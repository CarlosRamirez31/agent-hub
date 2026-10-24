"""Task state and CLI fixtures never touch real agent sessions or call models."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from agent_hub.cache import Cache
from agent_hub.cli import main
from agent_hub.engine.tasks import TaskContract, TaskStore
from agent_hub.migrations import LEGACY_SCHEMA, SCHEMA_VERSION


def contract(title='Implementar ñ 日本語'):
    return {'title': title, 'objective': 'Cambiar un componente sin alterar el comportamiento.',
            'scope': {'files': ['src/components/Save Button.tsx']}, 'acceptance': ['Compila'],
            'assignment': {'mode': 'fixed', 'agent': 'custom-worker'}}


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'state/index.sqlite'
        self.cache = Cache(self.path)
        self.addCleanup(self.cache.close)
        self.store = TaskStore(self.cache.conn)

    def test_contract_roundtrip_and_no_agent_required(self):
        task = self.store.create(contract())
        self.assertEqual(task.id, 'TASK-001')
        self.assertEqual(task.status, 'pending')
        self.assertEqual(task.contract['assignment'], {'mode': 'fixed', 'agent': 'custom-worker'})
        second = Cache(self.path)
        try:
            self.assertEqual(TaskStore(second.conn).get(task.id), task)
        finally:
            second.close()
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_strict_contract_validation_and_scope(self):
        cases = [dict(contract(), title=''), dict(contract(), version=True), dict(contract(), bogus=1),
                 dict(contract(), permissions={'network': 'false'}),
                 dict(contract(), budget={'max_retries': True}),
                 dict(contract(), assignment={'mode': 'fixed'}),
                 dict(contract(), assignment={'mode': 'orchestrated', 'agent': 'codex'}),
                 dict(contract(), complexity='critical', review={'required': False})]
        cases += [dict(contract(), scope={'files': [p]}) for p in ('/etc/passwd', '../secret', 'a/../../b', 'a\\b')]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.create(value)
        self.assertEqual(self.store.list(), [])

    def test_dag_cycles_and_atomic_creation(self):
        a = self.store.create(contract('A'))
        b = self.store.create(contract('B'), [a.id])
        c = self.store.create(contract('C'), [b.id])
        with self.assertRaisesRegex(ValueError, 'ciclo'):
            self.store.dependency(a.id, c.id)
        with self.assertRaises(ValueError):
            self.store.dependency(a.id, a.id)
        with self.assertRaises(ValueError):
            self.store.create(contract(), ['TASK-999'])
        self.assertEqual(len(self.store.list()), 3)
        self.assertEqual(self.store.get(a.id).dependencies, ())
        self.assertEqual(self.store.get(c.id).blockers, (b.id,))

    def test_states_blockers_and_revision_guards(self):
        a = self.store.create(contract())
        b = self.store.create(contract(), [a.id])
        with self.assertRaisesRegex(ValueError, 'Dependencias'):
            self.store.status(b.id, 'ready')
        with self.assertRaisesRegex(ValueError, 'Transición'):
            self.store.status(a.id, 'done')
        for state in ('ready', 'running', 'verifying', 'reviewing', 'done'):
            a = self.store.status(a.id, state)
        b = self.store.status(b.id, 'ready')
        self.assertEqual(b.blockers, ())
        with self.assertRaisesRegex(ValueError, 'revisión'):
            self.store.status(b.id, 'running', expected_revision=1)
        self.assertEqual(self.store.get(b.id).status, 'ready')
        self.assertEqual(len(self.store.events(b.id)), 2)
        with self.assertRaises(ValueError): self.store.status(a.id, 'running')

    def test_dependency_mutation_does_not_leave_ready_task_runnable(self):
        a = self.store.create(contract())
        b = self.store.create(contract())
        self.store.status(a.id, 'ready')
        self.assertEqual(self.store.dependency(a.id, b.id).status, 'blocked')
        self.store.dependency(a.id, b.id, remove=True)
        self.store.status(a.id, 'ready')
        self.store.status(a.id, 'running')
        with self.assertRaises(ValueError): self.store.dependency(a.id, b.id)

    def test_concurrent_creation_has_unique_persistent_ids(self):
        def create(i):
            cache = Cache(self.path)
            try:
                return TaskStore(cache.conn).create(contract(str(i))).id
            finally:
                cache.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(create, range(12)))
        self.assertEqual(len(set(ids)), 12)
        self.assertEqual(len(self.store.list()), 12)

    def test_migration_preserves_v1_tables_and_is_idempotent(self):
        path = Path(self.temp.name)/'legacy.sqlite'
        conn = sqlite3.connect(path)
        for sql in LEGACY_SCHEMA: conn.execute(sql)
        conn.execute('PRAGMA user_version=1')
        conn.execute("INSERT INTO conversations VALUES ('fixture','chat','title','/workspace',1,0,'project')")
        conn.execute("INSERT INTO transfers VALUES ('handoff-fixture','fixture','chat','other','p','name','/workspace','title',NULL,NULL,'prepared',1)")
        conn.commit(); conn.close()
        for _ in range(2):
            migrated = Cache(path)
            try:
                self.assertEqual(migrated.conn.execute('PRAGMA user_version').fetchone()[0], SCHEMA_VERSION)
                self.assertEqual(migrated.snapshot('fixture')[0][0].id, 'chat')
                self.assertEqual(migrated.transfer('handoff-fixture')['status'], 'prepared')
            finally:
                migrated.close()

    def test_migration_failure_rolls_back_and_future_schema_is_not_downgraded(self):
        from agent_hub import migrations
        conn = sqlite3.connect(':memory:')
        for sql in LEGACY_SCHEMA: conn.execute(sql)
        conn.execute('PRAGMA user_version=1'); conn.commit()
        with patch.object(migrations, 'TASK_SCHEMA', migrations.TASK_SCHEMA + ('INVALID SQL',)):
            with self.assertRaises(sqlite3.Error): migrations.migrate(conn)
        self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 1)
        self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='tasks'").fetchone())
        conn.execute('PRAGMA user_version=99'); conn.commit()
        with self.assertRaises(ValueError): migrations.migrate(conn)
        self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 99)
        conn.close()

    def test_cli_persists_without_registry_or_native_sync_and_demo_does_not_write(self):
        with patch.dict(os.environ, XDG_STATE_HOME=self.temp.name), \
             patch('agent_hub.manager.Manager', side_effect=AssertionError('No native discovery')), \
             patch('subprocess.Popen', side_effect=AssertionError('No models')):
            def call(*argv):
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err): code = main(['task', *argv, '--json'])
                return code, out.getvalue(), err.getvalue()
            code, output, _ = call('create', '--title', 'General ñ ; $(never-run)')
            self.assertEqual(code, 0)
            ident = json.loads(output)['id']
            self.assertEqual(call('status', ident, 'ready')[0], 0)
            self.assertEqual(json.loads(call('show', ident)[1])['status'], 'ready')
            self.assertEqual(len(json.loads(call('list')[1])), 1)
            self.assertEqual(call('show', 'TASK-999')[0], 1)
            self.assertEqual(call('create', '--demo', '--title', 'ephemeral')[0], 0)
            self.assertEqual(len(json.loads(call('list')[1])), 1)
            self.assertEqual(call('create')[0], 1)

if __name__ == '__main__': unittest.main()
