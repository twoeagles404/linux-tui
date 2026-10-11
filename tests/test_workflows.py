import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from linux_tui.backups import create_backup, verify_backup, restore_backup, prune_backups
from linux_tui.workflows import change_file, restore_file, execute, firewall, name, instances, network_edit, empty_disks, gpu_drivers, configuration_lock


class WorkflowTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix', 'Runtime configuration locks require Linux/POSIX')
    def test_concurrent_configuration_change_fails_without_overwriting(self):
        with tempfile.TemporaryDirectory() as folder:
            path, state = Path(folder) / 'config', Path(folder) / 'state'
            path.write_bytes(b'original')
            with configuration_lock(path, state):
                with self.assertRaises(RuntimeError):
                    change_file(path, b'conflicting', state=state)
                self.assertEqual(path.read_bytes(), b'original')
            transaction = change_file(path, b'changed', state=state)
            restore_file(transaction)
            self.assertEqual(path.read_bytes(), b'original')
    def test_container_cannot_install_host_gpu_drivers(self):
        with patch('linux_tui.workflows.require_root'), patch.dict('linux_tui.workflows.os.environ', {'container': 'lxc'}), patch('linux_tui.workflows.execute') as execute_mock:
            with self.assertRaises(RuntimeError):
                gpu_drivers(Mock())
            execute_mock.assert_not_called()
    def test_format_selection_excludes_partitioned_mounted_swap_readonly_and_signed_disks(self):
        disks = [{'path': '/dev/empty', 'type': 'disk'}, {'path': '/dev/root', 'type': 'disk', 'children': [{'mountpoints': ['/']}]},
                 {'path': '/dev/mounted', 'type': 'disk', 'mountpoints': ['/data']}, {'path': '/dev/signed', 'type': 'disk', 'fstype': 'ext4'},
                 {'path': '/dev/swap', 'type': 'disk'}, {'path': '/dev/readonly', 'type': 'disk', 'ro': True}]
        self.assertEqual([disk['path'] for disk in empty_disks({'blockdevices': disks}, ['/dev/swap'])], ['/dev/empty'])
    def test_failed_configuration_apply_restores_original(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config'
            path.write_bytes(b'original')
            with patch('linux_tui.workflows.run', side_effect=RuntimeError('reload failed')):
                with self.assertRaises(RuntimeError):
                    change_file(path, b'new', [('false',)], Path(folder) / 'state')
            self.assertEqual(path.read_bytes(), b'original')

    def test_new_file_undo_removes_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config'
            transaction = change_file(path, b'new', state=Path(folder) / 'state')
            restore_file(transaction)
            self.assertFalse(path.exists())
            self.assertEqual(json.loads((transaction / 'record.json').read_text())['status'], 'restored')

    def test_sysctl_undo_restores_saved_runtime_value(self):
        with tempfile.TemporaryDirectory() as folder:
            transaction = change_file(Path(folder) / 'sysctl.conf', b'vm.swappiness=10',
                                      state=Path(folder) / 'state', rollback_commands=[('sysctl', '-w', 'vm.swappiness=60')])
            with patch('linux_tui.workflows.run') as run:
                restore_file(transaction)
                run.assert_called_once_with(['sysctl', '-w', 'vm.swappiness=60'])

    def test_cancelled_workflow_has_no_command_side_effects(self):
        ui = Mock()
        ui.confirm.return_value = False
        with patch('linux_tui.workflows.require_root'), patch('linux_tui.workflows.shutil.which', return_value='/bin/tool'), patch('linux_tui.workflows.run') as run:
            execute(ui, 'Test', [('tool', 'start')])
            run.assert_not_called()

    def test_instance_name_rejects_option_and_shell_input(self):
        for value in ('--all', 'vm;reboot', 'vm\nreboot', 'vm name', '../vm'):
            with self.assertRaises(ValueError):
                name(value)

    def test_firewall_invalid_port_never_executes(self):
        ui = Mock()
        ui.menu.return_value = 'allow'
        ui.input.return_value = '99999/tcp'
        with patch('linux_tui.workflows.shutil.which', return_value='/bin/ufw'), patch('linux_tui.workflows.execute') as execute_mock:
            with self.assertRaises(ValueError):
                firewall(ui)
            execute_mock.assert_not_called()

    def test_backup_roundtrip_selective_restore_and_undo(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source'
            source.mkdir()
            (source / 'one').write_bytes(b'saved')
            (source / 'two').write_bytes(b'untouched')
            archive = create_backup(source, root / 'backups')
            self.assertEqual(len(verify_backup(archive)['files']), 2)
            target = root / 'target'
            target.mkdir()
            (target / 'one').write_bytes(b'current')
            transactions = restore_backup(archive, target, {'one'}, state=root / 'state')
            self.assertEqual((target / 'one').read_bytes(), b'saved')
            self.assertFalse((target / 'two').exists())
            restore_file(transactions[0])
            self.assertEqual((target / 'one').read_bytes(), b'current')

    def test_corrupt_backup_rejected_before_restore_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source'
            source.mkdir()
            (source / 'one').write_bytes(b'original')
            archive = create_backup(source, root / 'backups')
            with zipfile.ZipFile(archive) as zipped:
                manifest = json.loads(zipped.read('manifest.json'))
            with zipfile.ZipFile(archive, 'w') as zipped:
                zipped.writestr('manifest.json', json.dumps(manifest))
                zipped.writestr('files/one', b'tampered')
            with self.assertRaises(ValueError):
                restore_backup(archive, root / 'target', state=root / 'state')
            self.assertFalse((root / 'target').exists())

    def test_backup_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / 'bad.zip'
            with zipfile.ZipFile(archive, 'w') as zipped:
                zipped.writestr('manifest.json', json.dumps({'version': 1, 'files': [{'path': '../escape'}]}))
                zipped.writestr('files/../escape', b'data')
            with self.assertRaises(ValueError):
                verify_backup(archive)

    def test_backup_inside_source_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                create_backup(Path(folder), Path(folder) / 'backups')

    def test_retention_preserves_unrelated_zip_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source'
            source.mkdir()
            (source / 'one').write_bytes(b'config')
            destination = root / 'backups'
            create_backup(source, destination)
            create_backup(source, destination)
            unrelated = destination / 'unrelated.zip'
            unrelated.write_bytes(b'not ours')
            prune_backups(destination, 1)
            self.assertEqual(len(list(destination.glob('linux-tui-*.zip'))), 1)
            self.assertTrue(unrelated.exists())

    def test_invalid_network_address_never_changes_configuration(self):
        ui = Mock()
        ui.menu.return_value = 'eth0'
        ui.input.return_value = '192.168.1.1;reboot'
        with patch('linux_tui.workflows.require_root'), patch('linux_tui.workflows.shutil.which', return_value='/bin/nmcli'), patch('linux_tui.workflows.run', return_value='eth0:connected'), patch('linux_tui.workflows.subprocess.run') as run:
            with self.assertRaises(ValueError):
                network_edit(ui)
            run.assert_not_called()

    def test_incus_creation_uses_validated_image_and_instance_arguments(self):
        ui = Mock()
        ui.menu.side_effect = ['incus', 'create']
        ui.input.side_effect = ['test-vm', 'images:debian/13']
        with patch('linux_tui.workflows.shutil.which', return_value='/bin/tool'), patch('linux_tui.workflows.execute') as execute_mock:
            # Image aliases include slashes, unlike instance names.
            instances(ui)
            self.assertEqual(execute_mock.call_args.args[2], [('incus', 'launch', 'images:debian/13', 'test-vm')])

    def test_partial_restore_failure_rolls_back_prior_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target = root / 'source', root / 'target'
            source.mkdir()
            target.mkdir()
            for key in ('one', 'two'):
                (source / key).write_bytes(b'saved')
                (target / key).write_bytes(b'current')
            archive = create_backup(source, root / 'backups')
            calls = []
            def fail_second(*args, **kwargs):
                calls.append(args)
                if len(calls) == 2:
                    raise OSError('Disk full')
                return change_file(*args, **kwargs)
            with patch('linux_tui.backups.change_file', side_effect=fail_second):
                with self.assertRaises(OSError):
                    restore_backup(archive, target, state=root / 'state')
            self.assertTrue(all((target / key).read_bytes() == b'current' for key in ('one', 'two')))


if __name__ == '__main__':
    unittest.main()
