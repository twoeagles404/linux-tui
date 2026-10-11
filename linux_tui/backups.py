"""Local configuration snapshots with checksums and transactional file restore."""
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import uuid
import zipfile

from .workflows import STATE, atomic_write, change_file, require_root, restore_file, run

MAX_BYTES = 512 * 1024 * 1024
MAX_FILES = 20000


def create_backup(source=Path('/etc'), destination=STATE / 'backups'):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_dir():
        raise ValueError('Backup source must be an existing directory.')
    if destination == source or source in destination.parents:
        raise ValueError('Store the backup outside its source directory.')
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    archive = destination / ('linux-tui-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8] + '.zip')
    pending = archive.with_suffix('.partial')
    manifest = {'version': 1, 'source': str(source), 'created': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'files': [], 'skipped': []}
    total = 0
    fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as file, zipfile.ZipFile(file, 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
            for directory, subdirs, files in os.walk(source, followlinks=False):
                for dirname in list(subdirs):
                    item = Path(directory) / dirname
                    if item.is_symlink():
                        subdirs.remove(dirname)
                        manifest['skipped'].append(str(item.relative_to(source)))
                for filename in files:
                    path = Path(directory) / filename
                    relative = path.relative_to(source).as_posix()
                    # O_NOFOLLOW closes the symlink race between inventory and read.
                    if path.is_symlink() or not path.is_file():
                        manifest['skipped'].append(relative)
                        continue
                    handle = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
                    with os.fdopen(handle, 'rb') as original:
                        metadata = os.fstat(original.fileno())
                        if not stat.S_ISREG(metadata.st_mode):
                            raise ValueError('Source changed to a non-regular file: ' + relative)
                        if metadata.st_size + total > MAX_BYTES or len(manifest['files']) >= MAX_FILES:
                            raise ValueError('Configuration snapshot exceeds 512 MiB or 20,000 files; use Borg for larger backups.')
                        data = original.read(MAX_BYTES - total + 1)
                    total += len(data)
                    if total > MAX_BYTES:
                        raise ValueError('Snapshot size limit exceeded.')
                    zipped.writestr('files/' + relative, data)
                    manifest['files'].append({'path': relative, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                                              'mode': stat.S_IMODE(metadata.st_mode) & 0o777, 'uid': metadata.st_uid, 'gid': metadata.st_gid})
            zipped.writestr('manifest.json', json.dumps(manifest, indent=2))
        os.replace(pending, archive)
    except Exception:
        pending.unlink(missing_ok=True)
        raise
    return archive


def verify_backup(archive):
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        if len(entries) > MAX_FILES + 1 or sum(item.file_size for item in entries) > MAX_BYTES + 16 * 1024 * 1024:
            raise ValueError('Archive exceeds configuration snapshot limits.')
        if len({entry.filename for entry in entries}) != len(entries):
            raise ValueError('Duplicate archive entries.')
        manifest = json.loads(zipped.read('manifest.json'))
        if not isinstance(manifest, dict) or manifest.get('version') != 1 or not isinstance(manifest.get('files'), list):
            raise ValueError('Unsupported snapshot manifest.')
        seen = set()
        for record in manifest['files']:
            if not isinstance(record, dict) or not isinstance(record.get('path'), str):
                raise ValueError('Invalid snapshot file record.')
            relative = PurePosixPath(record['path'])
            if relative.is_absolute() or '..' in relative.parts or '\\' in record['path'] or not relative.parts or record['path'] in seen:
                raise ValueError('Unsafe or duplicate snapshot path.')
            seen.add(record['path'])
            data = zipped.read('files/' + record['path'])
            if len(data) != record['size'] or hashlib.sha256(data).hexdigest() != record['sha256']:
                raise ValueError('Snapshot checksum mismatch: ' + record['path'])
            if not isinstance(record['mode'], int) or record['mode'] & ~0o777:
                raise ValueError('Unsupported file permission bits.')
            if any(not isinstance(record.get(key), int) or not 0 <= record[key] < 2**32 - 1 for key in ('uid', 'gid')):
                raise ValueError('Invalid snapshot file ownership.')
        if {item.filename for item in entries} != {'manifest.json', *('files/' + path for path in seen)}:
            raise ValueError('Archive contains unlisted files.')
    return manifest


def restore_backup(archive, target, selected=None, state=STATE):
    manifest = verify_backup(archive)
    target = Path(target).resolve()
    records = [record for record in manifest['files'] if selected is None or record['path'] in selected]
    # Validate every destination before changing any file. Never traverse a symlink.
    for record in records:
        path = target / record['path']
        if any(parent.is_symlink() for parent in (path, *path.parents) if parent != target.parent):
            raise ValueError('Restore path contains a symlink: ' + str(path))
        if path.exists() and not path.is_file():
            raise ValueError('Restore target is not a regular file: ' + str(path))
    transactions = []
    try:
        with zipfile.ZipFile(archive) as zipped:
            for record in records:
                path = target / record['path']
                transactions.append(change_file(path, zipped.read('files/' + record['path']), state=state))
                os.chmod(path, record['mode'])
                if hasattr(os, 'chown') and os.geteuid() == 0:
                    os.chown(path, record['uid'], record['gid'])
    except Exception:
        for transaction in reversed(transactions):
            restore_file(transaction, reload=False)
        raise
    return transactions


def backup_menu(ui):
    action = ui.menu('Configuration backups', [('create', 'Snapshot /etc (regular files; skips symlinks)'),
                                               ('verify', 'Verify a saved snapshot'), ('restore', 'Restore selected configuration files'),
                                               ('schedule', 'Schedule daily /etc snapshots (keep 7)'),
                                               ('unschedule', 'Disable daily snapshot timer'),
                                               ('borg', 'Encrypted Borg backups / checks / staged restore')])
    if not action:
        return
    require_root()
    if action == 'schedule':
        schedule(ui)
        return
    if action == 'unschedule':
        from .workflows import execute
        execute(ui, 'Disable backup schedule', [('systemctl', 'disable', '--now', 'linux-tui-backup.timer')])
        return
    if action == 'create':
        if ui.confirm('Create local configuration snapshot', 'Save regular files under /etc to /var/lib/linux-tui/backups.\nSnapshots contain secrets and are stored root-only. Symlinks, special files and empty directories are omitted. This is not a full-system backup.'):
            archive = create_backup()
            manifest = verify_backup(archive)
            ui.message('Backup verified', f'{archive}\n{len(manifest["files"])} files; {len(manifest["skipped"])} skipped paths.')
        return
    if action == 'borg':
        borg(ui)
        return

    archives = sorted((STATE / 'backups').glob('*.zip'), reverse=True)
    choice = ui.menu('Saved snapshots', [(str(i), archive.name) for i, archive in enumerate(archives)]) if archives else None
    if choice is None:
        if not archives:
            ui.message('Configuration backups', 'No saved snapshots.')
        return
    archive = archives[int(choice)]
    manifest = verify_backup(archive)
    if action == 'verify':
        ui.message('Snapshot verified', f'{len(manifest["files"])} regular files\nSource: {manifest["source"]}\nCreated: {manifest["created"]}')
    else:
        file = ui.menu('Choose a file to restore into /etc', [(str(i), record['path']) for i, record in enumerate(manifest['files'])])
        if file is not None:
            relative = manifest['files'][int(file)]['path']
            if manifest['source'] != '/etc':
                raise ValueError('Only /etc snapshots can be restored through this menu.')
            if ui.confirm('Restore configuration file', f'Overwrite /etc/{relative} from {archive.name}.\nCurrent content is saved for undo. Services are not restarted automatically.'):
                restore_backup(archive, Path('/etc'), selected={relative})
                ui.message('Configuration restored', '/etc/' + relative + '\nReview and reload the affected service when ready.')


def borg(ui):
    import shutil
    import subprocess
    import shlex
    operation = ui.menu('Borg 1.x', [('init', 'Initialize encrypted repository'), ('create', 'Back up a directory'),
                                   ('list', 'List archives'), ('check', 'Verify repository data'),
                                   ('extract', 'Restore archive into an empty staging directory')])
    if not operation:
        return
    repository = ui.input('Borg repository', 'Absolute path to a local Borg repository:')
    if not repository:
        return
    if not Path(repository).is_absolute() or '::' in repository:
        raise ValueError('Enter an absolute repository path.')
    # Borg prompts securely on the terminal; do not collect passphrases in the UI.
    if not shutil.which('borg'):
        raise RuntimeError('Install Borg 1.x first.')
    if not run(('borg', '--version')).startswith('borg 1.'):
        raise RuntimeError('This workflow currently supports Borg 1.x.')
    cwd = None
    if operation == 'init':
        command = ['borg', 'init', '--encryption=repokey', repository]
    elif operation == 'create':
        source = ui.input('Backup source', 'Existing absolute source directory:', '/etc')
        if not source:
            return
        source_path, repo_path = Path(source).resolve(), Path(repository).resolve()
        if not Path(source).is_absolute() or not source_path.is_dir() or source_path == repo_path or source_path in repo_path.parents:
            raise ValueError('Use an existing absolute source directory with the repository outside it.')
        archive = 'linux-tui-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        command = ['borg', 'create', '--stats', '--compression', 'lz4', repository + '::' + archive, str(source_path)]
    elif operation == 'extract':
        archive = ui.input('Archive name', 'Exact archive name from Borg list:')
        if not archive:
            return
        from .workflows import name
        name(archive)
        destination = ui.input('Restore staging directory', 'Existing empty absolute directory:')
        if not destination:
            return
        cwd = Path(destination)
        if not cwd.is_absolute() or not cwd.is_dir() or cwd.is_symlink() or any(cwd.iterdir()):
            raise ValueError('Restore requires an existing empty absolute directory.')
        command = ['borg', 'extract', repository + '::' + archive]
    else:
        command = ['borg', operation, *(['--verify-data'] if operation == 'check' else []), repository]
    if ui.confirm('Review Borg operation', shlex.join(command) + (f'\nRestore directory: {cwd}' if cwd else '') + '\nBorg will prompt for its passphrase on the terminal. Keep the repository key and passphrase separately.'):
        print('\033[2J\033[H', end='', flush=True)
        result = subprocess.run(command, cwd=cwd)
        # Preserve command output until the administrator acknowledges it.
        input('\nPress Enter to return to Linux TUI...')
        ui.message('Borg operation complete', f'Exit code: {result.returncode}\n0 = success; 1 = warnings; 2 or greater = failure.')


def schedule(ui):
    import sys
    if not Path('/run/systemd/system').exists():
        raise RuntimeError('Scheduled snapshots currently require systemd.')
    if not ui.confirm('Enable daily configuration backups', 'Create a systemd timer to snapshot /etc daily. Keep the newest 7 verified Linux TUI snapshots. Symlinks and special files are skipped. Snapshots contain secrets and remain root-only.'):
        return
    def quote(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'
    service = '[Unit]\nDescription=Linux TUI configuration snapshot\n[Service]\nType=oneshot\nUMask=0077\nWorkingDirectory=' + quote(Path(__file__).resolve().parent.parent) + '\nExecStart=' + quote(sys.executable) + ' -m linux_tui.backups --create --keep 7\n'
    timer = '[Unit]\nDescription=Daily Linux TUI configuration snapshot\n[Timer]\nOnCalendar=daily\nPersistent=true\nRandomizedDelaySec=15m\n[Install]\nWantedBy=timers.target\n'
    records = []
    try:
        records.append(change_file('/etc/systemd/system/linux-tui-backup.service', service.encode()))
        records.append(change_file('/etc/systemd/system/linux-tui-backup.timer', timer.encode()))
        run(('systemctl', 'daemon-reload'))
        run(('systemctl', 'enable', '--now', 'linux-tui-backup.timer'))
    except Exception:
        for transaction in reversed(records):
            restore_file(transaction, reload=False)
        run(('systemctl', 'daemon-reload'))
        raise
    ui.message('Daily snapshots enabled', 'systemctl status linux-tui-backup.timer\nConfiguration backups: /var/lib/linux-tui/backups\nUse Disable daily snapshot timer before uninstalling Linux TUI.')


def prune_backups(destination, keep):
    """Only remove verified snapshots produced by this application."""
    if not 1 <= keep <= 1000:
        raise ValueError('Retention must be 1â€“1000 snapshots.')
    import re
    archives = sorted((p for p in Path(destination).glob('linux-tui-*.zip')
                       if not p.is_symlink() and re.fullmatch(r'linux-tui-\d{8}T\d{6}Z-[a-f0-9]{8}\.zip', p.name)),
                      key=lambda p: p.stat().st_mtime_ns, reverse=True)
    for archive in archives[keep:]:
        verify_backup(archive)
        archive.unlink()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Linux TUI configuration snapshots')
    parser.add_argument('--create', action='store_true', required=True)
    parser.add_argument('--source', type=Path, default=Path('/etc'))
    parser.add_argument('--destination', type=Path, default=STATE / 'backups')
    parser.add_argument('--keep', type=int, default=7)
    args = parser.parse_args()
    if not 1 <= args.keep <= 1000:
        parser.error('--keep must be 1â€“1000')
    archive = create_backup(args.source, args.destination)
    manifest = verify_backup(archive)
    prune_backups(args.destination, args.keep)
    print(json.dumps({'archive': str(archive), 'files': len(manifest['files']), 'skipped': len(manifest['skipped']), 'verified': True}))


if __name__ == '__main__':
    main()
