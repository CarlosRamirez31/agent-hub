"""Confirmed deletion: native commands, cross-agent scope, and file boundaries."""
from contextlib import closing
import json
import sqlite3
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent_hub.agents import Agent, native_delete
from agent_hub.deletion import checked_roots, delete_chat, delete_folder, folder_plan
from agent_hub.manager import Manager, private_json
from agent_hub.rpc import codex_delete


class DeletionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.work = self.root/'project with spaces'
        self.work.mkdir()
        (self.work/'.git').mkdir()
        (self.work/'.git/config').write_text('fixture')
        self.script = self.root/'delete.py'
        self.script.write_text('''import json, pathlib, sys
path = pathlib.Path(sys.argv[1])/'index.json'
data = json.loads(path.read_text())
data['conversations'] = [c for c in data['conversations'] if c['id'] != sys.argv[2]]
path.write_text(json.dumps(data))
''')
        self.agents = []
        for ident in ('one', 'two'):
            home = self.root/ident
            home.mkdir()
            agent = Agent(ident, ident, 'normalized', str(home), [sys.executable],
                          delete=[str(self.script), str(home), '{session}'])
            self.agents.append(agent)
            self.seed(agent, [{'id': ident, 'cwd': str(self.work), 'archived': ident == 'two'}])
        self.manager = Manager(self.agents, self.root/'state')
        self.addCleanup(self.manager.close)
        self.manager.sync()

    def seed(self, agent, chats):
        private_json(Path(agent.home)/'index.json', {'version': 1,
            'projects': [{'id': 'ppe', 'name': 'PPE', 'roots': [str(self.work)]}],
            'conversations': [{'title': 'Chat', 'updated': 1, 'project_id': 'ppe', **c} for c in chats]})

    def test_native_chat_delete_preserves_files_other_agents_and_invalidates_route(self):
        chats, projects = self.manager.snapshot('one')
        route = self.manager.route('one', chats[0], projects)
        with self.assertRaisesRegex(ValueError, 'confirmar'):
            delete_chat(self.manager, 'one', chats[0])
        self.assertEqual(len(self.agents[0].index()[0]), 1)
        delete_chat(self.manager, 'one', chats[0], confirmed=True)
        self.manager.sync()
        self.assertEqual(self.manager.snapshot('one')[0], [])
        self.assertEqual(len(self.manager.snapshot('two')[0]), 1)
        self.assertTrue((self.work/'.git/config').exists())
        with self.assertRaisesRegex(ValueError, 'no existe'):
            self.manager.resolve(route)

    def test_folder_deletes_all_agents_archives_nested_files_but_not_symlink_target(self):
        outside = self.root/'outside'
        outside.mkdir()
        (outside/'keep').write_text('keep')
        (self.work/'linked').symlink_to(outside, target_is_directory=True)
        plan = folder_plan(self.manager, 'one', 'ppe')
        self.assertEqual(len(plan['conversations']), 2)
        with self.assertRaisesRegex(ValueError, 'confirmar'):
            delete_folder(self.manager, plan)
        self.assertTrue(self.work.exists())
        self.assertEqual(delete_folder(self.manager, plan, confirmed=True), 2)
        self.assertFalse(self.work.exists())
        self.assertTrue((outside/'keep').exists())
        self.manager.sync()
        for agent in self.agents:
            self.assertEqual(self.manager.snapshot(agent.id), ([], []))

    def test_changed_scope_requires_new_confirmation_before_native_deletion(self):
        plan = folder_plan(self.manager, 'one', 'ppe')
        self.seed(self.agents[0], [{'id': 'one', 'cwd': str(self.work)}, {'id': 'new-chat', 'cwd': str(self.work)}])
        with self.assertRaisesRegex(ValueError, 'cambiaron'):
            delete_folder(self.manager, plan, confirmed=True)
        self.assertTrue(self.work.exists())
        self.assertEqual(len(self.agents[0].index()[0]), 2)

    def test_partial_native_failure_keeps_directory_and_reports_completed_count(self):
        plan = folder_plan(self.manager, 'one', 'ppe')
        with patch.object(self.agents[1], 'delete_conversation', side_effect=ValueError('active session')):
            with self.assertRaisesRegex(ValueError, 'parcial: 1 conversaciones'):
                delete_folder(self.manager, plan, confirmed=True)
        self.assertTrue((self.work/'.git/config').exists())
        self.assertEqual(self.agents[0].index()[0], [])
        self.assertEqual(len(self.agents[1].index()[0]), 1)

    def test_missing_source_or_unsupported_agent_rejects_entire_plan(self):
        self.agents[1].delete = []
        with self.assertRaisesRegex(ValueError, 'mecanismo nativo'):
            folder_plan(self.manager, 'one', 'ppe')
        self.agents[1].delete = ['delete', '{session}']
        (Path(self.agents[1].home)/'index.json').unlink()
        with self.assertRaisesRegex(ValueError, 'todos los agentes'):
            folder_plan(self.manager, 'one', 'ppe')
        self.assertTrue(self.work.exists())
        self.assertEqual(len(self.agents[0].index()[0]), 1)

    def test_root_home_history_state_and_symbolic_root_are_rejected(self):
        link = self.root/'alias'
        link.symlink_to(self.work, target_is_directory=True)
        for root in ('/', '/usr', '/etc', str(Path.home()), str(self.manager.state), self.agents[0].home, str(link)):
            with self.subTest(root=root), self.assertRaises(ValueError):
                checked_roots(self.manager, [root])

    def test_replaced_root_after_plan_is_rejected(self):
        plan = folder_plan(self.manager, 'one', 'ppe')
        self.work.rename(self.root/'old-project')
        self.work.mkdir()
        with self.assertRaisesRegex(ValueError, 'cambiaron'):
            delete_folder(self.manager, plan, confirmed=True)
        self.assertTrue(self.work.exists())

    def test_prepared_new_chat_delete_never_calls_native_agent(self):
        route = self.manager.prepare_new('one', 'ppe')
        _, chat = self.manager.resolve(route)
        with patch.object(self.agents[0], 'delete_conversation') as native:
            delete_chat(self.manager, 'one', chat, confirmed=True)
            native.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'no existe'):
            self.manager.resolve(route)

    def test_folder_plan_includes_hidden_hermes_history_without_exposing_it_in_menu(self):
        home = self.root/'hermes-fixture'
        home.mkdir()
        db = home/'state.db'
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute('CREATE TABLE sessions (id TEXT, title TEXT, cwd TEXT, started_at INT, hidden INT)')
            conn.executemany('INSERT INTO sessions VALUES (?, ?, ?, ?, ?)',
                             [('visible', 'Visible', str(self.work), 1, 0),
                              ('hidden', 'Compressed predecessor', str(self.work), 1, 1)])
        original = db.read_bytes()
        self.manager.agents.append(Agent('hermes', 'Hermes', 'hermes', str(home), [sys.executable]))
        plan = folder_plan(self.manager, 'one', 'ppe')
        self.assertEqual([c.id for c in self.manager.snapshot('hermes')[0]], ['visible'])
        self.assertEqual({c.id for agent, c in plan['conversations'] if agent == 'hermes'}, {'visible', 'hidden'})
        self.assertEqual(db.read_bytes(), original)

    def test_codex_uses_exact_native_rpc_and_hermes_uses_exact_argv(self):
        with patch('agent_hub.rpc.CodexReader') as reader:
            codex_delete('/isolated', 'native-id')
            self.assertEqual(reader.return_value.call.call_args.args, ('thread/delete', {'threadId': 'native-id'}))
            reader.return_value.close.assert_called_once()
            codex_delete('/isolated', 'project-id', project=True)
            self.assertEqual(reader.return_value.call.call_args.args, ('project/delete', {'projectId': 'project-id'}))
        with patch('agent_hub.agents.run_delete', return_value={}) as run:
            native_delete('hermes', '/isolated', 'native-id')
            self.assertEqual(run.call_args.args[0], ['hermes', 'sessions', 'delete', 'native-id', '--yes'])
            self.assertEqual(run.call_args.kwargs['env']['HERMES_HOME'], '/isolated')
