"""Opt-in Docker lifecycle acceptance test using one isolated disposable container."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from linux_tui.workflows import containers, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pull', action='store_true', help='Allow fetching the public BusyBox test image if absent')
    args = parser.parse_args()
    endpoint = os.environ.get('DOCKER_HOST') or run(('docker', 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}')).strip()
    if not endpoint.startswith('unix://'):
        raise SystemExit('This test requires a local Unix-socket Docker engine.')
    image = 'busybox:1.37'
    existed = subprocess.run(['docker', 'image', 'inspect', image], capture_output=True).returncode == 0
    if not existed:
        if not args.pull:
            raise SystemExit('BusyBox test image is absent. Use --pull to fetch it explicitly.')
        run(('docker', 'pull', image), timeout=120)
    instance = 'linux-tui-smoke-' + uuid.uuid4().hex[:12]
    identifier = None
    results = {}
    try:
        identifier = run(('docker', 'create', '--network', 'none', '--name', instance,
                          '--label', 'org.linux-tui.test=true', image, 'sleep', '300')).strip()
        for action in ('start', 'inspect', 'logs', 'restart', 'stop', 'remove'):
            ui = Mock()
            ui.menu.side_effect = ['docker', identifier[:12], action]
            ui.confirm.return_value = True
            containers(ui)
            if action in ('start', 'restart', 'stop'):
                running = run(('docker', 'inspect', '--format', '{{.State.Running}}', identifier)).strip()
                assert running == ('false' if action == 'stop' else 'true')
            elif action == 'remove':
                assert subprocess.run(['docker', 'inspect', identifier], capture_output=True).returncode != 0
            results[action] = 'passed'
    finally:
        if identifier:
            label = subprocess.run(['docker', 'inspect', '--format', '{{index .Config.Labels "org.linux-tui.test"}}', identifier], capture_output=True, text=True)
            if label.returncode == 0 and label.stdout.strip() == 'true':
                subprocess.run(['docker', 'rm', '-f', identifier], capture_output=True)
        if not existed:
            # No force: Docker protects layers now referenced by another container.
            removed = subprocess.run(['docker', 'image', 'rm', image], capture_output=True)
            results['temporary_image_cleanup'] = 'passed' if removed.returncode == 0 else 'retained (in use or cleanup failed)'
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
