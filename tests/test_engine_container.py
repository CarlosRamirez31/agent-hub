"""Opt-in real Podman sandbox tests: only Python fixtures, never models."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from agent_hub.cache import Cache
from agent_hub.engine.tasks import TaskStore
from agent_hub.engine.profiles import Profiles
from agent_hub.engine.workspace import Workspaces,git
from agent_hub.engine.execution import Runner
from agent_hub.engine.policy import Policies


@unittest.skipUnless(os.environ.get('AGENT_HUB_TEST_CONTAINER'),'Set AGENT_HUB_TEST_CONTAINER for the existing-container integration fixture')
class ContainerTests(unittest.TestCase):
    def setUp(self):
        # Existing test containers mount the host home; do not assume /tmp is shared.
        self.temp=tempfile.TemporaryDirectory(prefix='.hub-container-test-',dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.state=self.root/'state'
        self.cache=Cache(self.state/'index.sqlite');self.addCleanup(self.cache.close)
        self.repo=self.root/'repo';self.repo.mkdir();git(self.repo,'init','-q');git(self.repo,'config','user.email','fixture@example.invalid');git(self.repo,'config','user.name','Fixture')
        (self.repo/'file').write_text('base');git(self.repo,'add','.');git(self.repo,'commit','-qm','base')
        self.tasks=TaskStore(self.cache.conn);self.profiles=Profiles(self.cache.conn)
        self.profiles.register({'id':'container-fixture','provider':'fixture','command':['python3','-c',
            'import json;from pathlib import Path;Path("file").write_text("container");print(json.dumps({"text":"isolated"}))'],
            'container':{'name':os.environ['AGENT_HUB_TEST_CONTAINER'],'host_root':str(Path.home()),'runtime_root':os.environ.get('AGENT_HUB_TEST_MOUNT','/host-home')}})
        self.task=self.tasks.create({'title':'fixture','objective':'write file','complexity':'small','review':{'required':False},
            'assignment':{'mode':'fixed','agent':'container-fixture'},'scope':{'files':['file']},'permissions':{'filesystem':'write'}})
        self.spaces=Workspaces(self.cache.conn,self.state);self.spaces.create(self.task.id,self.repo);self.tasks.status(self.task.id,'ready')
    def test_native_container_sandbox_changes_only_task_worktree(self):
        result=Runner(self.cache.conn,self.state).run(self.task.id)
        self.assertEqual(result['status'],'completed',result)
        self.assertEqual((self.repo/'file').read_text(),'base')
        self.assertEqual((Path(self.spaces.get(self.task.id)['path'])/'file').read_text(),'container')
    def test_existing_hermes_cli_help_inside_sandbox_without_model(self):
        spec=self.profiles.get('container-fixture')
        spec['command']=['/usr/local/bin/hermes','--help'];spec['format']='text'
        self.profiles.register(spec)
        result=Runner(self.cache.conn,self.state).run(self.task.id)
        self.assertEqual(result['status'],'failed',result)
        self.assertIn('Read-only file system',result['result']['error'])
        # Hermes opens its own install-state lock even for --help. An explicit
        # narrow exception is required; do not disable the sandbox or run repair.
        Policies(self.cache.conn).set('default',{'runtime_write_paths':{'container-fixture':['/opt/hermes/.hermes/installs']}})
        self.tasks.status(self.task.id,'ready')
        result=Runner(self.cache.conn,self.state).run(self.task.id)
        self.assertEqual(result['status'],'completed',result)
        self.assertIn('usage:',result['result']['text'])

    def test_cancel_is_acknowledged_by_inner_runner(self):
        spec=self.profiles.get('container-fixture');spec['command']=['python3','-c','import time;time.sleep(10)'];self.profiles.register(spec)
        def run():
            cache=Cache(self.state/'index.sqlite')
            try:return Runner(cache.conn,self.state).run(self.task.id)
            finally:cache.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(run)
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                row=self.cache.conn.execute('SELECT id,pid FROM executions WHERE task=1').fetchone()
                if row and row['pid']:break
                time.sleep(.03)
            else:self.fail('container runner not started')
            Runner(self.cache.conn,self.state).cancel(self.task.id)
            self.assertEqual(future.result(timeout=5)['status'],'cancelled')
            self.assertTrue((self.state/'process-controls'/str(row['id'])/'complete').exists())

if __name__=='__main__':unittest.main()
