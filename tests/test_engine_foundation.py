from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from agent_hub.cache import Cache
from agent_hub.engine.tasks import TaskStore
from agent_hub.engine.profiles import Profiles
from agent_hub.engine.workspace import Workspaces, git


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.cache=Cache(self.root/'state/index.sqlite');self.addCleanup(self.cache.close)
        self.tasks=TaskStore(self.cache.conn)
        self.profiles=Profiles(self.cache.conn)
        self.workspaces=Workspaces(self.cache.conn,self.root/'state')

    def test_profile_capabilities_and_offline_availability(self):
        value=self.profiles.register({'id':'hermes-academic','provider':'hermes','command':[sys.executable],
            'specializations':['university-work'],'skills':['apa'],'cost_class':'local','priority_domains':['academic']})
        self.assertEqual(value['provider'],'hermes')
        self.assertTrue(self.profiles.list()[0]['available'])
        self.profiles.unregister(value['id'])
        self.assertFalse(self.profiles.list()[0]['available'])
        with self.assertRaises(ValueError):self.profiles.register({'id':'bad','provider':'test','command':'sh -c bad'})

    def test_one_task_one_worktree_preserves_dirty_checkout(self):
        repo=self.root/'repo';repo.mkdir()
        git(repo,'init','-q');git(repo,'config','user.email','fixture@example.invalid');git(repo,'config','user.name','Fixture')
        (repo/'tracked').write_text('base');git(repo,'add','tracked');git(repo,'commit','-qm','base')
        (repo/'tracked').write_text('user dirty change')
        (repo/'untracked').write_text('user file')
        task=self.tasks.create({'title':'work','objective':'isolate'})
        second=self.tasks.create({'title':'other','objective':'isolate'})
        a=self.workspaces.create(task.id,repo);b=self.workspaces.create(second.id,repo)
        self.assertNotEqual(a['path'],b['path'])
        self.assertEqual((repo/'tracked').read_text(),'user dirty change')
        self.assertEqual((Path(a['path'])/'tracked').read_text(),'base')
        self.assertEqual(self.workspaces.create(task.id,repo),a)
        before=self.workspaces.fingerprint(task.id)
        (Path(a['path'])/'tracked').write_text('worker')
        self.assertNotEqual(before,self.workspaces.fingerprint(task.id))
        self.assertEqual(self.workspaces.changed_files(task.id),['tracked'])
        self.assertEqual((repo/'untracked').read_text(),'user file')

if __name__=='__main__':unittest.main()
