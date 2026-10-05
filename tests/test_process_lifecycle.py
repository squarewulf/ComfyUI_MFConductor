import io
import os
import shlex
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from node_scanner import NodeScanner
from profile_launch import build_profile_args, parse_launch_flags, write_profile_launcher
from standalone_server import MFConductorAPI
from workflow_analyzer import apply_enabled_folders


class LaunchArgumentsTests(unittest.TestCase):
    def test_combined_profile_options_are_validated(self):
        for profile in (
            {'flags': {'memory': '--lowvram'}, 'custom_flags': '--cpu'},
            {'port': 'not-a-port'},
        ):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                build_profile_args(profile)

    @unittest.skipUnless(os.name == 'nt', 'Windows paths')
    def test_windows_paths_round_trip(self):
        cases = [
            ('--output-directory C:\\Images', ['--output-directory', 'C:\\Images']),
            ('--output-directory "C:\\My Images\\"', ['--output-directory', 'C:\\My Images\\']),
            ('--output-directory "\\\\server\\share"', ['--output-directory', '\\\\server\\share']),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(parse_launch_flags(text), expected)
                self.assertEqual(parse_launch_flags(shlex.join(expected)), expected)


class ProcessLifecycleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='mfconductor-process-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'custom_nodes').mkdir()
        (self.root / 'main.py').write_text('')
        self.api = MFConductorAPI(str(self.root / 'custom_nodes'))
        self.api.add_backend_log = Mock()
        self.api.get_comfy_status = Mock(return_value={'status': 'stopped'})
        self.api.apply_profile = Mock(return_value={'success': True, 'results': {}})
        self.api.apply_enabled_folders = Mock(return_value={'success': True, 'results': {}})
        self.api._read_comfy_output = Mock()
        self.api._watch_comfy_startup = Mock()
        self.user_patch = patch('standalone_server.get_user_data')
        self.user = self.user_patch.start().return_value
        self.addCleanup(self.user_patch.stop)
        self.user.get_profile.return_value = {'flags': {}}
        self.persist_patch = patch('standalone_server.persist_blocked_packages')
        self.persist = self.persist_patch.start()
        self.addCleanup(self.persist_patch.stop)

    def test_invalid_profile_does_not_stop_or_apply(self):
        self.api.stop_comfy = Mock()
        self.api.get_comfy_status.return_value = {'status': 'running', 'managed': True}
        for profile in (None, {'custom_flags': '--port bad'},
                        {'flags': {'memory': '--lowvram'}, 'custom_flags': '--cpu'}):
            self.user.get_profile.return_value = profile
            result = self.api.launch_comfy('example', restart_if_running=True)
            self.assertFalse(result['success'])
        self.api.stop_comfy.assert_not_called()
        self.api.apply_profile.assert_not_called()
        self.persist.assert_not_called()

    def test_restart_validates_before_stopping(self):
        self.api.active_profile_name = 'example'
        self.user.get_profile.return_value = {'custom_flags': '--port bad'}
        self.api.stop_comfy = Mock()
        self.assertFalse(self.api.restart_comfy()['success'])
        self.api.stop_comfy.assert_not_called()

    def test_launch_uses_selected_comfy_root_and_resets_overrides(self):
        self.api.last_enabled_override = ['OldWorkflow']
        process = Mock(pid=123)
        with patch('standalone_server.subprocess.Popen', return_value=process) as spawn:
            result = self.api.launch_comfy(flags_override=['--port', '8195'])
        self.assertTrue(result['success'])
        self.assertEqual(spawn.call_args.args[0][2], str(self.root / 'main.py'))
        self.assertEqual(spawn.call_args.kwargs['cwd'], str(self.root))
        self.assertEqual(self.api.comfy_port, 8195)
        self.assertIsNone(self.api.last_enabled_override)

    def test_profile_launch_uses_whitelist_instead_of_renames(self):
        self.user.get_profile.return_value = {'flags': {}}
        self.api.apply_enabled_folders.return_value = {
            'success': True,
            'results': {'enabled': [], 'kept': [], 'disabled': [], 'errors': []},
        }
        process = Mock(pid=123)
        with patch('standalone_server.subprocess.Popen', return_value=process) as spawn:
            result = self.api.launch_comfy('example')
        self.assertTrue(result['success'], result)
        self.api.apply_profile.assert_not_called()
        self.assertFalse(self.api.apply_enabled_folders.call_args.kwargs['disable_others'])
        self.assertIn('--disable-all-custom-nodes', spawn.call_args.args[0])

    def test_workflow_isolation_uses_whitelist_instead_of_renames(self):
        self.api.apply_enabled_folders.return_value = {
            'success': True,
            'results': {'enabled': [], 'kept': ['Example'], 'disabled': [], 'errors': []},
        }
        process = Mock(pid=123)
        with patch('standalone_server.subprocess.Popen', return_value=process) as spawn:
            result = self.api.launch_comfy(enabled_override=['Example', 'ComfyUI-Manager'])
        self.assertTrue(result['success'], result)
        command = spawn.call_args.args[0]
        self.assertEqual(command[command.index('--whitelist-custom-nodes') + 1:], ['Example', 'ComfyUI-Manager'])
        self.assertIn('--disable-all-custom-nodes', command)
        self.assertFalse(self.api.apply_enabled_folders.call_args.kwargs['disable_others'])

    def test_isolation_error_prevents_spawn(self):
        self.api.apply_enabled_folders.return_value = {'success': False, 'message': 'Folder collision'}
        with patch('standalone_server.subprocess.Popen') as spawn:
            self.assertFalse(self.api.launch_comfy(enabled_override=['Example'])['success'])
        spawn.assert_not_called()

    def test_failed_stop_keeps_process_available_for_retry(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = OSError('Access denied')
        self.api.comfy_process = process
        self.assertFalse(self.api.stop_comfy()['success'])
        self.assertIs(self.api.comfy_process, process)

    def test_old_output_reader_cannot_consume_new_process_output(self):
        new_process = Mock(stdout=io.BytesIO(b'new process output\n'))
        old_process = Mock(stdout=io.BytesIO(b'old process output\n'))
        self.api.comfy_process = new_process
        MFConductorAPI._read_comfy_output(self.api, old_process)
        self.assertEqual(new_process.stdout.tell(), 0)
        self.assertFalse(new_process.stdout.closed)
        self.assertTrue(old_process.stdout.closed)
        self.assertEqual(self.api.comfy_output_buffer, [])

    def test_real_child_process_output_and_shutdown(self):
        (self.root / 'main.py').write_text(
            "import time\nprint('MFCONDUCTOR_TEST_READY', flush=True)\ntime.sleep(30)\n"
        )
        ready = threading.Event()
        reader_finished = threading.Event()
        decode = self.api._decode_line

        def decode_line(line):
            text = decode(line)
            if 'MFCONDUCTOR_TEST_READY' in text:
                ready.set()
            return text

        def read_output(process):
            try:
                MFConductorAPI._read_comfy_output(self.api, process)
            finally:
                reader_finished.set()

        self.api._decode_line = decode_line
        self.api._read_comfy_output = read_output
        result = self.api.launch_comfy()
        self.assertTrue(result['success'], result)
        process = self.api.comfy_process
        try:
            self.assertTrue(ready.wait(5), 'Child output was not captured')
            self.assertTrue(self.api.stop_comfy()['success'])
            self.assertTrue(reader_finished.wait(5), 'Output reader did not finish')
            self.assertIsNotNone(process.poll())
            self.assertTrue(process.stdout.closed)
            self.assertTrue(any(row['text'] == 'MFCONDUCTOR_TEST_READY' for row in self.api.comfy_output_buffer))
            self.assertFalse(any('Output reader error' in row['text'] for row in self.api.comfy_output_buffer))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    def test_overlapping_launch_requests_spawn_only_once(self):
        entered = threading.Event()
        release = threading.Event()
        process = Mock(pid=123)
        process.poll.return_value = None

        def spawn(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise TimeoutError('Test did not release spawn')
            return process

        def status():
            return {'status': 'running' if self.api.comfy_process else 'stopped'}

        self.api.get_comfy_status.side_effect = status
        with patch('standalone_server.subprocess.Popen', side_effect=spawn) as popen:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(self.api.launch_comfy)
                try:
                    self.assertTrue(entered.wait(5))
                    second = pool.submit(self.api.launch_comfy)
                finally:
                    release.set()
                self.assertTrue(first.result(timeout=5)['success'])
                self.assertFalse(second.result(timeout=5)['success'])
            popen.assert_called_once()


class LockedFolderTests(unittest.TestCase):
    def test_locked_disabled_folder_is_linked(self):
        temp = tempfile.TemporaryDirectory(prefix='mfconductor-link-')
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        disabled = root / 'Example.disabled'
        disabled.mkdir()
        (disabled / 'keep.txt').write_text('x', encoding='utf-8')
        scanner = NodeScanner(str(root))
        with patch('node_scanner._rename_node_folder', side_effect=PermissionError):
            ok, message = scanner.activate_node('Example')
        self.assertTrue(ok, message)
        self.assertEqual((root / 'Example' / 'keep.txt').read_text(encoding='utf-8'), 'x')
        ok, message = scanner.activate_node('Example')
        self.assertIn('already', message.lower())

    def test_generated_launcher_whitelists_instead_of_disabling(self):
        temp = tempfile.TemporaryDirectory(prefix='mfconductor-launcher-')
        self.addCleanup(temp.cleanup)
        conductor = Path(temp.name)
        script = write_profile_launcher(conductor, 'Example', {'enabled': ['Example']}, ['--port', '8188'])
        text = script.read_text(encoding='utf-8')
        self.assertIn('disable_others=False', text)
        self.assertIn('isolation_launch_flags', text)
        compile(text, str(script), 'exec')


class IsolationFailureTests(unittest.TestCase):
    def test_duplicate_activation_is_an_error(self):
        scanner = Mock()
        scanner.list_folder_names.return_value = ['Example']
        scanner.activate_node.return_value = (False, 'duplicate folders')
        result = apply_enabled_folders(scanner, ['Example'])
        self.assertEqual(result['errors'], ['Example: duplicate folders'])
        self.assertEqual(result['kept'], [])

    def test_workflow_isolation_does_not_rename_other_packs(self):
        scanner = Mock()
        scanner.list_folder_names.return_value = ['Example', 'ComfyUI-Memory-Cleaner']
        scanner.activate_node.return_value = (False, 'Node is already active: Example')
        result = apply_enabled_folders(scanner, ['Example'], disable_others=False)
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['disabled'], [])
        scanner.deactivate_node.assert_not_called()

    def test_profile_apply_reports_errors_without_changing_package_blocks(self):
        api = object.__new__(MFConductorAPI)
        api.scanner = Mock()
        api.scanner.list_folder_names.return_value = ['Example']
        with patch('standalone_server.get_user_data') as user, \
                patch('standalone_server.apply_enabled_folders', return_value={'errors': ['collision']}), \
                patch('standalone_server.persist_blocked_packages') as persist:
            user.return_value.get_profile.return_value = {'enabled': ['Example']}
            self.assertFalse(api.apply_profile('example')['success'])
            self.assertFalse(api.apply_enabled_folders(['Example'])['success'])
            persist.assert_not_called()


if __name__ == '__main__':
    unittest.main()
