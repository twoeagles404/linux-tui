import subprocess
import unittest
from unittest.mock import patch
from linux_tui.core import ACTIONS, os_release, run_action, unavailable


class CoreTests(unittest.TestCase):
    def test_release_parser_does_not_execute_shell(self):
        result = os_release('ID=debian\nPRETTY_NAME="Debian GNU/Linux"\nBAD="unterminated\nX="$(whoami)"')
        self.assertEqual(result['PRETTY_NAME'], 'Debian GNU/Linux')
        self.assertEqual(result['X'], '$(whoami)')
        self.assertNotIn('BAD', result)

    def test_unknown_action_never_executes(self):
        with patch('linux_tui.core.subprocess.run') as run:
            with self.assertRaises(ValueError):
                run_action('system; reboot')
            run.assert_not_called()

    @patch('linux_tui.core.platform.system', return_value='Windows')
    def test_non_linux_never_executes(self, _):
        with patch('linux_tui.core.subprocess.run') as run:
            self.assertFalse(run_action('system')['ok'])
            run.assert_not_called()

    @patch('linux_tui.core.platform.system', return_value='Linux')
    @patch('linux_tui.core.shutil.which', return_value=None)
    def test_missing_executable_explained(self, *_):
        self.assertIn('missing', unavailable(ACTIONS[0]))

    @patch('linux_tui.core.unavailable', return_value=None)
    def test_fixed_argv_and_failure_propagation(self, _):
        with patch('linux_tui.core.subprocess.run', return_value=subprocess.CompletedProcess(['uname'], 1, '', 'denied')) as run:
            result = run_action('system')
            self.assertFalse(result['ok'])
            self.assertEqual(result['stderr'], 'denied')
            self.assertEqual(run.call_args.args[0], ('uname', '-a'))
            self.assertNotIn('shell', run.call_args.kwargs)
            self.assertEqual(run.call_args.kwargs['timeout'], 15)

    @patch('linux_tui.core.unavailable', return_value=None)
    def test_timeout_is_reported(self, _):
        with patch('linux_tui.core.subprocess.run', side_effect=subprocess.TimeoutExpired('uname', 15)):
            self.assertFalse(run_action('system')['ok'])


if __name__ == '__main__':
    unittest.main()
