import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from profile_launch import parse_launch_flags, build_profile_args
from workflow_analyzer import folders_for_workflow_launch
from standalone_server import MFConductorAPI

class WorkflowLaunchTests(unittest.TestCase):
    def test_quoted_paths_and_port(self):
        self.assertEqual(parse_launch_flags('--output-directory "C:\\My Images" --port 8190'), ['--output-directory', 'C:\\My Images', '--port', '8190'])
        for flags in ('--port', '--port abc', '--port=0', '--port=65536', 'python main.py', '--foo "broken'):
            with self.subTest(flags=flags), self.assertRaises(ValueError):
                parse_launch_flags(flags)

    def test_profile_flags_include_enabled_custom_options(self):
        self.assertEqual(build_profile_args({'flags': {'memory': '--lowvram'}, 'port': 8190, 'custom_flags_list': [{'value': '--cpu', 'enabled': False}, {'value': '--preview-method auto'}]}), ['--lowvram', '--port', '8190', '--preview-method', 'auto'])

    def test_workflow_keeps_utilities_and_explicit_extras(self):
        installed = ['Example', 'ComfyUI-Manager', 'ComfyUI-ModelFrisk', 'rgthree-comfy', 'HeavyUnused']
        result = folders_for_workflow_launch({'required_folders': ['Example']}, installed, ['rgthree-comfy'])
        self.assertEqual(set(result), set(installed) - {'HeavyUnused'})
        with self.assertRaises(ValueError):
            folders_for_workflow_launch({}, installed, ['not-installed'])

    def test_invalid_setup_does_not_stop_running_comfy(self):
        api = object.__new__(MFConductorAPI)
        api.stop_comfy = Mock()
        api._isolation_for_workflows = Mock(return_value=(None, {'success': False, 'message': 'Bad workflow'}))
        self.assertFalse(api.launch_workflow('bad.json', launch_flags='--port=invalid')['success'])
        self.assertFalse(api.launch_workflow('bad.json', launch_flags='')['success'])
        api.stop_comfy.assert_not_called()

    def test_launch_forwards_flags_and_only_persists_after_success(self):
        api = object.__new__(MFConductorAPI)
        api.output_lock = threading.Lock()
        api._isolation_for_workflows = Mock(return_value=({'enabled': ['Example'], 'names': ['Example'], 'paths': ['Example.json']}, None))
        api.get_comfy_status = Mock(return_value={'status': 'stopped'})
        api._append_comfy_log = Mock()
        api._warn_broken_native_packs = Mock()
        api.launch_comfy = Mock(return_value={'success': True, 'port': 8190})
        with patch('standalone_server.get_user_data') as user, patch('standalone_server.persist_pending_workflow') as pending:
            user.return_value.get_profiles.return_value = {}
            result = api.launch_workflow('Example.json', launch_flags='--port 8190', extra_nodes=['rgthree-comfy'])
            self.assertTrue(result['success'])
            self.assertEqual(api.launch_comfy.call_args.kwargs['flags_override'], ['--port', '8190'])
            self.assertEqual(api._isolation_for_workflows.call_args.args[2], ['rgthree-comfy'])
            pending.assert_called_once_with('Example.json', ['Example.json'])
            pending.reset_mock()
            api.launch_comfy.return_value = {'success': False}
            api.launch_workflow('Example.json', launch_flags='')
            pending.assert_not_called()

    def test_splash_has_no_tabs_and_batch_uses_same_asset(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / 'web/assets/splash.txt').read_text(encoding='utf-8')
        self.assertNotIn('\t', text)
        self.assertIn('web\\assets\\splash.txt', (root / 'Launch_MFConductor.bat').read_text())

if __name__ == '__main__':
    unittest.main()
