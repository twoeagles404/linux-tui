import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from linux_tui.notifications import deliver, health_events, send_event


class NotificationTests(unittest.TestCase):
    def test_gotify_token_uses_header_not_url(self):
        with patch('linux_tui.notifications.post') as post:
            deliver('gotify', {'url': 'https://notify.example', 'token': 'dummy-secret'}, 'title', 'body')
            self.assertEqual(post.call_args.args[0], 'https://notify.example/message')
            self.assertEqual(post.call_args.args[2], {'X-Gotify-Key': 'dummy-secret'})

    def test_dedup_and_severity_filter_never_send_extra_messages(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / 'notifications.json').write_text(json.dumps({'channels': {'gotify': {}}, 'severities': ['critical']}))
            with patch('linux_tui.notifications.deliver') as deliver_mock:
                event = {'title': 'Disk full', 'message': '90%', 'severity': 'warning'}
                self.assertFalse(send_event(path, event))
                deliver_mock.assert_not_called()
                event['severity'] = 'critical'
                self.assertTrue(send_event(path, event))
                self.assertFalse(send_event(path, event))
                deliver_mock.assert_called_once()

    def test_failed_channel_is_retried_when_other_channel_succeeded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / 'notifications.json').write_text(json.dumps({'channels': {'gotify': {}, 'discord': {}}}))
            def delivery(channel, *_):
                if channel == 'discord':
                    raise RuntimeError('Unavailable')
            with patch('linux_tui.notifications.deliver', side_effect=delivery) as deliver_mock:
                event = {'title': 'Disk full', 'message': '90%'}
                send_event(path, event)
                send_event(path, event)
                self.assertEqual([call.args[0] for call in deliver_mock.call_args_list], ['gotify', 'discord', 'discord'])

    def test_unknown_metrics_do_not_generate_false_alerts(self):
        self.assertEqual(health_events({'cpu_percent': None}), [])
        self.assertEqual(len(health_events({'cpu_percent': 95, 'root_filesystem': {'total': 100, 'used': 95},
                                           'cgroup_memory_limit': 100, 'cgroup_memory_current': 95})), 3)

    def test_apprise_missing_config_never_launches_command(self):
        with patch('subprocess.run') as run:
            with self.assertRaises(ValueError):
                deliver('apprise', {'config': 'relative-config'}, 'title', 'body')
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
