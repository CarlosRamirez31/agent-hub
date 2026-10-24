from pathlib import Path
import json
import shutil
import sys
import tempfile
import unittest
from agent_hub.cache import Cache
from agent_hub.engine.tasks import TaskStore
from agent_hub.engine.profiles import Profiles
from agent_hub.engine.workspace import Workspaces,git
from agent_hub.engine.execution import Runner
from agent_hub.engine.quality import Quality
from agent_hub.engine.context import Contexts
from agent_hub.engine.skills import Skills
from agent_hub.engine.process import execute


@unittest.skipUnless(shutil.which('bwrap'),'OS sandbox required')
class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.cache=Cache(self.root/'state/index.sqlite');self.addCleanup(self.cache.close)
        self.tasks=TaskStore(self.cache.conn);self.profiles=Profiles(self.cache.conn)
        self.workspace=Workspaces(self.cache.conn,self.root/'state')
        self.quality=Quality(self.cache.conn,self.root/'state');self.runner=Runner(self.cache.conn,self.root/'state')
        repo=self.root/'repo';repo.mkdir();self.repo=repo
        git(repo,'init','-q');git(repo,'config','user.email','fixture@example.invalid');git(repo,'config','user.name','Fixture')
        (repo/'file.txt').write_text('base');git(repo,'add','.');git(repo,'commit','-qm','base')
        self.profiles.register({'id':'worker','provider':'fixture','command':[sys.executable,'-c',
            'import json;from pathlib import Path;Path("file.txt").write_text("worker");print(json.dumps({"text":"done"}))']})
        self.profiles.register({'id':'reviewer','provider':'fixture','roles':['reviewer'],'command':[sys.executable,'-c',
            'import json;print(json.dumps({"verdict":"approve","issues":[]}))']})
    def task(self,review=False):
        task=self.tasks.create({'title':'Write fixture','objective':'write fixture file','complexity':'small',
            'scope':{'files':['file.txt']},'permissions':{'filesystem':'write'},'review':{'required':review},
            'assignment':{'mode':'fixed','agent':'worker'}})
        self.workspace.create(task.id,self.repo);self.tasks.status(task.id,'ready');return task
    def test_worker_isolation_verifier_and_independent_review_gates(self):
        task=self.task(review=True)
        result=self.runner.run(task.id)
        self.assertEqual(result['status'],'completed',result)
        self.assertEqual((self.repo/'file.txt').read_text(),'base')
        with self.assertRaises(ValueError):self.tasks.status(task.id,'done')
        self.assertTrue(self.quality.verify(task.id,[[sys.executable,'-c','from pathlib import Path;assert Path("file.txt").read_text()=="worker"']])['passed'])
        self.assertFalse(self.quality.gate(task.id)['passed'])
        with self.assertRaises(ValueError):self.quality.review(task.id,'worker',{'verdict':'approve','issues':[]})
        review=self.runner.run(task.id,'reviewer',role='reviewer')
        self.assertEqual(review['status'],'completed',review)
        self.assertTrue(self.quality.gate(task.id)['passed'])
        self.assertEqual(self.tasks.status(task.id,'done').status,'done')
    def test_readonly_reviewer_and_host_files_not_writable(self):
        task=self.task();path=self.workspace.get(task.id)['path']
        result=execute([sys.executable,'-c','from pathlib import Path;Path("file.txt").write_text("bad")'],path,writable=False)
        self.assertNotEqual(result['code'],0)
        host=self.root/'host.txt';host.write_text('safe')
        result=execute([sys.executable,'-c',f'from pathlib import Path;Path({str(host)!r}).write_text("bad")'],path,writable=True)
        # /tmp is private scratch inside the sandbox; either denial or a
        # private shadow is valid, but the original host file must be unchanged.
        self.assertEqual(host.read_text(),'safe')
    def test_verification_stale_after_changes_and_failed_checks(self):
        task=self.task();self.assertEqual(self.runner.run(task.id)['status'],'completed')
        self.assertFalse(self.quality.verify(task.id,[[sys.executable,'-c','raise SystemExit(1)']])['passed'])
        self.assertFalse(self.quality.gate(task.id)['passed'])
        self.assertTrue(self.quality.verify(task.id,[[sys.executable,'-c','pass']])['passed'])
        (Path(self.workspace.get(task.id)['path'])/'file.txt').write_text('changed after verify')
        self.assertFalse(self.quality.gate(task.id)['passed'])
    def test_native_output_limits_and_timeout(self):
        task=self.task();path=self.workspace.get(task.id)['path']
        self.assertEqual(execute([sys.executable,'-c','import time;time.sleep(5)'],path,timeout=.1)['failure'],'timeout')
        self.assertEqual(execute([sys.executable,'-c','print("x"*2000000)'],path)['failure'],'output_limit')
    def test_context_skills_budget_and_handoff_cycle(self):
        task=self.task();skills=Skills(self.cache.conn)
        skills.register('global-test','Keep local changes.');skills.register('private-other','secret rules','agent','other')
        context=Contexts(self.cache.conn,self.root/'state')
        profile=self.profiles.get('worker')
        pack=context.build(task.id,profile,history=[{'role':'system','text':'HIDDEN'},{'role':'user','text':'visible'}])
        self.assertNotIn('HIDDEN',json.dumps(pack))
        self.assertLessEqual(len(json.dumps({k:v for k,v in pack.items() if k!='id'},ensure_ascii=False)),40000)
        with self.assertRaises(ValueError):skills.for_task(task,{**profile,'skills':['private-other']})
        self.profiles.register({'id':'other','provider':'fixture','command':[sys.executable]})
        with self.assertRaises(ValueError):context.handoff(task.id,'worker','other','manual',{'summary':'continue'})
        context.handoff(task.id,'worker','other','manual',{'summary':'continue'},fixed_override=True)
        with self.assertRaisesRegex(ValueError,'Ciclo'):context.handoff(task.id,'other','worker','manual',{'summary':'continue'},fixed_override=True)
        self.assertEqual(self.tasks.get(task.id).status,'waiting_human')

if __name__=='__main__':unittest.main()
