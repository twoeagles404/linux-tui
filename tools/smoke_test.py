"""Exercise every diagnostic and the real interactive menu on a Linux host.

Reports contain status metadata only, never diagnostic output or system logs.
"""
import json
import os
from pathlib import Path
import platform
import select
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from linux_tui.core import ACTIONS, run_action, unavailable

REQUIRED = {'system', 'memory', 'processes', 'disks', 'filesystems', 'mounts',
            'addresses', 'routes', 'listeners'}


def menu_test(backend='auto'):
    import pty
    import fcntl
    import struct
    import termios
    import signal
    def controlling_terminal():
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 100, 0, 0))
    process = subprocess.Popen([sys.executable, '-m', 'linux_tui', '--ui', backend], stdin=slave,
                               stdout=slave, stderr=slave, env={**os.environ, 'TERM': 'xterm'},
                               preexec_fn=controlling_terminal)
    os.close(slave)
    transcript = bytearray()
    pending = bytearray()
    phase = 0
    steps = [(b'Main Linux TUI', b'h\r'),
             (b'Environment and capabilities', b'\r'),
             (b'platform: Linux', b'\x1b'),
             (b'Feature coverage and Proxmox exclusions', b'\x1b'),
             (b'Main Linux TUI', b'\x1b')]
    deadline = time.monotonic() + 20
    try:
        while time.monotonic() < deadline:
            ready = select.select([master], [], [], .2)[0]
            if ready:
                try:
                    data = os.read(master, 8192)
                except OSError:
                    break
                if not data:
                    break
                transcript.extend(data)
                pending.extend(data)
            # Wait until drawing completes before typing: newt can flush
            # early keystrokes while it initializes a newly opened form.
            if not ready and phase < len(steps) and steps[phase][0] in pending:
                os.write(master, steps[phase][1])
                phase += 1
                pending.clear()
            if process.poll() is not None:
                break
        process.wait(timeout=2)
        text = transcript.decode(errors='replace')
        return process.returncode == 0 and phase == len(steps) and 'Main Linux TUI' in text
    except subprocess.TimeoutExpired:
        return False
    finally:
        if os.environ.get('LINUX_TUI_SMOKE_TRANSCRIPT'):
            Path(os.environ['LINUX_TUI_SMOKE_TRANSCRIPT'] + '-' + backend).write_bytes(transcript)
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        os.close(master)


def main():
    if platform.system() != 'Linux':
        print('Live smoke tests require Linux.', file=sys.stderr)
        return 2
    outcomes = []
    for action in ACTIONS:
        reason = unavailable(action)
        if reason:
            outcomes.append({'action': action.id, 'status': 'unavailable', 'reason': reason})
            continue
        result = run_action(action.id)
        outcomes.append({'action': action.id, 'status': 'passed' if result['ok'] else 'failed',
                         'exit_code': result.get('exit_code'),
                         'output_present': bool(result.get('stdout'))})
    menu_results = {backend: menu_test(backend) for backend in ('auto', 'curses')}
    menu_ok = all(menu_results.values())
    required_ok = all(item['status'] == 'passed' for item in outcomes if item['action'] in REQUIRED)
    report = {'python': platform.python_version(), 'platform': platform.system(),
              'diagnostics': outcomes, 'interactive_menu': 'passed' if menu_ok else 'failed',
              'menu_backends': menu_results,
              'required_diagnostics_passed': required_ok}
    print(json.dumps(report, indent=2))
    operational_ok = not any(item['status'] == 'failed' for item in outcomes)
    return 0 if required_ok and operational_ok and menu_ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
