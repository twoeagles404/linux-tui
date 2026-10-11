"""Read-only Linux discovery and explicitly allowlisted diagnostics."""
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess


@dataclass(frozen=True)
class Action:
    id: str
    category: str
    title: str
    argv: tuple[str, ...]


ACTIONS = (
    Action('system', 'System', 'Kernel and architecture', ('uname', '-a')),
    Action('memory', 'System', 'Memory usage (may include host totals in containers)', ('free', '-h')),
    Action('processes', 'System', 'Processes visible in this namespace', ('ps', '-eo', 'pid,ppid,user,%cpu,%mem,comm', '--sort=-%cpu')),
    Action('disks', 'Storage', 'Block device inventory', ('lsblk', '--json', '-o', 'NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS,RO')),
    Action('filesystems', 'Storage', 'Mounted filesystem usage', ('df', '-h')),
    Action('mounts', 'Storage', 'Mount inventory', ('findmnt', '--json')),
    Action('addresses', 'Network', 'Interface addresses', ('ip', '-json', 'address', 'show')),
    Action('routes', 'Network', 'Routing tables', ('ip', '-json', 'route', 'show', 'table', 'all')),
    Action('listeners', 'Network', 'Listening sockets', ('ss', '-lntu')),
    Action('services', 'Services', 'Failed system services', ('systemctl', '--failed', '--no-pager')),
    Action('logs', 'Services', 'Recent system warnings', ('journalctl', '-p', 'warning', '-n', '60', '--no-pager')),
    Action('pci', 'Hardware', 'Visible PCI devices', ('lspci', '-nn')),
    Action('usb', 'Hardware', 'Visible USB devices', ('lsusb',)),
    Action('sensors', 'Hardware', 'Available temperature sensors', ('sensors',)),
)


def read_text(path):
    try:
        return Path(path).read_text(encoding='utf-8').strip()
    except (OSError, UnicodeError):
        return ''


def os_release(text):
    values = {}
    for line in text.splitlines():
        if '=' not in line or line.startswith('#'):
            continue
        key, value = line.split('=', 1)
        try:
            parts = shlex.split(value, comments=True)
            values[key] = parts[0] if parts else ''
        except ValueError:
            continue
    return values


def discover():
    linux = platform.system() == 'Linux'
    release = os_release(read_text('/etc/os-release')) if linux else {}
    container = 'unknown'
    if linux:
        container = read_text('/run/systemd/container') or os.environ.get('container', '')
        if not container and Path('/.dockerenv').exists():
            container = 'docker'
        if not container:
            container = 'not detected (not proof of bare metal)'
    return {
        'platform': platform.system(), 'architecture': platform.machine(),
        'distribution': release.get('PRETTY_NAME', 'unknown'),
        'distribution_id': release.get('ID', 'unknown'),
        'kernel': platform.release(), 'container_hint': container,
        'effective_uid': os.geteuid() if hasattr(os, 'geteuid') else None,
        'init': read_text('/proc/1/comm') if linux else 'unavailable',
        'package_managers': [name for name in ('apt-get', 'dnf', 'apk', 'pacman', 'zypper') if linux and shutil.which(name)],
        'cgroup_v2_memory_max': read_text('/sys/fs/cgroup/memory.max') if linux else '',
        'cgroup_v2_cpu_max': read_text('/sys/fs/cgroup/cpu.max') if linux else '',
        'notes': ['Cgroup paths are hints; delegated/nested cgroups require further resolution.',
                  'Visible devices and installed commands do not prove permission to manage them.'],
    }


def unavailable(action):
    if platform.system() != 'Linux':
        return 'Linux required; this system supports catalog preview only'
    if not shutil.which(action.argv[0]):
        return f'Required executable is missing: {action.argv[0]}'
    if action.id == 'usb':
        try:
            if not any(Path('/sys/bus/usb/devices').iterdir()):
                return 'No USB devices are exposed in this environment'
        except OSError:
            return 'USB device inventory is not accessible in this environment'
    if action.argv[0] in ('systemctl', 'journalctl') and not Path('/run/systemd/system').is_dir():
        return 'Active systemd environment required'
    return None


def catalog():
    return [{**asdict(action), 'status': 'implemented-read-only', 'unavailable_reason': unavailable(action)} for action in ACTIONS]


def run_action(action_id):
    action = next((item for item in ACTIONS if item.id == action_id), None)
    if action is None:
        raise ValueError(f'Unknown action: {action_id}')
    reason = unavailable(action)
    if reason:
        return {'action': action.id, 'ok': False, 'error': reason}
    try:
        # Fixed argv only; no user command interpolation or shell execution.
        result = subprocess.run(action.argv, capture_output=True, text=True,
                                errors='replace', timeout=15, check=False,
                                env={**os.environ, 'LC_ALL': 'C', 'SYSTEMD_PAGER': 'cat'})
        return {'action': action.id, 'ok': result.returncode == 0,
                'exit_code': result.returncode, 'stdout': result.stdout[:65536],
                'stderr': result.stderr[:8192]}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {'action': action.id, 'ok': False, 'error': str(error)}
