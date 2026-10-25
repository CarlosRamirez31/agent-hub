"""Cursor metadata, exact sessions and orchestration without model requests."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent_hub.agents import Agent
from agent_hub.cache import Cache
from agent_hub.engine.bootstrap import initialize
from agent_hub.engine.execution import parse_result
from agent_hub.engine.profiles import Profiles
from agent_hub.engine.skills import Skills
from agent_hub.engine.tasks import TaskStore
from agent_hub.native import read_index, read_messages


class CursorIntegrationTests(unittest.TestCase):
    def test_native_metadata_keeps_exact_cwd_and_ignores_empty_and_unknown_sessions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for ident, meta in [('exact', {'cwd': '/some/project with spaces', 'hasConversation': True, 'updatedAtMs': 1800000000000}),
                                ('empty', {'cwd': '/some/project', 'hasConversation': False}), ('missing-cwd', {})]:
                path = root/'chats/hash'/ident
                path.mkdir(parents=True)
                (path/'meta.json').write_text(json.dumps(meta))
                (path/'prompt_history.json').write_text('DO_NOT_READ_TOOL_OR_SECRET')
            chats, _ = read_index('cursor', root)
            self.assertEqual([(c.id, c.cwd) for c in chats], [('exact', '/some/project with spaces')])
            self.assertEqual(chats[0].updated, 1800000000)
            with self.assertRaisesRegex(ValueError, 'no exporta'):
                read_messages('cursor', root, 'exact')

    def test_worker_reviewer_global_skills_and_exact_resume_without_permission_bypass(self):
        cache = Cache(':memory:')
        self.addCleanup(cache.close)
        agent = Agent('cursor', 'Cursor', 'cursor', '/native', [sys.executable],
                      ['--workspace', '{cwd}', '--resume', '{session}'], ['--workspace', '{cwd}'])
        created = initialize(cache.conn, [agent])
        self.assertEqual(created['created'], ['cursor', 'cursor-reviewer'])
        self.assertFalse(initialize(cache.conn, [agent])['created'])
        self.assertEqual(agent.argv('/project with spaces', 'exact-id'),
                         [sys.executable, '--workspace', '/project with spaces', '--resume', 'exact-id'])
        for profile in Profiles(cache.conn).list():
            self.assertTrue(profile['available'])
            self.assertIn('{session}', profile['resume_command'])
            for flag in ('--force', '--yolo', '--trust', '--approve-mcps'):
                self.assertNotIn(flag, profile['command'])
        skills = Skills(cache.conn)
        for name in ('surgical-edits', 'anti-overengineering', 'repo-scaffold', 'appsec-guardrail', 'software-architect', 'context-efficiency'):
            skills.register(name, 'fixture '+name)
        task = TaskStore(cache.conn).create({'title': 'fixture', 'objective': 'fixture'})
        for profile in Profiles(cache.conn).list():
            self.assertEqual({item['id'] for item in skills.for_task(task, profile)},
                             {'context-efficiency', 'software-architect'})

    def test_stream_persists_only_final_visible_text_and_native_identity(self):
        events = [{'type': 'system', 'subtype': 'init', 'session_id': 'exact-id'},
                  {'type': 'tool_call', 'tool_call': {'secret': 'DO_NOT_STORE'}},
                  {'type': 'thinking', 'text': 'DO_NOT_STORE'},
                  {'type': 'result', 'subtype': 'success', 'session_id': 'exact-id', 'result': 'visible answer'}]
        result = parse_result({'format': 'cursor-jsonl'}, '\n'.join(map(json.dumps, events)))
        self.assertEqual(result['native_id'], 'exact-id')
        self.assertEqual(result['text'], 'visible answer')
        self.assertNotIn('DO_NOT_STORE', json.dumps(result))
        events[-1].update(is_error=True, result='Rate limit reached')
        failed = parse_result({'format': 'cursor-jsonl'}, '\n'.join(map(json.dumps, events)))
        self.assertEqual(failed['error'], 'Rate limit reached')
        early = parse_result({'format': 'cursor-jsonl'}, json.dumps({'type': 'error', 'message': 'Rate limit reached'}))
        self.assertIsNone(early['native_id'])
        self.assertEqual(early['error'], 'Rate limit reached')
