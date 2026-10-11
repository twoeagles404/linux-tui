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


def menu_test():
    import pty
    master, slave = pty.openpty()
    process = subprocess.Popen([sys.executable, '-m', 'linux_tui'], stdin=slave,
                               stdout=slave, stderr=slave)
    os.close(slave)
    transcript = bytearray()
    sent = False
    deadline = time.monotonic() + 20
    try:
        while time.monotonic() < deadline:
            if select.select([master], [], [], .2)[0]:
                try:
                    data = os.read(master, 8192)
                except OSError:
                    break
                if not data:
                    break
                transcript.extend(data)
                if not sent and b'Choose a diagnostic' in transcript:
                    os.write(master, b'd\n1\nq\n')
                    sent = True
            if process.poll() is not None:
                break
        process.wait(timeout=2)
        text = transcript.decode(errors='replace')
        return process.returncode == 0 and all(value in text for value in
            ('read-only foundation', '"platform": "Linux"', '"action": "system"', '"ok": true'))
    except subprocess.TimeoutExpired:
        return False
    finally:
        if process.poll() is None:
            process.kill()
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
    menu_ok = menu_test()
    required_ok = all(item['status'] == 'passed' for item in outcomes if item['action'] in REQUIRED)
    report = {'python': platform.python_version(), 'platform': platform.system(),
              'diagnostics': outcomes, 'interactive_menu': 'passed' if menu_ok else 'failed',
              'required_diagnostics_passed': required_ok}
    print(json.dumps(report, indent=2))
    operational_ok = not any(item['status'] == 'failed' for item in outcomes)
    return 0 if required_ok and operational_ok and menu_ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
