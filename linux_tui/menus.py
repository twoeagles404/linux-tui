"""Category hierarchy mirroring the portable parts of ProxMenux."""
import shutil
import subprocess
from . import __version__
from .admin import TOOLS, apply_package
from .core import discover, run_action
from .ui import TerminalUI

MAIN = (
    ('1', 'Settings post-install Linux'),
    ('2', 'Hardware: GPUs and Coral-TPU'),
    ('3', 'Virtual machines and containers'),
    ('4', 'Disk and Storage Manager'),
    ('5', 'Mount and Share Manager'),
    ('6', 'Applications and Helper Tools'),
    ('7', 'Network Management'),
    ('8', 'Security'),
    ('9', 'Utilities and Tools'),
    ('b', 'Backup and Restore'),
    ('h', 'Help and Info Commands'),
    ('s', 'Settings'),
    ('0', 'Exit'),
)

SECTIONS = {
    '1': [('refresh', 'Refresh package repositories'), ('upgrade', 'Update system packages'),
          ('guest-agent', 'Install QEMU guest agent'), ('tools', 'Install common CLI utilities'),
          ('services', 'Review failed services'), ('logs', 'Review system warnings')],
    '2': [('pci', 'PCI devices / GPU inventory'), ('usb', 'USB devices / Coral inventory'),
          ('sensors', 'Temperatures and sensors'), ('gpu', 'NVIDIA GPU status'),
          ('hardware-help', 'GPU/TPU installation and passthrough support')],
    '3': [('libvirt', 'List libvirt virtual machines'), ('lxc', 'List native LXC containers'),
          ('incus', 'List Incus instances'), ('lxd', 'List LXD instances'),
          ('virt-help', 'Host capabilities and creation support')],
    '4': [('disks', 'Disks and partitions'), ('filesystems', 'Filesystem usage'),
          ('mounts', 'Mount inventory'), ('zfs', 'ZFS pool status'), ('storage-help', 'Disk changes and SMART support')],
    '5': [('mounts', 'Mounted filesystems and shares'), ('fstab', 'Persistent mounts (fstab)'),
          ('nfs', 'NFS exports'), ('samba', 'Validate and show Samba configuration'),
          ('share-help', 'Mount and share administration support')],
    '6': [('docker', 'Docker containers'), ('podman', 'Podman containers'),
          ('tools', 'Install common CLI utilities'), ('apps-help', 'Application recipe support')],
    '7': [('addresses', 'Network interfaces and addresses'), ('routes', 'Routing tables'),
          ('listeners', 'Listening sockets'), ('networkctl', 'systemd network status'),
          ('nmcli', 'NetworkManager connections'), ('network-help', 'Network configuration support')],
    '8': [('fail2ban-install', 'Install Fail2ban'), ('fail2ban-status', 'Fail2ban status'),
          ('lynis-install', 'Install Lynis'), ('lynis', 'Run Lynis system audit'),
          ('ufw', 'UFW firewall status'), ('firewalld', 'Firewalld status'), ('nft', 'nftables rules')],
    '9': [('tools', 'Install common CLI utilities'), ('processes', 'Running processes'),
          ('memory', 'Memory usage'), ('services', 'Failed services'), ('logs', 'System warnings')],
    'b': [('backup-help', 'Backup and restore implementation status'), ('borg', 'Borg version / availability'),
          ('restic', 'Restic version / availability')],
    'h': [('discovery', 'Environment and capabilities'), ('system', 'Kernel and architecture'),
          ('scope', 'Feature coverage and Proxmox exclusions'), ('keys', 'Keyboard controls')],
    's': [('version', 'Version information'), ('backend', 'Terminal UI backend'), ('scope', 'Implementation status')],
}

COMMANDS = {
    'gpu': ('nvidia-smi',), 'libvirt': ('virsh', 'list', '--all'),
    'lxc': ('lxc-ls', '--fancy'), 'incus': ('incus', 'list'), 'lxd': ('lxc', 'list'),
    'zfs': ('zpool', 'status'), 'fstab': ('cat', '/etc/fstab'),
    'nfs': ('exportfs', '-v'), 'samba': ('testparm', '-s'),
    'docker': ('docker', 'ps', '-a'), 'podman': ('podman', 'ps', '-a'),
    'networkctl': ('networkctl', 'list', '--no-pager'), 'nmcli': ('nmcli', 'connection', 'show'),
    'fail2ban-status': ('fail2ban-client', 'status'), 'lynis': ('lynis', 'audit', 'system', '--quick'),
    'ufw': ('ufw', 'status', 'verbose'), 'firewalld': ('firewall-cmd', '--list-all'),
    'nft': ('nft', 'list', 'ruleset'), 'borg': ('borg', '--version'), 'restic': ('restic', 'version'),
}

STATUS = 'The full-screen category menus, diagnostics, native tool launchers and reviewed package operations are implemented. Full portable ProxMenux parity is still incomplete.\n\nNot yet implemented: tuning/rollback profiles, VM creation, device passthrough, disk formatting, share editing, network/firewall editing, backup/restore orchestration, web dashboard, notifications and translations.\n\nProxmox APIs, PVE commands, repositories, clusters, PBS and subscription modifications are excluded.'
GUIDES = {
    'hardware-help': 'GPU and TPU inventory works when devices are exposed to this guest. Automated driver installation and host passthrough workflows are not implemented yet. A container cannot change host drivers or assign devices from inside the guest.',
    'virt-help': 'Inventory uses local libvirt, native LXC, Incus or LXD tools when installed. Creation, lifecycle and migration wizards are not implemented yet. Ordinary guests cannot manage their hypervisor. No Proxmox API is used.',
    'storage-help': 'Disk, filesystem, mount and ZFS inspection is available. Formatting, SMART test scheduling and disk assignment workflows are not implemented yet.',
    'share-help': 'Mount inventory, fstab, NFS exports and Samba configuration inspection are available. Creating/editing shares and persistent mounts is not implemented yet.',
    'apps-help': 'Docker/Podman inventory and CLI utility installation are available. Managed application recipes, updates and container recreation are not implemented yet. No external community scripts are downloaded or executed.',
    'network-help': 'Address, route, socket and network-manager inspection is available. Editing/restarting network configuration with automatic SSH recovery is not implemented yet.',
    'backup-help': 'Backup and restore orchestration is not implemented yet. Borg and Restic availability checks are available. The project does not currently create or restore system backups.',
    'scope': STATUS,
    'keys': 'Use Up/Down to move, Enter to choose, Tab to move between OK and Cancel, and Escape/Cancel to return. Main-menu 0 exits. Package changes show a command preview and default to Cancel; the package manager also prompts before changes.',
}


def display_result(result):
    if not result.get('ok'):
        return result.get('error') or f"Command failed (exit {result.get('exit_code')}).\n\n{result.get('stderr', '')}\n{result.get('stdout', '')}"
    return (result.get('stdout') or '(No output)') + ('\n\n' + result['stderr'] if result.get('stderr') else '')


def dispatch(ui, key):
    if key in GUIDES:
        ui.message('Feature information', GUIDES[key])
    elif key == 'discovery':
        info = discover()
        ui.message('Environment and capabilities', '\n'.join(f'{name}: {value}' for name, value in info.items()))
    elif key == 'version':
        ui.message('Linux TUI', f'Version {__version__}\nhttps://github.com/twoeagles404/linux-tui\n\n' + STATUS)
    elif key == 'backend':
        ui.message('Terminal UI backend', ui.program or 'Built-in curses (dialog-style blue screen)')
    elif key in ('refresh', 'upgrade'):
        apply_package(ui, key)
    elif key in ('guest-agent', 'fail2ban-install', 'lynis-install'):
        package = {'guest-agent': 'qemu-guest-agent', 'fail2ban-install': 'fail2ban', 'lynis-install': 'lynis'}[key]
        apply_package(ui, 'install', (package,))
    elif key == 'tools':
        while True:
            package = ui.menu('Install CLI utilities', [(name, name) for name in TOOLS] + [('0', 'Return')])
            if package is None or package == '0':
                return
            apply_package(ui, 'install', (package,))
    elif key in COMMANDS:
        command = COMMANDS[key]
        if not shutil.which(command[0]):
            ui.message('Tool unavailable', f'{command[0]} is not installed. No changes were made.')
            return
        if key == 'lynis' and not ui.confirm('Run security audit', 'Lynis writes its audit log/report. Run the system audit?'):
            return
        try:
            result = subprocess.run(command, capture_output=True, text=True, errors='replace', timeout=120, check=False)
            ui.message(' '.join(command), display_result({'ok': result.returncode == 0, 'exit_code': result.returncode,
                                                         'stdout': result.stdout[:100000], 'stderr': result.stderr[:8192]}))
        except (OSError, subprocess.TimeoutExpired) as error:
            ui.message('Command failed', str(error))
    else:
        ui.message('Diagnostic results', display_result(run_action(key)))


def launch(backend='auto'):
    ui = TerminalUI(backend)
    while True:
        choice = ui.menu('Main Linux TUI', MAIN)
        if choice is None or choice == '0':
            return 0
        title = dict(MAIN)[choice]
        while True:
            entries = [(str(i), label) for i, (_, label) in enumerate(SECTIONS[choice], 1)] + [('0', 'Return to Main Menu')]
            item = ui.menu(title, entries)
            if item is None or item == '0':
                break
            dispatch(ui, SECTIONS[choice][int(item) - 1][0])
