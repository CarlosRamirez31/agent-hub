from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout,redirect_stderr
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from agent_hub.cli import main
from agent_hub.cache import Cache
from agent_hub.engine.tasks import TaskStore
from agent_hub.engine.profiles import Profiles
from agent_hub.engine.policy import Policies
from agent_hub.engine.execution import Runner,parse_result
from agent_hub.engine.workspace import Workspaces,git
from agent_hub.engine.quality import Quality


class WorkCliTests(unittest.TestCase):
    def test_public_workflow_has_clean_json_without_native_discovery(self):
        with tempfile.TemporaryDirectory() as temporary,patch.dict(os.environ,XDG_STATE_HOME=temporary),patch('agent_hub.manager.Manager',side_effect=AssertionError('No implicit discovery')):
            root=Path(temporary)
            profile=root/'profile.json';profile.write_text(json.dumps({'id':'fixture','provider':'fixture','command':[sys.executable]}))
            def call(*argv):
                output,error=io.StringIO(),io.StringIO()
                with redirect_stdout(output),redirect_stderr(error):status=main(list(argv))
                return status,json.loads(output.getvalue()) if output.getvalue() else None,error.getvalue()
            self.assertEqual(call('work','profile','register','--file',str(profile))[0],0)
            self.assertEqual(call('work','profile','list')[1][0]['id'],'fixture')
            task=call('task','create','--title','Fixture','--json')[1]
            self.assertEqual(call('work','classify',task['id'])[0],0)
            run=call('work','run','plan','--intent','Write general response','--agent','fixture')[1]
            self.assertEqual(run['status'],'pending')
            self.assertEqual(call('work','run','execute',run['id'])[0],1)
            # Queries succeed even when the work is waiting on a human.
            self.assertEqual(call('work','run','show',run['id'])[0],0)
            self.assertEqual(call('work','events','--run',run['id'])[0],0)
            self.assertEqual(call('work','run','cancel',run['id'])[0],0)
            self.assertEqual(call('work','metrics')[1],[])

    def test_native_failure_keeps_verified_session_and_rejects_internal_fields(self):
        profile={'format':'codex-jsonl'}
        result=parse_result(profile,'\n'.join(json.dumps(event) for event in [
            {'type':'thread.started','thread_id':'exact-session'},
            {'type':'item.completed','item':{'type':'reasoning','text':'MUST_NOT_EXPORT'}},
            {'type':'turn.failed','error':{'message':'quota exceeded'}}]))
        self.assertEqual(result['native_id'],'exact-session')
        self.assertIn('quota',result['error'])
        self.assertNotIn('MUST_NOT_EXPORT',json.dumps(result))
        with self.assertRaises(ValueError):parse_result({'format':'json'},'{"text":"hello","reasoning":"private"}')
        with self.assertRaises(ValueError):parse_result({'format':'json'},'{"text":"hello","tokens":-1}')
        with self.assertRaises(ValueError):parse_result({'format':'json'},'{"text":"hello","native_id":"--last"}')


@unittest.skipUnless(shutil.which('bwrap'),'OS sandbox required')
class ManagedSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.state=self.root/'state'
        self.cache=Cache(self.state/'index.sqlite');self.addCleanup(self.cache.close)
        self.tasks=TaskStore(self.cache.conn);self.profiles=Profiles(self.cache.conn);self.spaces=Workspaces(self.cache.conn,self.state)
        self.repo=self.root/'repo';self.repo.mkdir();git(self.repo,'init','-q');git(self.repo,'config','user.email','fixture@example.invalid');git(self.repo,'config','user.name','Fixture')
        (self.repo/'file').write_text('base');git(self.repo,'add','.');git(self.repo,'commit','-qm','base')
        self.profiles.register({'id':'worker','provider':'fixture','command':[sys.executable,'-c','import json;from pathlib import Path;Path("file").write_text("change");print(json.dumps({"text":"done"}))']})
        self.profiles.register({'id':'reviewer','provider':'fixture','roles':['reviewer'],'capabilities':['security-review'],'command':[sys.executable,'-c','print(\'{"verdict":"approve","issues":[]}\')']})
    def task(self,critical=False,commit=False):
        task=self.tasks.create({'title':'Authentication' if critical else 'Fixture','objective':'make change','scope':{'files':['file']},
            'complexity':'critical' if critical else 'small','review':{'required':critical},
            'permissions':{'filesystem':'write','git_commit':commit},'assignment':{'mode':'fixed','agent':'worker'}})
        self.spaces.create(task.id,self.repo);self.tasks.status(task.id,'ready');return task
    def test_critical_gates_and_contract_change_invalidation(self):
        task=self.task(critical=True);runner=Runner(self.cache.conn,self.state);policy=Policies(self.cache.conn)
        with self.assertRaisesRegex(ValueError,'aprobación'):runner.run(task.id)
        self.assertEqual(self.cache.conn.execute('SELECT COUNT(*) FROM executions').fetchone()[0],0)
        policy.approve(task.id,'critical-start',self.spaces.fingerprint(task.id),True,'Reviewed contract')
        self.assertEqual(runner.run(task.id)['status'],'completed')
        quality=Quality(self.cache.conn,self.state);self.assertTrue(quality.verify(task.id,[[sys.executable,'-c','pass']])['passed'])
        self.assertEqual(runner.run(task.id,'reviewer','reviewer','code')['status'],'completed')
        self.assertEqual(runner.run(task.id,'reviewer','reviewer','security')['status'],'completed')
        self.assertFalse(quality.gate(task.id)['passed'])
        policy.approve(task.id,'critical-merge',self.spaces.fingerprint(task.id),True,'Reviewed code and security checks')
        self.assertTrue(quality.gate(task.id)['passed'])
        changed={**self.tasks.get(task.id).contract,'objective':'new objective'}
        self.tasks.replace_contract(task.id,changed,'human changed objective')
        self.assertFalse(quality.gate(task.id)['passed'])
    def test_commit_and_merge_require_explicit_fingerprint_approval(self):
        task=self.task(commit=True);policy=Policies(self.cache.conn);policy.set('default',{'git_commit':True})
        self.assertEqual(Runner(self.cache.conn,self.state).run(task.id)['status'],'completed')
        quality=Quality(self.cache.conn,self.state);self.assertTrue(quality.verify(task.id,[[sys.executable,'-c','pass']])['passed'])
        self.tasks.status(task.id,'done')
        with self.assertRaises(ValueError):self.spaces.commit(task.id,'fixture')
        fingerprint=self.spaces.fingerprint(task.id);policy.approve(task.id,'git-commit',fingerprint,True,'human approved')
        self.spaces.commit(task.id,'verified fixture')
        self.assertEqual(self.spaces.fingerprint(task.id),fingerprint)
        with self.assertRaises(ValueError):self.spaces.merge(task.id)
        policy.approve(task.id,'merge',fingerprint,True,'human approved')
        self.assertTrue(self.spaces.merge(task.id)['merged'])
        self.assertEqual((self.repo/'file').read_text(),'change')
    def test_cancel_managed_process_without_touching_other_agents(self):
        task=self.task()
        spec=self.profiles.get('worker');spec['command']=[sys.executable,'-c','import time;time.sleep(10)'];self.profiles.register(spec)
        def work():
            cache=Cache(self.state/'index.sqlite')
            try:return Runner(cache.conn,self.state).run(task.id)
            finally:cache.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(work)
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                row=self.cache.conn.execute('SELECT pid FROM executions WHERE task=1').fetchone()
                if row and row[0]:break
                time.sleep(.02)
            else:self.fail('managed process did not start')
            result=Runner(self.cache.conn,self.state).cancel(task.id)
            self.assertEqual(result['status'],'cancelled')
            self.assertEqual(future.result(timeout=4)['status'],'cancelled')

if __name__=='__main__':unittest.main()
