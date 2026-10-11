"""Install the dependency-free Linux TUI and its launcher for the current user."""
import argparse
from pathlib import Path
import platform
import shlex
import shutil
import sys

MARKER = '# Linux TUI launcher'


def install(prefix):
    if sys.version_info < (3, 11):
        raise RuntimeError('Python 3.11 or newer is required.')
    if platform.system() != 'Linux':
        raise RuntimeError('Installation requires Linux.')
    prefix = Path(prefix).expanduser().resolve()
    destination = prefix / 'share' / 'linux-tui'
    launcher = prefix / 'bin' / 'linux-tui'
    if launcher.exists() and MARKER not in launcher.read_text(encoding='utf-8'):
        raise RuntimeError(f'Refusing to overwrite an unrelated launcher: {launcher}')
    source = Path(__file__).resolve().parents[1] / 'linux_tui'
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination / 'linux_tui', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(
        '#!/bin/sh\n' + MARKER + '\n'
        + f'cd {shlex.quote(str(destination))} || exit 1\n'
        + f'exec {shlex.quote(sys.executable)} -m linux_tui "$@"\n',
        encoding='utf-8', newline='\n')
    launcher.chmod(0o755)
    return launcher


def main():
    parser = argparse.ArgumentParser(description='Install Linux TUI for the current user; no sudo or pip required.')
    parser.add_argument('--prefix', type=Path, default=Path.home() / '.local')
    args = parser.parse_args()
    try:
        launcher = install(args.prefix)
    except (OSError, RuntimeError) as error:
        parser.exit(1, f'Installation failed: {error}\n')
    print(f'Installed: {launcher}')
    print(f'Start with: {shlex.quote(str(launcher))}')
    print(f'To enable the short command in this shell: export PATH={shlex.quote(str(launcher.parent))}:"$PATH"')


if __name__ == '__main__':
    main()
