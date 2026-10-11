"""Portable, previewed package operations. No upstream scripts are executed."""
import os
import shlex
import shutil
import subprocess

TOOLS = ('curl', 'wget', 'git', 'jq', 'htop', 'btop', 'tmux', 'rsync', 'nano', 'unzip')
ADMIN_TOOLS = ('smartmontools', 'borg', 'samba', 'nfs-client', 'nfs-server', 'podman', 'ufw', 'sensors', 'libvirt', 'virt-install', 'lxc')
PACKAGE_NAMES = {
    'borg': {'apt-get': 'borgbackup', 'dnf': 'borgbackup', 'apk': 'borgbackup', 'pacman': 'borg', 'zypper': 'borgbackup'},
    'nfs-client': {'apt-get': 'nfs-common', 'dnf': 'nfs-utils', 'apk': 'nfs-utils', 'pacman': 'nfs-utils', 'zypper': 'nfs-client'},
    'nfs-server': {'apt-get': 'nfs-kernel-server', 'dnf': 'nfs-utils', 'apk': 'nfs-utils', 'pacman': 'nfs-utils', 'zypper': 'nfs-kernel-server'},
    'sensors': {'apt-get': 'lm-sensors', 'dnf': 'lm_sensors', 'apk': 'lm-sensors', 'pacman': 'lm_sensors', 'zypper': 'sensors'},
    'libvirt': {'apt-get': 'libvirt-daemon-system', 'dnf': 'libvirt', 'apk': 'libvirt', 'pacman': 'libvirt', 'zypper': 'libvirt'},
    'virt-install': {'apt-get': 'virtinst', 'dnf': 'virt-install', 'pacman': 'virt-install', 'zypper': 'virt-install'},
}


def package_plan(operation, packages=()):
    if operation not in ('refresh', 'upgrade', 'install'):
        raise ValueError('Unknown package operation')
    if operation == 'install' and (not packages or any(p not in (*TOOLS, *ADMIN_TOOLS, 'fail2ban', 'lynis', 'qemu-guest-agent') for p in packages)):
        raise ValueError('Package is not in the reviewed catalog')
    manager = next((name for name in ('apt-get', 'dnf', 'apk', 'pacman', 'zypper') if shutil.which(name)), None)
    if manager is None:
        raise RuntimeError('No supported package manager found.')
    resolved = []
    for package in packages:
        if package in PACKAGE_NAMES:
            if manager not in PACKAGE_NAMES[package]:
                raise RuntimeError(f'No reviewed package mapping for {package} on {manager}; install this tool using your distribution documentation.')
            resolved.append(PACKAGE_NAMES[package][manager])
        else:
            resolved.append(package)
    packages = tuple(resolved)
    plans = {
        'apt-get': {'refresh': ['update'], 'upgrade': ['upgrade'], 'install': ['install', *packages]},
        'dnf': {'refresh': ['makecache'], 'upgrade': ['upgrade'], 'install': ['install', *packages]},
        'apk': {'refresh': ['update'], 'upgrade': ['upgrade'], 'install': ['add', *packages]},
        'pacman': {'refresh': ['-Syu'], 'upgrade': ['-Syu'], 'install': ['-Syu', *packages]},
        'zypper': {'refresh': ['refresh'], 'upgrade': ['update'], 'install': ['install', *packages]},
    }
    return [manager, *plans[manager][operation]]


def apply_package(ui, operation, packages=()):
    try:
        command = package_plan(operation, packages)
    except (ValueError, RuntimeError) as error:
        ui.message('Package operation unavailable', str(error))
        return
    if os.geteuid() != 0:
        ui.message('Administrator access required', 'Run linux-tui as root to change system packages. No change was made.')
        return
    detail = 'Command:\n' + shlex.join(command) + '\n\nThis changes system packages. Package upgrades cannot be automatically rolled back.'
    if command[0] == 'pacman':
        detail += '\nArch packages must be updated together; this performs a full synchronized upgrade.'
    if not ui.confirm('Review package changes', detail):
        return
    print('\033[2J\033[H', end='', flush=True)
    try:
        result = subprocess.run(command, check=False)
        ui.message('Package operation complete', f'Command: {shlex.join(command)}\nExit code: {result.returncode}')
    except OSError as error:
        ui.message('Package operation failed', str(error))
