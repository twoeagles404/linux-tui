import json
import subprocess
import sys
import unittest


class CliTests(unittest.TestCase):
    def invoke(self, *args):
        return subprocess.run([sys.executable, '-m', 'linux_tui', *args],
                              input='', capture_output=True, text=True, timeout=10)

    def test_discovery_json(self):
        result = self.invoke('--discover')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('platform', json.loads(result.stdout))

    def test_catalog_ids_are_unique(self):
        result = self.invoke('--catalog')
        self.assertEqual(result.returncode, 0, result.stderr)
        catalog = json.loads(result.stdout)
        ids = [item['id'] for item in catalog]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all('unavailable_reason' in item for item in catalog))

    def test_invalid_action_exits_with_error(self):
        result = self.invoke('--run', 'system; reboot')
        self.assertEqual(result.returncode, 2)
        self.assertIn('invalid choice', result.stderr)

    def test_redirected_input_prints_help(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0)
        self.assertIn('usage:', result.stdout)


if __name__ == '__main__':
    unittest.main()
