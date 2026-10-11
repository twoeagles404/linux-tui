import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from tools.install import install


class InstallTests(unittest.TestCase):
    @patch('tools.install.platform.system', return_value='Linux')
    def test_install_runs_independently_of_checkout(self, _):
        with tempfile.TemporaryDirectory(prefix='linux tui ') as folder:
            launcher = install(Path(folder))
            environment = {**os.environ, 'PYTHONPATH': str(Path(folder) / 'share' / 'linux-tui')}
            result = subprocess.run([sys.executable, '-m', 'linux_tui', '--version'],
                                    cwd=folder, env=environment, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), '0.2.0')
            self.assertTrue(launcher.is_file())

    @patch('tools.install.platform.system', return_value='Linux')
    def test_unrelated_command_is_preserved(self, _):
        with tempfile.TemporaryDirectory() as folder:
            launcher = Path(folder) / 'bin' / 'linux-tui'
            launcher.parent.mkdir()
            launcher.write_text('unrelated program', encoding='utf-8')
            with self.assertRaises(RuntimeError):
                install(Path(folder))
            self.assertEqual(launcher.read_text(encoding='utf-8'), 'unrelated program')


if __name__ == '__main__':
    unittest.main()
