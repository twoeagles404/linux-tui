import unittest
from unittest.mock import Mock, patch
from linux_tui.admin import apply_package, package_plan
from linux_tui.core import ACTIONS
from linux_tui.menus import COMMANDS, GUIDES, MAIN, SECTIONS, launch
from linux_tui.workflows import WORKFLOWS


class MenuTests(unittest.TestCase):
    def test_category_items_have_handlers(self):
        handlers = set(COMMANDS) | set(GUIDES) | set(WORKFLOWS) | {a.id for a in ACTIONS} | {
            'refresh', 'upgrade', 'guest-agent', 'fail2ban-install', 'lynis-install',
            'tools', 'admin-tools', 'discovery', 'version', 'backend'}
        self.assertEqual(set(SECTIONS), {key for key, _ in MAIN if key != '0'})
        for entries in SECTIONS.values():
            self.assertTrue(all(key in handlers for key, _ in entries))

    @patch('linux_tui.menus.TerminalUI')
    def test_cancel_submenu_returns_to_main(self, ui_class):
        ui = ui_class.return_value
        ui.menu.side_effect = ['1', None, '0']
        self.assertEqual(launch(), 0)
        self.assertEqual(ui.menu.call_args_list[-1].args[0], 'Main Linux TUI')

    @patch('linux_tui.admin.shutil.which', side_effect=lambda name: '/usr/bin/apt-get' if name == 'apt-get' else None)
    def test_package_names_cannot_be_commands(self, _):
        with self.assertRaises(ValueError):
            package_plan('install', ('curl; reboot',))

    @patch('linux_tui.admin.shutil.which', side_effect=lambda name: '/usr/bin/apt-get' if name == 'apt-get' else None)
    def test_admin_tool_names_map_to_native_apt_packages(self, _):
        self.assertEqual(package_plan('install', ('borg', 'nfs-client', 'libvirt', 'virt-install')),
                         ['apt-get', 'install', 'borgbackup', 'nfs-common', 'libvirt-daemon-system', 'virtinst'])

    @patch('linux_tui.admin.shutil.which', return_value='/usr/bin/apt-get')
    @patch('linux_tui.admin.os.geteuid', return_value=0, create=True)
    @patch('linux_tui.admin.subprocess.run')
    def test_cancelled_package_plan_does_not_execute(self, run, *_):
        ui = Mock()
        ui.confirm.return_value = False
        apply_package(ui, 'upgrade')
        run.assert_not_called()
        self.assertIn('apt-get upgrade', ui.confirm.call_args.args[1])


if __name__ == '__main__':
    unittest.main()
