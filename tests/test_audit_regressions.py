import ast
import asyncio
import http.client
import json
import os
import runpy
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiohttp import web
from node_scanner import NodeScanner
from profile_launch import write_profile_launcher
from security_utils import is_local_api_request, is_local_request
from standalone_server import MFConductorHandler
from workflow_analyzer import apply_enabled_folders, folders_for_profile


class RequestSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(MFConductorHandler):
            web_dir = ROOT / 'web'

            def log_message(self, *args):
                pass

        cls.handler = Handler
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)

    def setUp(self):
        self.api = Mock()
        self.api.delete_profile.return_value = {'success': True}
        self.api.clear_default_profile.return_value = {'success': True}
        self.handler.api = self.api
        self.host = f'127.0.0.1:{self.server.server_port}'

    def request(self, method='POST', path='/api/profiles/delete', headers=None, body='{"name":"test"}'):
        request_headers = {'Host': self.host, 'Content-Type': 'application/json'}
        request_headers.update(headers or {})
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            conn.request(method, path, body, request_headers)
            response = conn.getresponse()
            if response.status != 101:
                response.read()
            return response.status
        finally:
            conn.close()

    def test_same_origin_and_native_json_clients_work(self):
        self.assertEqual(self.request(headers={'Origin': f'http://{self.host}', 'Sec-Fetch-Site': 'same-origin'}), 200)
        self.assertEqual(self.request(), 200)
        self.assertEqual(self.api.delete_profile.call_count, 2)

    def test_foreign_origins_and_hosts_cannot_mutate(self):
        for headers in (
            {'Origin': 'http://untrusted.example'},
            {'Origin': 'null'},
            {'Origin': 'http://127.0.0.1:1'},
            {'Origin': f'https://{self.host}'},
            {'Host': 'untrusted.example'},
            {'Host': 'localhost@untrusted.example'},
            {'Sec-Fetch-Site': 'cross-site'},
            {'Sec-Fetch-Site': 'same-site'},
        ):
            with self.subTest(headers=headers):
                self.assertEqual(self.request(headers=headers), 403)
        self.api.delete_profile.assert_not_called()

    def test_form_and_plain_text_posts_are_rejected(self):
        for content_type in ('text/plain', 'application/x-www-form-urlencoded', 'multipart/form-data', ''):
            with self.subTest(content_type=content_type):
                self.assertEqual(self.request(headers={'Content-Type': content_type}), 415)
        self.api.delete_profile.assert_not_called()

    def test_bodyless_json_actions_work(self):
        self.assertEqual(self.request(path='/api/profiles/clear-default', body=''), 200)
        self.api.clear_default_profile.assert_called_once()

    def test_node_route_decodes_folder_names(self):
        self.api.deactivate_node.return_value = {'success': True}
        self.assertEqual(self.request(path='/api/nodes/My%20Nodes/deactivate', body=''), 200)
        self.api.deactivate_node.assert_called_once_with('My Nodes')

    def test_non_object_json_is_rejected(self):
        for body in ('[]', 'null', '"string"'):
            with self.subTest(body=body):
                self.assertEqual(self.request(body=body), 400)
        self.api.delete_profile.assert_not_called()

    def test_websocket_checks_origin_before_upgrade(self):
        headers = {
            'Upgrade': 'websocket', 'Connection': 'Upgrade',
            'Sec-WebSocket-Key': 'dGhlIHNhbXBsZSBub25jZQ==',
            'Origin': 'http://untrusted.example',
        }
        self.assertEqual(self.request('GET', '/ws', headers, ''), 403)
        self.api.ws_register.assert_not_called()
        headers['Origin'] = f'http://{self.host}'
        self.assertEqual(self.request('GET', '/ws', headers, ''), 101)

    def test_loopback_variants_and_remote_peers(self):
        for peer, host in (('127.0.0.1', 'localhost:8199'), ('::1', '[::1]:8199'), ('::ffff:127.0.0.1', '[::ffff:127.0.0.1]:8199')):
            with self.subTest(host=host):
                headers = {'Origin': f'http://{host}'}
                self.assertTrue(is_local_api_request(peer, host, headers))
                self.assertTrue(is_local_request(SimpleNamespace(remote=peer, host=host, headers=headers, scheme='http')))
        self.assertFalse(is_local_api_request('192.168.1.2', 'localhost:8199', {}))
        self.assertFalse(is_local_api_request('127.invalid', 'localhost:8199', {}))

    def test_integrated_middleware(self):
        # Run the actual middleware without importing ComfyUI or registering routes.
        tree = ast.parse((ROOT / '__init__.py').read_text(encoding='utf-8'))
        middleware = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == '_mf_local_only')
        scope = {'web': web, 'is_local_request': is_local_request}
        exec(compile(ast.Module(body=[middleware], type_ignores=[]), '<integrated middleware>', 'exec'), scope)
        calls = []

        async def handler(request):
            calls.append(request)
            return web.Response(status=200)

        for origin, content_type, expected in (
            ('http://localhost:8188', 'application/json', 200),
            ('http://untrusted.example', 'application/json', 403),
            ('http://localhost:8188', 'text/plain', 415),
        ):
            request = SimpleNamespace(path='/mf_conductor/api/profiles/save', method='POST',
                                      remote='127.0.0.1', host='localhost:8188', scheme='http',
                                      headers={'Origin': origin}, content_type=content_type)
            response = asyncio.run(scope['_mf_local_only'](request, handler))
            self.assertEqual(response.status, expected)
        self.assertEqual(len(calls), 1)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mfconductor-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.nodes = self.root / 'custom_nodes'
        self.nodes.mkdir()
        # Generated launchers use the same scanner; keep its cache writes isolated too.
        self.cache_patch = patch.object(NodeScanner, '_invalidate_cache')
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)
        self.scanner = NodeScanner(str(self.nodes))

    def load_launcher(self, profile, name='Audit'):
        script = write_profile_launcher(self.root / 'conductor', name, profile, [])
        old_path = sys.path[:]
        try:
            return runpy.run_path(str(script), run_name='audit_launcher')
        finally:
            sys.path[:] = old_path

    def test_collision_preserves_both_folders_and_markers(self):
        for folder in ('Example', 'Example.disabled'):
            (self.nodes / folder).mkdir()
            (self.nodes / folder / 'unique.txt').write_text(folder)
            (self.nodes / folder / '.disabled').touch()
        for operation in (self.scanner.activate_node, self.scanner.deactivate_node):
            for name in ('Example', 'Example.disabled'):
                with self.subTest(operation=operation.__name__, name=name):
                    ok, message = operation(name)
                    self.assertFalse(ok)
                    self.assertIn('duplicate folders', message)
                    for folder in ('Example', 'Example.disabled'):
                        self.assertEqual((self.nodes / folder / 'unique.txt').read_text(), folder)
                        self.assertTrue((self.nodes / folder / '.disabled').exists())

    def test_normal_toggle_preserves_contents(self):
        (self.nodes / 'Example').mkdir()
        (self.nodes / 'Example' / 'unique.txt').write_text('keep')
        self.assertTrue(self.scanner.deactivate_node('Example')[0])
        self.assertTrue(self.scanner.activate_node('Example')[0])
        self.assertEqual((self.nodes / 'Example' / 'unique.txt').read_text(), 'keep')

    def test_activate_retries_windows_permission_error(self):
        (self.nodes / 'Example.disabled').mkdir()
        (self.nodes / 'Example.disabled' / 'unique.txt').write_text('keep')
        real_rename = os.rename
        calls = {'n': 0}

        def flaky(src, dst):
            calls['n'] += 1
            if calls['n'] < 3:
                raise PermissionError(13, 'Access is denied')
            return real_rename(src, dst)

        with patch('node_scanner.os.rename', flaky):
            ok, message = self.scanner.activate_node('Example')
        self.assertTrue(ok, message)
        self.assertGreaterEqual(calls['n'], 3)
        self.assertEqual((self.nodes / 'Example' / 'unique.txt').read_text(), 'keep')

    def test_profile_name_is_data_not_python(self):
        name = 'Audit"""\nAUDIT_INJECTED = True\n#'
        launcher = self.load_launcher({}, name)
        self.assertNotIn('AUDIT_INJECTED', launcher)
        self.assertEqual(launcher['PROFILE_NAME'], name)

    def test_shortcut_matches_api_profile_semantics(self):
        profiles = (
            {'enabled': [], 'disabled': ['example.disabled']},
            {'enabled': ['OTHER.disabled'], 'disabled': ['ComfyUI_MFConductor']},
            {'enabled': [], 'disabled': []},
        )
        for index, profile in enumerate(profiles):
            with self.subTest(profile=profile):
                roots = [self.root / f'{index}-api', self.root / f'{index}-shortcut']
                for root in roots:
                    root.mkdir()
                    for name in ('Example', 'Other.disabled', 'ComfyUI_MFConductor.disabled'):
                        (root / name).mkdir()
                scanner = NodeScanner(str(roots[0]))
                enabled = folders_for_profile(profile, scanner.list_folder_names())
                apply_enabled_folders(scanner, enabled, disable_others=False)
                self.load_launcher(profile)['apply_node_states'](roots[1])
                self.assertEqual(sorted(p.name for p in roots[0].iterdir()), sorted(p.name for p in roots[1].iterdir()))
                self.assertTrue((roots[1] / 'ComfyUI_MFConductor').is_dir())
                self.assertTrue((roots[1] / 'Example').is_dir())

    def test_shortcut_reports_collision_without_deleting(self):
        for name in ('Example', 'Example.disabled'):
            (self.nodes / name).mkdir()
        launcher = self.load_launcher({'enabled': ['Example']})
        with self.assertRaisesRegex(RuntimeError, 'duplicate folders'):
            launcher['apply_node_states'](self.nodes)
        self.assertTrue((self.nodes / 'Example').exists())
        self.assertTrue((self.nodes / 'Example.disabled').exists())


class PackageBlockingTests(unittest.TestCase):
    def test_distribution_aliases_namespaces_and_core_safeguards(self):
        with tempfile.TemporaryDirectory(prefix='mfconductor-import-test-') as temp:
            root = Path(temp)
            def distribution(name, files, top_level=None):
                metadata = root / (name.replace('-', '_') + '-1.0.dist-info')
                metadata.mkdir()
                (metadata / 'METADATA').write_text(f'Name: {name}\nVersion: 1.0\n')
                if files:
                    (metadata / 'RECORD').write_text('\n'.join(f'{file},,' for file in files))
                if top_level:
                    (metadata / 'top_level.txt').write_text(top_level)
                for file in files:
                    if file.startswith('../'):
                        continue
                    path = root / file
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('value = 42\n')

            distribution('audit-alias-dist', ['audit_import/__init__.py', 'audit_import/child.py'])
            distribution('audit-namespace-dist', ['audit_ns/blocked/__init__.py', 'audit_ns/direct.py'])
            distribution('audit-neighbor-dist', ['audit_ns/allowed/__init__.py'])
            distribution('audit-protected-dist', ['json/__init__.py'])
            distribution('audit-editable-dist', [], 'audit_editable')
            (root / 'audit_editable.py').write_text('value = 42\n')
            code = '''
import importlib.util, json, runpy, sys
sys.path.insert(0, sys.argv[1])
import audit_import, audit_import.child
runpy.run_path(sys.argv[2])
for name in ('audit_import', 'audit_ns.blocked', 'audit_ns.direct', 'audit_editable'):
    assert importlib.util.find_spec(name) is None, name
    try:
        __import__(name)
    except ModuleNotFoundError:
        pass
    else:
        raise AssertionError(name + ' imported')
assert 'audit_import.child' not in sys.modules
assert importlib.util.find_spec('audit_ns.allowed') is not None
assert importlib.util.find_spec('json') is not None
assert importlib.util.find_spec('pathlib') is not None
print('blocking checks passed')
'''
            env = os.environ.copy()
            env['MFCONDUCTOR_BLOCKED_PACKAGES'] = 'Audit_Alias_Dist,audit-namespace-dist,audit-protected-dist,audit-editable-dist,json,pathlib'
            result = subprocess.run([sys.executable, '-B', '-c', code, str(root), str(ROOT / 'prestartup_script.py')],
                                    env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('blocking checks passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
