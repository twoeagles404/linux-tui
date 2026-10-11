"""Live Linux workflow checks using only temporary files and a localhost listener."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from linux_tui.backups import create_backup, verify_backup, restore_backup
from linux_tui.workflows import change_file, restore_file


def main():
    if sys.platform != 'linux':
        raise SystemExit('Live workflow smoke checks require Linux.')
    report = {}
    with tempfile.TemporaryDirectory(prefix='linux-tui-smoke-') as folder:
        root = Path(folder)
        file = root / 'config'
        file.write_bytes(b'original')
        os.chmod(file, 0o640)
        transaction = change_file(file, b'changed', state=root / 'changes')
        assert file.read_bytes() == b'changed'
        restore_file(transaction)
        assert file.read_bytes() == b'original' and file.stat().st_mode & 0o777 == 0o640
        report['real_config_write_and_undo'] = 'passed'
        source = root / 'source'
        source.mkdir()
        (source / 'nested').mkdir()
        (source / 'nested/settings').write_bytes(b'saved configuration')
        (source / 'link').symlink_to(source / 'nested/settings')
        archive = create_backup(source, root / 'backups')
        manifest = verify_backup(archive)
        assert manifest['skipped'] == ['link'] and archive.stat().st_mode & 0o077 == 0
        target = root / 'restore'
        restore_backup(archive, target, state=root / 'changes')
        assert (target / 'nested/settings').read_bytes() == b'saved configuration'
        assert not (target / 'link').exists()
        report['real_backup_verify_restore_and_private_permissions'] = 'passed'
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        process = subprocess.Popen([sys.executable, '-m', 'linux_tui', '--monitor', '--port', str(port),
                                    '--monitor-state', str(root / 'monitor')], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        url = f'http://127.0.0.1:{port}/api/metrics'
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    urlopen(url, timeout=1).close()
                    raise AssertionError('Unauthenticated resource request succeeded.')
                except HTTPError as error:
                    assert error.code == 401
                    error.close()
                    break
                except URLError:
                    if process.poll() is not None:
                        raise AssertionError('Monitor process stopped before accepting requests.')
                    time.sleep(.1)
            else:
                raise AssertionError('Monitor startup timed out.')
            token_path = root / 'monitor/monitor-token'
            assert token_path.stat().st_mode & 0o077 == 0
            token = token_path.read_text().strip()
            with urlopen(Request(url, headers={'Authorization': 'Bearer ' + token}), timeout=3) as response:
                metrics = json.load(response)
            assert metrics['host_memory_total'] > 0 and metrics['uptime_seconds'] > 0
            assert 'cgroup_memory_limit' in metrics and 'network' in metrics
            report['running_monitor_cli_auth_and_real_linux_metrics'] = 'passed'
        finally:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=3)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
