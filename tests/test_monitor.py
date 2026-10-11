import base64
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from linux_tui.monitor import Collector, History, cgroup_directory, make_handler, token_file


class MonitorTests(unittest.TestCase):
    def test_metrics_api_requires_auth_and_returns_persisted_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            history = History(Path(folder) / 'history.sqlite3')
            history.append({'time': 1, 'cpu_percent': 12})
            token = 'test-token-for-http-authentication-only'
            server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(history, token))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = 'http://127.0.0.1:' + str(server.server_port)
            try:
                with self.assertRaises(HTTPError) as error:
                    urlopen(url + '/api/metrics', timeout=3)
                self.assertEqual(error.exception.code, 401)
                error.exception.close()
                request = Request(url + '/api/metrics', headers={'Authorization': 'Bearer ' + token})
                with urlopen(request, timeout=3) as response:
                    self.assertEqual(json.load(response)['cpu_percent'], 12)
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')
                basic = base64.b64encode(('linux-tui:' + token).encode()).decode()
                for route, marker in (('/', b'Linux TUI Monitor'), ('/app.js', b'setInterval'), ('/style.css', b'grid'), ('/api/history', b'cpu_percent')):
                    with urlopen(Request(url + route, headers={'Authorization': 'Basic ' + basic}), timeout=3) as response:
                        self.assertIn(marker, response.read())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_token_is_stable_and_not_replaced_on_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'token'
            token = token_file(path)
            # Windows does not model POSIX private file modes.
            if os.name != 'nt':
                self.assertEqual(token_file(path), token)
            else:
                self.assertEqual(path.read_text().strip(), token)
            self.assertGreaterEqual(len(token), 32)

    def test_nested_cgroup_memory_and_cpu_usage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            proc, sysfs = root / 'proc', root / 'cgroup'
            (proc / 'self').mkdir(parents=True)
            (proc / 'net').mkdir()
            (sysfs / 'slice/service').mkdir(parents=True)
            group = sysfs / 'slice/service'
            (proc / 'self/cgroup').write_text('0::/slice/service\n')
            (proc / 'self/mountinfo').write_text('1 0 0:1 / /sys/fs/cgroup rw - cgroup2 cgroup rw\n')
            (proc / 'stat').write_text('cpu 100 0 0 100 0 0 0 0\n')
            (proc / 'meminfo').write_text('MemTotal: 1000 kB\nMemAvailable: 400 kB\n')
            (proc / 'uptime').write_text('120 100\n')
            (proc / 'net/dev').write_text('header\nheader\neth0: 100 0 0 0 0 0 0 0 200 0 0 0 0 0 0 0\n')
            (group / 'memory.max').write_text('102400')
            (group / 'memory.current').write_text('51200')
            (group / 'cpu.max').write_text('50000 100000')
            (group / 'cpu.stat').write_text('usage_usec 1000000\n')
            self.assertEqual(cgroup_directory(proc, sysfs), group)
            collector = Collector(proc, sysfs)
            with patch('linux_tui.monitor.os.getloadavg', return_value=(1, 2, 3), create=True), patch('linux_tui.monitor.time.time', side_effect=[1, 2]):
                first = collector.sample()
                (proc / 'stat').write_text('cpu 150 0 0 150 0 0 0 0\n')
                (group / 'cpu.stat').write_text('usage_usec 1250000\n')
                second = collector.sample()
            self.assertEqual(first['cgroup_memory_limit'], 102400)
            self.assertEqual(first['cgroup_cpu_quota'], 0.5)
            self.assertIsNone(first['cpu_percent'])
            self.assertEqual(second['cpu_percent'], 50)
            self.assertEqual(second['cgroup_cpu_percent'], 25)


if __name__ == '__main__':
    unittest.main()
