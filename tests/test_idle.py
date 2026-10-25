"""Owned lifecycle guards; no real user agent processes are terminated."""
from contextlib import closing
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from agent_hub.idle import database, register, observe, expired, install_hooks, install_hermes_plugin


class IdleTests(unittest.TestCase):
    def test_unknown_busy_permission_and_compaction_never_expire(self):
        with tempfile.TemporaryDirectory() as state, closing(database(state)) as conn:
            ident = register(conn, 'codex', 'exact', '/project', os.getpid())
            payload = {'session_id': 'exact', 'prompt': 'DO_NOT_SAVE'}
            self.assertFalse(expired(conn, ident, 600, now=10000))
            self.assertTrue(observe('codex', 'Stop', payload, state, now=100))
            self.assertFalse(expired(conn, ident, 600, now=699))
            self.assertTrue(expired(conn, ident, 600, now=700))
            for event in ('UserPromptSubmit', 'PreToolUse', 'PermissionRequest', 'SubagentStart'):
                observe('codex', event, payload, state, now=100)
                observe('codex', 'SessionStart', payload, state, now=101)
                self.assertFalse(expired(conn, ident, 600, now=10000))
            observe('codex', 'Stop', payload, state, now=10000)
            self.assertFalse(expired(conn, ident, 600, now=10001))
            self.assertNotIn('DO_NOT_SAVE', str(list(conn.execute('SELECT * FROM launches'))))

    def test_new_owner_binding_wrong_session_ambiguity_and_reused_pid(self):
        with tempfile.TemporaryDirectory() as state, closing(database(state)) as conn:
            ident = register(conn, 'cursor', None, '/project', os.getpid())
            self.assertFalse(observe('cursor', 'stop', {'conversation_id': 'exact'}, state))
            self.assertTrue(observe('cursor', 'stop', {'conversation_id': 'exact'}, state, owner=ident, now=1))
            self.assertFalse(observe('cursor', 'stop', {'conversation_id': 'wrong'}, state, owner=ident))
            self.assertFalse(observe('cursor', 'stop', {'conversation_id': '--unsafe'}, state, owner=ident))
            self.assertTrue(expired(conn, ident, 600, now=601))
            with patch('agent_hub.idle.token', return_value='different-process'):
                self.assertFalse(expired(conn, ident, 600, now=10000))
            register(conn, 'cursor', 'exact', '/project', os.getpid())
            self.assertFalse(observe('cursor', 'stop', {'conversation_id': 'exact'}, state))

    def test_owned_child_closes_after_confirmed_idle_and_exact_session_can_reopen(self):
        from types import SimpleNamespace
        from agent_hub.idle import launch
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake = root/'native.py'
            fake.write_text("import os,time\nfrom agent_hub.idle import observe\nobserve('cursor','stop',{'conversation_id':'exact'},owner=os.environ['AGENT_HUB_LAUNCH_ID'],now=time.monotonic()-601)\ntime.sleep(30)\n")
            environment = {**os.environ, 'XDG_STATE_HOME': str(root),
                           'PYTHONPATH': str(Path(__file__).resolve().parents[1])}
            with patch.dict(os.environ, environment):
                code = launch(SimpleNamespace(id='cursor', container=''), [sys.executable, str(fake)], root, 'exact', 10)
                self.assertEqual(code, 0)
                with closing(database()) as conn:
                    self.assertEqual(conn.execute('SELECT COUNT(*) FROM launches').fetchone()[0], 0)
            # The adapter resumes the same native identity after cleanup.
            from agent_hub.agents import Agent
            agent = Agent('cursor','Cursor','cursor',str(root),[sys.executable],['--resume','{session}'])
            self.assertEqual(agent.argv(root,'exact')[-2:], ['--resume','exact'])

    def test_hook_install_preserves_existing_handlers_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root/'.cursor/hooks.json'
            path.parent.mkdir()
            personal = {'command': '/personal/observer'}
            path.write_text(json.dumps({'version': 1, 'hooks': {'stop': [personal]}}))
            with patch.dict(os.environ, {'CODEX_HOME': str(root/'.codex'), 'XDG_STATE_HOME': str(root/'state')}):
                install_hooks(root)
                first = path.read_text()
                install_hooks(root)
                self.assertEqual(first, path.read_text())
            self.assertIn(personal, json.loads(first)['hooks']['stop'])
            self.assertTrue(list((root/'state/agent-hub/backups').glob('*.json')))

    def test_hermes_plugin_exits_its_own_process_after_all_sessions_idle(self):
        from types import SimpleNamespace
        import signal
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root/'config/agent-hub/idle.json'
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({'version': 1, 'minutes': 1}))
            agent = SimpleNamespace(id='hermes', container='fixture', home=str(root/'hermes'),
                                    map_path=lambda path: str(path))
            calls = []
            with patch('agent_hub.idle.config_path', return_value=config), \
                 patch('agent_hub.idle.state_dir', return_value=root/'state/agent-hub'), \
                 patch('agent_hub.idle.subprocess.run', side_effect=lambda *a, **kw: calls.append(kw.get('input'))):
                install_hermes_plugin(agent)
            payload = json.loads(calls[0])
            namespace = {}
            exec(compile(payload['code'], '<hermes-plugin>', 'exec'), namespace)
            handlers = {}
            context = SimpleNamespace(register_hook=lambda event, handler: handlers.setdefault(event, handler))
            thread_targets = []
            class Thread:
                def __init__(self, **kwargs): thread_targets.append(kwargs['target'])
                def start(self): pass
            with patch('threading.Thread', Thread):
                namespace['register'](context)
            clock = iter((100.0, 161.0))
            with patch('subprocess.run'), patch('time.sleep'), patch('time.monotonic', side_effect=lambda: next(clock)), \
                 patch('os.kill') as kill:
                handlers['on_session_start'](session_id='session-a')
                handlers['on_session_end'](session_id='session-a')
                thread_targets[0]()
            kill.assert_called_once_with(os.getpid(), signal.SIGTERM)

            handlers = {}
            with patch('threading.Thread', Thread):
                namespace['register'](SimpleNamespace(register_hook=lambda event, handler: handlers.setdefault(event, handler)))
            with patch('subprocess.run'), patch('time.sleep', side_effect=StopIteration), patch('os.kill') as kill:
                handlers['on_session_start'](session_id='session-a')
                handlers['on_session_start'](session_id='session-b')
                handlers['on_session_end'](session_id='session-a')
                with self.assertRaises(StopIteration):
                    thread_targets[1]()
            kill.assert_not_called()
