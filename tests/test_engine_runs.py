from pathlib import Path
import json
import shutil
import sys
import tempfile
import unittest
from agent_hub.cache import Cache
from agent_hub.engine.tasks import TaskStore
from agent_hub.engine.profiles import Profiles
from agent_hub.engine.runs import Runs
from agent_hub.engine.workspace import Workspaces,git
from agent_hub.engine.routing import Router,classify


@unittest.skipUnless(shutil.which('bwrap'),'OS isolation required')
class RunTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.state=self.root/'state'
        self.cache=Cache(self.state/'index.sqlite');self.addCleanup(self.cache.close)
        self.tasks=TaskStore(self.cache.conn);self.profiles=Profiles(self.cache.conn);self.runs=Runs(self.cache.conn,self.state)
        self.repo=self.root/'repo';self.repo.mkdir()
        git(self.repo,'init','-q');git(self.repo,'config','user.email','fixture@example.invalid');git(self.repo,'config','user.name','Fixture')
        (self.repo/'file.txt').write_text('base');git(self.repo,'add','.');git(self.repo,'commit','-qm','base')
        self.profiles.register({'id':'worker','provider':'fixture','command':[sys.executable,'-c',
            'import json;from pathlib import Path;Path("file.txt").write_text("worker");print(json.dumps({"text":"done"}))'],
            'capabilities':['coding'],'cost_class':'low'})
        self.profiles.register({'id':'academic','provider':'fixture','command':[sys.executable],
            'capabilities':['coding','academic-writing'],'priority_domains':['academic'],'cost_class':'local'})
    def item(self,key,depends=()):
        return {'key':key,'contract':{'title':key,'objective':'write file','scope':{'files':['file.txt']},
                'permissions':{'filesystem':'write'},'complexity':'small','review':{'required':False},
                'assignment':{'mode':'fixed','agent':'worker'}},'repo':str(self.repo),
                'depends_on':list(depends),'checks':[[sys.executable,'-c','from pathlib import Path;assert Path("file.txt").read_text()=="worker"']]}
    def test_parallel_worktrees_and_persistent_metrics(self):
        run=self.runs.create({'title':'parallel','tasks':[self.item('one'),self.item('two')],
                              'budget':{'max_parallel':2,'max_agents':2}})
        result=self.runs.execute(run['id'])
        self.assertEqual(result['status'],'done',result['results'])
        self.assertEqual((self.repo/'file.txt').read_text(),'base')
        paths=[Workspaces(self.cache.conn,self.state).get(t['id'])['path'] for t in result['tasks']]
        self.assertEqual(len(set(paths)),2)
        self.assertEqual(self.cache.conn.execute('SELECT COUNT(*) FROM agent_metrics').fetchone()[0],2)
        self.assertTrue(self.cache.conn.execute('SELECT 1 FROM engine_events WHERE type=\'run.done\'').fetchone())
    def test_dependency_requires_explicit_integration_before_downstream_edits(self):
        run=self.runs.create({'title':'DAG','tasks':[self.item('one'),self.item('two',['one'])]})
        result=self.runs.execute(run['id'])
        self.assertEqual(result['tasks'][0]['status'],'done')
        self.assertEqual(result['tasks'][1]['status'],'waiting_human')
        self.assertIn('Integra primero',str(result['results']))
        self.assertEqual((self.repo/'file.txt').read_text(),'base')
    def test_plan_cycles_rollback_and_no_worker_launch(self):
        with self.assertRaises(ValueError):
            self.runs.create({'title':'cycle','tasks':[self.item('a',['b']),self.item('b',['a'])]})
        self.assertEqual(self.runs.list(),[])
        self.assertEqual(self.tasks.list(),[])
        plan=self.runs.plan('Implementar recuperación de contraseña',str(self.repo),['file.txt'])
        self.assertEqual(len(plan['tasks']),2)
        self.assertEqual(plan['tasks'][1]['dependencies'],[plan['tasks'][0]['id']])
        self.assertEqual(self.cache.conn.execute('SELECT COUNT(*) FROM executions').fetchone()[0],0)
    def test_specialization_and_fixed_assignment(self):
        task=self.tasks.create({'title':'Trabajo universitario APA','objective':'academic-writing',
            'domain':'academic','capabilities':['academic-writing']})
        self.assertEqual(Router(self.cache.conn).choose(task.id)['selected'],'academic')
        fixed=self.tasks.create({'title':'Code','objective':'write','assignment':{'mode':'fixed','agent':'missing'}})
        with self.assertRaises(ValueError):Router(self.cache.conn).choose(fixed.id)
        self.assertEqual(classify({'title':'Authentication','objective':'password handling','scope':{'files':['a']},'complexity':'trivial','domain':'general'})['complexity'],'critical')
    def test_orchestrated_quota_handoff_and_fixed_no_substitution(self):
        self.profiles.register({'id':'quota-worker','provider':'fixture','cost_class':'local','command':[sys.executable,'-c',
            'import json,sys;print(json.dumps({"text":"partial","native_id":"exact-quota-session"}));sys.stderr.write("quota exceeded");sys.exit(1)']})
        item=self.item('handoff');item['contract']['assignment']={'mode':'orchestrated'}
        # Avoid the generic academic fixture for this coding task.
        item['contract']['capabilities']=['coding']
        quota=self.profiles.get('quota-worker');quota['capabilities']=['coding'];self.profiles.register(quota)
        academic=self.profiles.get('academic');academic['enabled']=False;self.profiles.register(academic)
        run=self.runs.create({'title':'quota','tasks':[item]})
        result=self.runs.execute(run['id'])
        self.assertEqual(result['status'],'done',result['results'])
        handoff=self.cache.conn.execute('SELECT source,target,reason FROM structured_handoffs').fetchone()
        self.assertEqual(tuple(handoff),('quota-worker','worker','quota_exhausted'))
        failed=json.loads(self.cache.conn.execute("SELECT result FROM executions WHERE profile='quota-worker'").fetchone()[0])
        self.assertEqual(failed['native_id'],'exact-quota-session')
        fixed=self.item('fixed');fixed['contract']['assignment']={'mode':'fixed','agent':'quota-worker'}
        run=self.runs.create({'title':'fixed quota','tasks':[fixed]})
        result=self.runs.execute(run['id'])
        self.assertEqual(result['status'],'waiting_human')
        profiles=[r[0] for r in self.cache.conn.execute('SELECT profile FROM executions WHERE task=?',(int(run['tasks'][0]['id'][5:]),))]
        self.assertEqual(profiles,['quota-worker'])

    def test_run_budget_cancel_and_recovery(self):
        run=self.runs.create({'title':'limits','tasks':[self.item('one'),self.item('two')],
                             'budget':{'max_turns':1}})
        result=self.runs.execute(run['id'])
        self.assertEqual(result['status'],'waiting_human')
        self.assertEqual(self.cache.conn.execute('SELECT COUNT(*) FROM executions').fetchone()[0],1)
        self.assertEqual(self.runs.cancel(run['id'])['status'],'cancelled')
        with self.assertRaises(ValueError):self.runs.execute(run['id'])

if __name__=='__main__':unittest.main()
