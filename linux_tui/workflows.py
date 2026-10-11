"""Reviewed administration workflows; subprocesses always receive argument arrays."""
import datetime
from contextlib import contextmanager, nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import uuid
import zipfile

STATE = Path('/var/lib/linux-tui')
PROFILES = {
    'journal': ('Bound persistent journal to 256 MiB', '/etc/systemd/journald.conf.d/90-linux-tui.conf',
                '[Journal]\nStorage=persistent\nSystemMaxUse=256M\nRuntimeMaxUse=64M\n',
                [('systemctl', 'restart', 'systemd-journald')]),
    'panic': ('Reboot 10 seconds after a kernel panic', '/etc/sysctl.d/90-linux-tui-panic.conf',
              'kernel.panic = 10\n', [('sysctl', '--system')]),
    'ipv4': ('Prefer IPv4 for APT downloads', '/etc/apt/apt.conf.d/90-linux-tui-ipv4',
             'Acquire::ForceIPv4 "true";\n', []),
    'languages': ('Disable translated APT package indexes', '/etc/apt/apt.conf.d/90-linux-tui-languages',
                  'Acquire::Languages "none";\n', []),
    'memory': ('Reduce swap preference (swappiness 10)', '/etc/sysctl.d/90-linux-tui-memory.conf',
               'vm.swappiness = 10\n', [('sysctl', '--system')]),
    'fastopen': ('Enable TCP Fast Open for clients and servers', '/etc/sysctl.d/90-linux-tui-fastopen.conf',
                 'net.ipv4.tcp_fastopen = 3\n', [('sysctl', '--system')]),
    'limits': ('Raise PAM open-file soft/hard limits to 65536', '/etc/security/limits.d/90-linux-tui.conf',
               '* soft nofile 65536\n* hard nofile 65536\nroot soft nofile 65536\nroot hard nofile 65536\n', []),
}


def run(command, timeout=120):
    result = subprocess.run(list(command), capture_output=True, text=True, errors='replace', timeout=timeout,
                            env={**os.environ, 'LC_ALL': 'C', 'SYSTEMD_PAGER': 'cat'})
    if result.returncode:
        raise RuntimeError(f'{shlex.join(command)}\nExit {result.returncode}\n{result.stderr[-8000:]}')
    return result.stdout


def require_root():
    if not hasattr(os, 'geteuid') or os.geteuid() != 0:
        raise RuntimeError('Run linux-tui as root for this operation.')


def name(value):
    if not value or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}', value):
        raise ValueError('Use a name containing letters, numbers, dots, underscores, colons, @, + or hyphens.')
    return value


def execute(ui, title, commands, root=True):
    if root:
        require_root()
    missing = [cmd[0] for cmd in commands if not shutil.which(cmd[0])]
    if missing:
        raise RuntimeError('Install the required tools first: ' + ', '.join(sorted(set(missing))))
    if not ui.confirm(title, '\n'.join(shlex.join(cmd) for cmd in commands)):
        return
    output = []
    for command in commands:
        output.append(run(command, timeout=3600))
    ui.message(title, '\n'.join(output) or 'Completed successfully.')


def atomic_write(path, data, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def configuration_lock(path, state):
    lockdir = Path(state) / 'locks'
    lockdir.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = lockdir / (hashlib.sha256(str(Path(path).absolute()).encode()).hexdigest() + '.lock')
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if os.name == 'posix':
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('Another Linux TUI operation is changing this configuration file.') from None
        yield
    finally:
        os.close(fd)


def change_file(path, data, commands=(), state=STATE, rollback_commands=()):
    with configuration_lock(path, state):
        return _change_file(path, data, commands, state, rollback_commands)


def _change_file(path, data, commands, state, rollback_commands):
    """Record original metadata/content before writing, and roll back on apply failure."""
    path, state = Path(path), Path(state)
    if path.is_symlink():
        raise ValueError('Refusing to replace a symlink configuration file.')
    transaction = state / 'changes' / uuid.uuid4().hex
    transaction.mkdir(parents=True, mode=0o700)
    existed = path.exists()
    metadata = {'path': str(path), 'existed': existed, 'commands': list(commands), 'rollback_commands': list(rollback_commands),
                'mode': path.stat().st_mode & 0o777 if existed else 0o644,
                'uid': path.stat().st_uid if existed else None, 'gid': path.stat().st_gid if existed else None,
                'created': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'status': 'pending'}
    if existed:
        atomic_write(transaction / 'original', path.read_bytes())
    atomic_write(transaction / 'record.json', json.dumps(metadata).encode())
    try:
        atomic_write(path, data, metadata['mode'])
        if existed and hasattr(os, 'chown'):
            os.chown(path, metadata['uid'], metadata['gid'])
        for command in commands:
            run(command)
        metadata['status'] = 'applied'
        metadata['sha256'] = hashlib.sha256(data).hexdigest()
        atomic_write(transaction / 'record.json', json.dumps(metadata).encode())
    except Exception:
        restore_file(transaction, reload=False, locked=True)
        # Reload the restored configuration as well, without masking the original error.
        for command in (*commands, *rollback_commands):
            try:
                run(command)
            except Exception:
                pass
        raise
    return transaction


def restore_file(transaction, reload=True, locked=False):
    transaction = Path(transaction)
    metadata = json.loads((transaction / 'record.json').read_text())
    with nullcontext() if locked else configuration_lock(metadata['path'], transaction.parent.parent):
        _restore_file(transaction, metadata, reload)


def _restore_file(transaction, metadata, reload):
    path = Path(metadata['path'])
    if path.is_symlink():
        raise ValueError('Configuration target became a symlink; inspect it manually.')
    if metadata['existed']:
        atomic_write(path, (transaction / 'original').read_bytes(), metadata['mode'])
        if hasattr(os, 'chown'):
            os.chown(path, metadata['uid'], metadata['gid'])
    else:
        path.unlink(missing_ok=True)
    if reload:
        failures = []
        for command in (*metadata['commands'], *metadata.get('rollback_commands', [])):
            try:
                run(command)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                failures.append(str(error))
        if failures:
            raise RuntimeError('Original file restored, but runtime reload needs attention:\n' + '\n'.join(failures))
    metadata['status'] = 'restored'
    atomic_write(transaction / 'record.json', json.dumps(metadata).encode())


def profiles(ui):
    selected = ui.menu('Post-install profiles', [(key, item[0]) for key, item in PROFILES.items()] + [('rollback', 'Undo a previous configuration change')])
    if not selected:
        return
    require_root()
    if selected == 'rollback':
        records = sorted((STATE / 'changes').glob('*/record.json'), key=lambda p: p.stat().st_mtime, reverse=True)
        active = [(p.parent, json.loads(p.read_text())) for p in records]
        active = [(p, record) for p, record in active if record['status'] == 'applied']
        key = ui.menu('Undo configuration change', [(str(i), record['created'] + ' ' + record['path']) for i, (_, record) in enumerate(active)]) if active else None
        if key is not None:
            transaction, record = active[int(key)]
            target = Path(record['path'])
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != record['sha256']:
                raise RuntimeError('File changed since this profile was applied. Inspect it before restoring the saved original.')
            if ui.confirm('Restore original configuration', record['path']):
                restore_file(transaction)
                ui.message('Configuration restored', record['path'])
        elif not active:
            ui.message('Undo configuration', 'No applied configuration changes.')
        return
    title, path, content, commands = PROFILES[selected]
    if commands and commands[0][0] == 'sysctl':
        if Path('/run/systemd/container').exists() or Path('/.dockerenv').exists():
            raise RuntimeError('Kernel tuning must be performed on the host, not from a container.')
    if selected in ('ipv4', 'languages') and not shutil.which('apt-get'):
        raise RuntimeError('This profile requires APT.')
    if selected == 'journal' and not Path('/run/systemd/system').exists():
        raise RuntimeError('This profile requires a running systemd instance.')
    if ui.confirm(title, f'Write {path}:\n\n{content}\nAn original copy is kept for undo.'):
        rollback = []
        if commands and commands[0][0] == 'sysctl':
            for line in content.splitlines():
                key = line.split('=', 1)[0].strip()
                rollback.append(('sysctl', '-w', key + '=' + run(('sysctl', '-n', key)).strip()))
        transaction = change_file(path, content.encode(), commands, rollback_commands=rollback)
        ui.message('Profile applied', f'Undo record: {transaction}')


def services(ui):
    if Path('/run/systemd/system').exists():
        lines = run(('systemctl', 'list-unit-files', '--type=service', '--no-legend', '--no-pager')).splitlines()
        units = [(line.split()[0], line.split()[0] + ' ' + line.split()[1]) for line in lines if len(line.split()) >= 2]
        unit = ui.menu('System services', units)
        if not unit:
            return
        action = ui.menu(unit, [(x, x.capitalize()) for x in ('status', 'start', 'stop', 'restart', 'enable', 'disable')])
        if not action:
            return
        if action == 'status':
            result = subprocess.run(['systemctl', 'status', unit, '--no-pager'], capture_output=True, text=True)
            ui.message(unit, result.stdout + result.stderr)
        else:
            execute(ui, 'Manage service', [('systemctl', action, name(unit))])
    elif shutil.which('rc-service'):
        service = ui.input('OpenRC service', 'Service name:')
        if not service:
            return
        action = ui.menu(service, [(x, x.capitalize()) for x in ('status', 'start', 'stop', 'restart')])
        if action:
            execute(ui, 'Manage OpenRC service', [('rc-service', name(service), action)], root=action != 'status')
    else:
        raise RuntimeError('No running systemd or OpenRC service manager detected.')


def instances(ui):
    backend = ui.menu('Virtualization backend', [(x, x) for x in ('virsh', 'incus', 'lxc', 'lxc-native') if shutil.which('lxc-ls' if x == 'lxc-native' else x)])
    if not backend:
        return
    action = ui.menu('Instance management', [(x, x.capitalize()) for x in ('list', 'create', 'start', 'stop', 'restart', 'delete')])
    if not action:
        return
    if action == 'list':
        command = ('virsh', 'list', '--all') if backend == 'virsh' else ('lxc-ls', '--fancy') if backend == 'lxc-native' else (backend, 'list')
        ui.message('Instances', run(command))
        return
    instance = ui.input('Instance name', 'Instance name:')
    if not instance:
        return
    name(instance)
    if backend == 'virsh':
        if action == 'create':
            method = ui.menu('Create libvirt VM', [('xml', 'Define existing domain XML'), ('disk', 'Import an existing disk image')])
            if not method:
                return
            image = ui.input('Existing VM definition' if method == 'xml' else 'Existing VM disk', 'Absolute path to the XML file:' if method == 'xml' else 'Absolute path to a qcow2 disk image:')
            if not image:
                return
            if not Path(image).is_absolute() or not Path(image).is_file():
                raise ValueError('Choose an existing absolute file.')
            if method == 'xml':
                commands = [('virsh', 'define', image)]
            else:
                if ',' in image:
                    raise ValueError('Disk paths cannot contain commas.')
                memory = ui.input('VM memory', 'Memory in MiB:', '2048')
                cpus = ui.input('VM CPUs', 'Virtual CPU count:', '2') if memory else None
                if not cpus:
                    return
                if not memory.isdigit() or not 256 <= int(memory) <= 1048576 or not cpus.isdigit() or not 1 <= int(cpus) <= 256:
                    raise ValueError('Memory must be 256–1048576 MiB; CPUs must be 1–256.')
                commands = [('virt-install', '--name', instance, '--memory', memory, '--vcpus', cpus,
                             '--import', '--disk', f'path={image},format=qcow2', '--network', 'network=default',
                             '--osinfo', 'detect=on,require=off', '--graphics', 'none', '--noautoconsole')]
        else:
            verb = {'start': 'start', 'stop': 'shutdown', 'restart': 'reboot', 'delete': 'undefine'}[action]
            commands = [('virsh', verb, instance)]
    elif backend == 'lxc-native':
        if action == 'create':
            distro = ui.input('LXC distribution', 'Distribution (e.g. debian):', 'debian')
            release = ui.input('LXC release', 'Release (e.g. trixie):', 'trixie') if distro else None
            arch = ui.menu('Container architecture', [('amd64', 'amd64'), ('arm64', 'arm64')]) if release else None
            if not arch:
                return
            commands = [('lxc-create', '-n', instance, '-t', 'download', '--', '--dist', name(distro), '--release', name(release), '--arch', arch)]
        else:
            command = {'start': ('lxc-start', '-n', instance), 'stop': ('lxc-stop', '-n', instance),
                       'restart': ('lxc-stop', '-r', '-n', instance), 'delete': ('lxc-destroy', '-n', instance)}[action]
            commands = [command]
    else:
        if action == 'create':
            image = ui.input('Container image', 'Image alias, e.g. images:debian/13:')
            if not image:
                return
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}', image) or '..' in image.split('/'):
                raise ValueError('Invalid container image reference.')
            commands = [(backend, 'launch', image, instance)]
        else:
            commands = [(backend, action, instance)]
    execute(ui, 'Review instance operation', commands)


def containers(ui):
    engine = ui.menu('Container engine', [(x, x.capitalize()) for x in ('docker', 'podman') if shutil.which(x)])
    if not engine:
        return
    raw = run((engine, 'ps', '-a', '--format', '{{.ID}} {{.Names}} {{.Status}}'))
    entries = [(line.split()[0], line) for line in raw.splitlines() if line.strip()]
    selected = ui.menu('Containers', entries + [('pull', 'Pull a container image')])
    if selected == 'pull':
        image = ui.input('Pull image', 'Image reference (include a version tag):')
        if image:
            if image.startswith('-') or any(c.isspace() for c in image):
                raise ValueError('Invalid image reference.')
            execute(ui, 'Pull image', [(engine, 'pull', image)], root=False)
    elif selected:
        action = ui.menu('Container operation', [(x, x.capitalize()) for x in ('logs', 'inspect', 'start', 'stop', 'restart', 'remove')])
        if not action:
            return
        command = (engine, 'logs', '--tail', '200', selected) if action == 'logs' else (engine, 'inspect', selected) if action == 'inspect' else (engine, 'rm' if action == 'remove' else action, selected)
        if action in ('logs', 'inspect'):
            ui.message(action.capitalize(), run(command))
        else:
            execute(ui, 'Review container operation', [command], root=False)


def firewall(ui):
    backend = next((x for x in ('ufw', 'firewall-cmd') if shutil.which(x)), None)
    if not backend:
        raise RuntimeError('Install UFW or firewalld first. Raw nftables editing is not yet supported.')
    action = ui.menu('Firewall rules', [('status', 'Show rules'), ('allow', 'Allow a port'), ('remove', 'Remove an allow rule')])
    if not action:
        return
    if action == 'status':
        ui.message('Firewall rules', run((backend, 'status', 'numbered') if backend == 'ufw' else (backend, '--list-all')))
        return
    port = ui.input('Firewall port', 'Port/protocol, e.g. 443/tcp:')
    if not port:
        return
    match = re.fullmatch(r'(\d{1,5})/(tcp|udp)', port)
    if not match or not 1 <= int(match[1]) <= 65535:
        raise ValueError('Enter a port from 1 to 65535 followed by /tcp or /udp.')
    commands = [(backend, 'allow', port)] if action == 'allow' else [(backend, 'delete', 'allow', port)]
    if backend == 'firewall-cmd':
        verb = '--add-port=' if action == 'allow' else '--remove-port='
        commands = [(backend, '--permanent', verb + port), (backend, verb + port)]
    execute(ui, 'Review firewall rule (may affect remote access)', commands)


def storage(ui):
    inventory = json.loads(run(('lsblk', '--json', '--nodeps', '--output', 'PATH,SIZE,MODEL,TYPE')))
    disks = [(disk['path'], f"{disk['path']} {disk.get('size', '')} {disk.get('model') or ''}")
             for disk in inventory['blockdevices'] if disk['type'] == 'disk']
    disk = ui.menu('SMART disk health', disks)
    if not disk:
        return
    action = ui.menu('SMART operations', [('health', 'Health, attributes and self-test log'),
                                         ('short', 'Start short self-test'), ('long', 'Start extended self-test'),
                                         ('abort', 'Abort current self-test')])
    if not action:
        return
    require_root()
    if not shutil.which('smartctl'):
        raise RuntimeError('Install smartmontools first. Virtual disks often do not expose SMART data.')
    if action == 'health':
        result = subprocess.run(['smartctl', '-a', disk], capture_output=True, text=True)
        # smartctl uses a bitmask; health warnings are data, not empty command errors.
        ui.message('SMART health', result.stdout + result.stderr + f'\nSMART status bitmask: {result.returncode}')
    else:
        command = ('smartctl', '-X', disk) if action == 'abort' else ('smartctl', '-t', action, disk)
        execute(ui, 'Review disk self-test', [command])


def empty_disks(inventory, swaps=()):
    """Only whole disks without partitions, signatures, mounts or read-only flags."""
    return [disk for disk in inventory.get('blockdevices', [])
            if disk.get('type') == 'disk' and not disk.get('children') and not disk.get('fstype')
            and not disk.get('ro') and not any(disk.get('mountpoints') or []) and disk.get('path') not in swaps]


def format_disk(ui):
    require_root()
    if Path('/run/systemd/container').exists() or Path('/.dockerenv').exists() or os.environ.get('container'):
        raise RuntimeError('Format disks from the host or a VM with a dedicated disk, not a container.')
    command = ('lsblk', '--json', '--output', 'PATH,TYPE,FSTYPE,MOUNTPOINTS,RO,SERIAL,SIZE,MAJ:MIN')
    swaps = [line.split()[0] for line in Path('/proc/swaps').read_text().splitlines()[1:]]
    disks = empty_disks(json.loads(run(command)), swaps)
    selected = ui.menu('Format an unused whole disk', [(str(i), f"{disk['path']} {disk['size']} serial={disk.get('serial') or 'unknown'}") for i, disk in enumerate(disks)]) if disks else None
    if selected is None:
        if not disks:
            ui.message('No eligible disks', 'Only whole disks with no partitions, filesystem signatures, mounts or swap use are eligible. Mounted/system disks cannot be selected.')
        return
    disk = disks[int(selected)]
    device = Path(disk['path'])
    if not device.is_block_device():
        raise ValueError('Selected path is not a block device.')
    holders = Path('/sys/dev/block', disk['maj:min'], 'holders')
    if not holders.is_dir() or any(holders.iterdir()):
        raise ValueError('Disk is in use by another block device, or holder information is unavailable.')
    if run(('wipefs', '--no-act', '--noheadings', '--output', 'TYPE', str(device))).strip():
        raise ValueError('Disk has signatures; this workflow only formats empty disks.')
    filesystem = ui.menu('New filesystem', [('ext4', 'ext4'), ('xfs', 'XFS')])
    if not filesystem:
        return
    typed = ui.input('Confirm destructive disk format', f'Type the exact disk path {device} to erase it:')
    if typed != str(device):
        raise ValueError('Disk identity confirmation did not match. No changes made.')
    formatter = 'mkfs.' + filesystem
    if not shutil.which(formatter):
        raise RuntimeError('Install the filesystem tool first: ' + formatter)
    if not ui.confirm('Format whole disk — permanent data loss; no undo', shlex.join((formatter, str(device)))):
        return
    fresh = empty_disks(json.loads(run(command)), [line.split()[0] for line in Path('/proc/swaps').read_text().splitlines()[1:]])
    if disk not in fresh or any(holders.iterdir()) or run(('wipefs', '--no-act', '--noheadings', '--output', 'TYPE', str(device))).strip():
        raise ValueError('Disk state changed; restart the workflow.')
    ui.message('Filesystem created', run((formatter, str(device)), timeout=3600) or str(device))


def mounts(ui):
    action = ui.menu('Mount administration', [('local', 'Add persistent local filesystem mount'),
                                             ('nfs', 'Add persistent NFS client mount'),
                                             ('mount', 'Mount an fstab entry'), ('unmount', 'Unmount a filesystem')])
    if not action:
        return
    require_root()
    target = ui.input('Mount point', 'Existing absolute mount directory (no spaces):')
    if not target:
        return
    path = Path(target)
    if not path.is_absolute() or not path.is_dir() or path.is_symlink() or re.search(r'\s', target) or target == '/':
        raise ValueError('Use an existing non-root absolute directory without spaces or symlinks.')
    if action in ('mount', 'unmount'):
        execute(ui, 'Review mount operation', [('mount' if action == 'mount' else 'umount', '--', target)])
        return
    source = ui.input('Mount source', 'UUID=... or /dev/...:' if action == 'local' else 'NFS server:/export:')
    if not source:
        return
    if re.search(r'\s', source) or source.startswith('-'):
        raise ValueError('Invalid mount source.')
    if action == 'local' and not (re.fullmatch(r'UUID=[A-Za-z0-9-]+', source) or source.startswith('/dev/')):
        raise ValueError('Choose a device path or filesystem UUID.')
    if action == 'nfs' and not re.fullmatch(r'[A-Za-z0-9_.-]+:/[^\s]*', source):
        raise ValueError('Use server:/export syntax.')
    kind = 'nfs' if action == 'nfs' else ui.menu('Filesystem type', [(x, x) for x in ('ext4', 'xfs', 'btrfs', 'vfat')])
    if not kind:
        return
    fstab = Path('/etc/fstab')
    original = fstab.read_text()
    for line in original.splitlines():
        fields = line.split()
        if fields and not line.lstrip().startswith('#') and len(fields) > 1 and fields[1] == target:
            raise ValueError('This mount point already has an fstab entry.')
    entry = f'{source}\t{target}\t{kind}\tdefaults,nofail\t0\t0\n'
    if ui.confirm('Add persistent mount', entry + '\nThe mount is tested now; fstab is restored if mounting fails.'):
        transaction = change_file(fstab, (original.rstrip() + '\n' + entry).encode(), [('mount', '--', target)])
        ui.message('Persistent mount added', f'{target}\nUndo record: {transaction}\nUnmount before undoing the fstab entry.')


def network_tools(ui):
    action = ui.menu('Network diagnostics', [('ping', 'Ping a host'), ('trace', 'Trace a route'),
                                           ('dns', 'Resolve a hostname'), ('speed', 'Show interface byte counters')])
    if not action:
        return
    if action == 'speed':
        ui.message('Interface traffic counters', Path('/proc/net/dev').read_text())
        return
    host = ui.input('Network target', 'Hostname or IP address:')
    if not host:
        return
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.:%_-]{0,252}', host):
        raise ValueError('Enter a hostname or IP address, without spaces or command options.')
    command = ('ping', '-c', '4', '-W', '3', host) if action == 'ping' else ('tracepath', host) if action == 'trace' else ('getent', 'ahosts', host)
    ui.message('Network results', run(command, timeout=60))


def zfs_tools(ui):
    action = ui.menu('ZFS administration', [('status', 'Pool status'), ('snapshot', 'Create a dataset snapshot'),
                                           ('list', 'List snapshots'), ('trim', 'Start pool TRIM'), ('scrub', 'Start pool scrub')])
    if not action:
        return
    if action in ('status', 'list'):
        ui.message('ZFS', run(('zpool', 'status') if action == 'status' else ('zfs', 'list', '-t', 'snapshot')))
        return
    target = ui.input('ZFS target', 'Dataset name:' if action == 'snapshot' else 'Pool name:')
    if not target:
        return
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:-]*', target) or '..' in target:
        raise ValueError('Invalid ZFS pool/dataset name.')
    commands = [('zfs', 'snapshot', target + '@linux-tui-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))] if action == 'snapshot' else [('zpool', action, target)]
    execute(ui, 'Review ZFS operation', commands)


def system_settings(ui):
    action = ui.menu('System settings', [('timezone', 'Set time zone'), ('ntp', 'Enable network time synchronization'),
                                        ('hostname', 'Set hostname')])
    if not action:
        return
    if action == 'ntp':
        commands = [('timedatectl', 'set-ntp', 'true')]
    else:
        value = ui.input('Time zone' if action == 'timezone' else 'Hostname', 'IANA time zone (e.g. America/Los_Angeles):' if action == 'timezone' else 'New hostname:')
        if not value:
            return
        if action == 'timezone':
            if value.startswith('/') or '..' in value.split('/') or not re.fullmatch(r'[A-Za-z0-9_+/-]+', value) or not Path('/usr/share/zoneinfo', value).is_file():
                raise ValueError('Choose a valid installed IANA time zone.')
            commands = [('timedatectl', 'set-timezone', value)]
        else:
            commands = [('hostnamectl', 'set-hostname', name(value))]
    execute(ui, 'Review system settings', commands)


def shares(ui):
    kind = ui.menu('Create server share', [('nfs', 'NFS export (specified client network)'), ('smb', 'Samba authenticated share (existing Samba users)')])
    if not kind:
        return
    require_root()
    folder = ui.input('Shared directory', 'Existing absolute directory (no spaces):')
    if not folder:
        return
    path = Path(folder)
    if not path.is_absolute() or not path.is_dir() or path.is_symlink() or not re.fullmatch(r'/[A-Za-z0-9_./-]+', folder) or folder == '/':
        raise ValueError('Choose an existing absolute non-root directory without spaces.')
    if kind == 'nfs':
        import ipaddress
        client = ui.input('Allowed client network', 'Client IPv4/IPv6 address or CIDR network:')
        if not client:
            return
        client = str(ipaddress.ip_network(client, strict=False))
        content = f'{folder} {client}(rw,sync,no_subtree_check,root_squash)\n'
        config = Path('/etc/exports.d') / ('linux-tui-' + hashlib.sha256(folder.encode()).hexdigest()[:12] + '.exports')
        commands = [('exportfs', '-ra')]
    else:
        share = ui.input('SMB share name', 'Share name:')
        if not share:
            return
        name(share)
        users = ui.input('Samba users', 'One existing Samba username:')
        if not users:
            return
        name(users)
        config = Path('/etc/samba/smb.conf')
        existing = config.read_text()
        if re.search(r'^\s*\[' + re.escape(share) + r'\]', existing, re.MULTILINE | re.IGNORECASE):
            raise ValueError('Share name already exists.')
        content = existing.rstrip() + f'\n\n[{share}]\npath = {folder}\nbrowseable = yes\nread only = no\nguest ok = no\nvalid users = {users}\n'
        commands = [('testparm', '-s'), ('smbcontrol', 'all', 'reload-config')]
    for command in commands:
        if not shutil.which(command[0]):
            raise RuntimeError('Install the share server tools first: ' + command[0])
    if ui.confirm('Review server share', f'{config}\n{content}\nDirectory permissions are not changed. Original configuration is saved for undo.'):
        transaction = change_file(config, content.encode(), commands)
        ui.message('Share configured', f'Undo record: {transaction}')


def compose(ui):
    engine = ui.menu('Compose engine', [(x, x) for x in ('docker', 'podman') if shutil.which(x)])
    if not engine:
        return
    file = ui.input('Compose project', 'Absolute path to your compose.yaml:')
    if not file:
        return
    if not Path(file).is_absolute() or not Path(file).is_file():
        raise ValueError('Choose an existing Compose file.')
    action = ui.menu('Compose operation', [('validate', 'Validate project'), ('up', 'Deploy / recreate project'),
                                          ('pull', 'Pull updated project images'), ('down', 'Stop and remove project containers'), ('logs', 'Recent project logs')])
    if not action:
        return
    base = (engine, 'compose', '-f', file)
    # Validate before showing a mutation preview; Compose files are trusted admin input.
    validation = run((*base, 'config', '--quiet'))
    if action == 'validate':
        ui.message('Compose validation', 'Project is valid.')
    elif action == 'logs':
        ui.message('Compose logs', run((*base, 'logs', '--tail', '200', '--no-color')))
    else:
        suffix = ('up', '-d') if action == 'up' else (action,)
        execute(ui, 'Review Compose project operation', [(*base, *suffix)], root=False)


def fail2ban(ui):
    action = ui.menu('Fail2ban administration', [('status', 'Show jail status'), ('ban', 'Ban an address'),
                                              ('unban', 'Unban an address'), ('ssh', 'Configure SSH protection')])
    if not action:
        return
    require_root()
    if not shutil.which('fail2ban-client'):
        raise RuntimeError('Install Fail2ban first.')
    if action == 'ssh':
        port = ui.input('Protected SSH port', 'Actual SSH listening port:', '22')
        if not port:
            return
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError('Enter a valid SSH port.')
        import ipaddress
        trusted = ui.input('Trusted management network', 'Trusted IP/CIDR (e.g. your Tailscale subnet); always allow loopback:')
        if not trusted:
            return
        trusted = str(ipaddress.ip_network(trusted, strict=False))
        content = f'[sshd]\nenabled = true\nport = {port}\nmaxretry = 5\nfindtime = 10m\nbantime = 1h\nignoreip = 127.0.0.1/8 ::1 {trusted}\n'
        if ui.confirm('Configure SSH jail', content + '\nEnsure the trusted network includes your management address.'):
            commands = [('fail2ban-client', '-t'), ('fail2ban-client', 'reload')]
            transaction = change_file('/etc/fail2ban/jail.d/90-linux-tui.local', content.encode(), commands)
            ui.message('SSH jail configured', f'Undo record: {transaction}')
        return
    jail = ui.input('Jail name', 'Jail name:', 'sshd')
    if not jail:
        return
    name(jail)
    if action == 'status':
        ui.message('Fail2ban jail', run(('fail2ban-client', 'status', jail)))
    else:
        import ipaddress
        address = ui.input('IP address', 'Address to ban/unban:')
        if address:
            execute(ui, 'Review Fail2ban operation', [('fail2ban-client', 'set', jail, 'banip' if action == 'ban' else 'unbanip', str(ipaddress.ip_address(address)))])


def network_edit(ui):
    require_root()
    if not shutil.which('nmcli'):
        raise RuntimeError('This editor currently requires NetworkManager. Other network owners are not modified.')
    raw = run(('nmcli', '-t', '--escape', 'no', '-f', 'DEVICE,STATE', 'device', 'status'))
    devices = [(line.split(':', 1)[0], line) for line in raw.splitlines() if line.endswith(':connected')]
    device = ui.menu('Connected NetworkManager interfaces', devices)
    if not device:
        return
    name(device)
    import ipaddress
    address = ui.input('Temporary IPv4 configuration', 'IPv4 address/prefix (e.g. 192.168.1.10/24):')
    if not address:
        return
    address = str(ipaddress.IPv4Interface(address))
    gateway = ui.input('IPv4 gateway', 'IPv4 gateway:')
    if not gateway:
        return
    gateway = str(ipaddress.IPv4Address(gateway))
    command = ['nmcli', 'device', 'checkpoint', '--timeout', '120', device, '--',
               'nmcli', 'device', 'modify', device, 'ipv4.method', 'manual', 'ipv4.addresses', address, 'ipv4.gateway', gateway]
    if ui.confirm('Review temporary network change', shlex.join(command) + '\nNetworkManager will ask you to confirm connectivity on the terminal. Without confirmation, it restores the checkpoint after 120 seconds. Changes are temporary until the connection is reactivated.'):
        print('\033[2J\033[H', end='', flush=True)
        result = subprocess.run(command)
        ui.message('Network checkpoint completed', f'Exit code: {result.returncode}\nThe saved connection profile was not edited.')


def resource_monitor(ui):
    from .monitor import Collector
    import time
    collector = Collector()
    collector.sample()
    time.sleep(0.5)
    ui.message('Live resource sample', json.dumps(collector.sample(), indent=2) + '\n\nWeb dashboard: linux-tui --monitor\nOpen localhost:8008; username linux-tui. The private login token is stored under ~/.local/state/linux-tui/monitor-token.')


def gpu_drivers(ui):
    require_root()
    if Path('/run/systemd/container').exists() or Path('/.dockerenv').exists() or os.environ.get('container'):
        raise RuntimeError('Kernel GPU drivers belong on the host. Container device access must be assigned by that host.')
    from .core import os_release
    distro = os_release(Path('/etc/os-release').read_text()).get('ID')
    action = ui.menu('Distribution-managed GPU / TPU packages', [('nvidia', 'Install / update NVIDIA drivers'),
                                                               ('mesa', 'Install Intel/AMD Mesa Vulkan userspace'),
                                                               ('coral', 'Install Coral Edge TPU runtime (configured APT repo)')])
    if not action:
        return
    if action == 'nvidia':
        if distro == 'ubuntu':
            commands = [('ubuntu-drivers', 'autoinstall')]
        elif distro == 'debian':
            commands = [('apt-get', 'install', 'nvidia-driver')]
        else:
            raise RuntimeError('NVIDIA installation currently supports Ubuntu/Debian repository packages. Configure your distro driver repositories and install its recommended package manually on other distributions.')
    elif action == 'coral':
        if not shutil.which('apt-get'):
            raise RuntimeError('Coral runtime installation currently requires an already configured Edge TPU APT repository.')
        # Never silently add third-party repositories or import signing keys.
        candidate = run(('apt-cache', 'policy', 'libedgetpu1-std'))
        if 'Candidate:' not in candidate or 'Candidate: (none)' in candidate:
            raise RuntimeError('No Coral runtime candidate. Configure the official Edge TPU APT repository first.')
        commands = [('apt-get', 'install', 'libedgetpu1-std')]
    elif shutil.which('apt-get'):
        commands = [('apt-get', 'install', 'mesa-vulkan-drivers')]
    elif shutil.which('dnf'):
        commands = [('dnf', 'install', 'mesa-vulkan-drivers')]
    elif shutil.which('pacman'):
        commands = [('pacman', '-Syu', 'vulkan-intel', 'vulkan-radeon')]
    else:
        raise RuntimeError('Mesa installation currently supports APT, DNF and pacman.')
    if ui.confirm('GPU/TPU package requirements', 'Driver packages can rebuild kernel modules and require a reboot. Secure Boot may require enrolling a module-signing key. Intel/AMD kernel drivers ship with the distribution kernel. This workflow installs repository packages; it does not configure passthrough or reboot.'):
        execute(ui, 'Review driver package command', commands)


WORKFLOWS = {'profiles': profiles, 'manage-services': services, 'instances': instances,
             'containers': containers, 'firewall-edit': firewall, 'smart': storage,
             'mount-edit': mounts, 'network-tools': network_tools, 'zfs-tools': zfs_tools,
             'system-settings': system_settings, 'shares': shares, 'compose': compose,
             'fail2ban-manage': fail2ban, 'network-edit': network_edit, 'monitor': resource_monitor}
WORKFLOWS['format-disk'] = format_disk
WORKFLOWS['gpu-drivers'] = gpu_drivers


def dispatch_workflow(ui, key):
    try:
        WORKFLOWS[key](ui)
    except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile, subprocess.TimeoutExpired) as error:
        ui.message('Operation could not complete', str(error))
