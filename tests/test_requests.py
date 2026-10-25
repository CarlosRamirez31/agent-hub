"""Directory intake, architecture gates and native-free full execution."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent_hub.cache import Cache
from agent_hub.engine.requests import prepare,resolve,validate,execute_ready
from agent_hub.engine.project_memory import load,call
from agent_hub.engine.runs import Runs
from agent_hub.engine.profiles import Profiles
from agent_hub.engine.skills import Skills
from agent_hub.engine.workspace import Workspaces
from agent_hub.engine.tasks import TaskStore


def plan():
    return {'status':'ready','summary':'Change the existing module',
            'architecture':{'status':'defined','content':'# Defined architecture\nmain.py contains the bounded fixture. Check the behavior with Python.\n','evidence':['main.py'],'pending':[]},
            'files':['main.py'],'checks':[[sys.executable,'-c',"from pathlib import Path;assert Path('main.py').read_text()=='changed'"]],
            'constraints':['Only main.py'],'acceptance':['The check passes'],'questions':[]}


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.home=self.root/'home';self.home.mkdir()
        self.environment=patch.dict(os.environ,HOME=str(self.home));self.environment.start();self.addCleanup(self.environment.stop)
        self.repo=self.home/'Documents/Programacion/app';self.repo.mkdir(parents=True)
        (self.repo/'main.py').write_text('original')
        self.cache=Cache(self.root/'state/index.sqlite');self.addCleanup(self.cache.close)
        self.runs=Runs(self.cache.conn,self.root/'state')
        for name in ('software-architect','anti-overengineering','appsec-guardrail','repo-scaffold'):
            Skills(self.cache.conn).register(name,'fixture '+name)

    def test_existing_no_git_loads_saved_architecture_and_keeps_it(self):
        info=call('init',self.repo)
        call('write',self.repo,'--document','architecture','--expected','missing',content='Existing verified architecture\n')
        seen=[]
        def planner(conn,state,pack,fixed):
            seen.append(pack)
            return plan(),{'profile':'fixture','native_id':'exact-planner'}
        result=prepare(self.runs,'Change '+str(self.repo),planner=planner)
        self.assertEqual(result['status'],'ready')
        self.assertIn('Existing verified',seen[0]['architecture']['content'])
        self.assertEqual(load(self.repo)['content'],'Existing verified architecture\n')
        self.assertEqual(result['run']['configuration']['request']['directory'],str(self.repo))
        self.assertEqual((self.repo/'main.py').read_text(),'original')
        self.assertFalse((self.repo/'.git').exists())
        self.assertFalse((self.repo/'architecture.md').exists())

    def test_missing_design_is_created_externally_but_incomplete_design_never_executes(self):
        value=plan();value['architecture']['status']='draft';value['architecture']['pending']=['Choose persistence']
        value['questions']=['Which database?']
        result=prepare(self.runs,'Change '+str(self.repo),planner=lambda *args:(value,{}))
        self.assertEqual(result['status'],'needs_input')
        self.assertEqual(load(self.repo)['status'],'draft')
        with patch('agent_hub.engine.runs.Runner.run',side_effect=AssertionError('must not execute')):
            blocked=self.runs.execute(result['run']['id'])
        self.assertEqual(blocked['status'],'waiting_human')
        self.assertEqual((self.repo/'main.py').read_text(),'original')

    def test_ambiguous_path_new_default_and_injection_are_not_shell(self):
        with patch('agent_hub.engine.requests.native_plan',side_effect=AssertionError('No project selected')):
            self.assertEqual(prepare(self.runs,'create a repository')['status'],'needs_input')
            self.assertEqual(prepare(self.runs,'modify /etc',directory='/etc')['status'],'needs_input')
            self.assertEqual(prepare(self.runs,'modify private state',directory=str(self.home/'.codex'))['status'],'needs_input')
        root,questions=resolve('crea un proyecto nuevo',directory=str(self.home/'Documents/Programacion/new-app'))
        self.assertTrue(root.is_dir());self.assertFalse((root/'.git').exists())
        named,questions=resolve('crea un proyecto llamado inventory-api con Python')
        self.assertEqual(named,self.home/'Documents/Programacion/inventory-api')
        self.assertEqual(resolve('cambia "'+str(self.repo)+'" y "'+str(named)+'"')[0],None)
        malicious=plan();malicious['files']=['../escape']
        with self.assertRaises(ValueError):validate(malicious)
        malicious=plan();malicious['files']=['.env']
        with self.assertRaises(ValueError):validate(malicious)

    @unittest.skipUnless(shutil.which('bwrap'),'OS sandbox required')
    def test_full_no_git_change_with_architecture_checks_independent_review_and_apply(self):
        profiles=Profiles(self.cache.conn)
        profiles.register({'id':'worker','provider':'fixture','command':[sys.executable,'-c',
            "import json,sys;from pathlib import Path;raw=sys.stdin.read();p=json.loads(raw[raw.index('{'):]);assert p['architecture']['status']=='defined' and p['task_design']['status']=='defined';Path('main.py').write_text('changed');print(json.dumps({'text':'done'}))"]})
        profiles.register({'id':'reviewer','provider':'fixture','roles':['reviewer'],'permissions':{'filesystem':'read'},
                           'command':[sys.executable,'-c',"import json;print(json.dumps({'text':json.dumps({'verdict':'approve','issues':[]})}))"]})
        prepared=prepare(self.runs,'Change '+str(self.repo),planner=lambda *args:(plan(),{}))
        result=execute_ready(self.runs,prepared)
        self.assertEqual(result['status'],'done',result)
        self.assertEqual((self.repo/'main.py').read_text(),'changed')
        self.assertEqual(result['applied'][0]['files'],['main.py'])
        executions=self.cache.conn.execute('SELECT COUNT(*) FROM executions').fetchone()[0]
        repeated=execute_ready(self.runs,prepared)
        self.assertEqual(repeated['status'],'done')
        self.assertEqual(self.cache.conn.execute('SELECT COUNT(*) FROM executions').fetchone()[0],executions)
        self.assertFalse((self.repo/'.git').exists())
        self.assertFalse((self.repo/'architecture.md').exists())

    def test_clarification_reuses_directory_memory_and_supersedes_unstarted_plan(self):
        draft=plan();draft['questions']=['Which database?'];draft['architecture']['status']='draft'
        first=prepare(self.runs,'Change '+str(self.repo),planner=lambda *a:(draft,{}))
        second=prepare(self.runs,'Use an in-memory fixture',continue_run=first['run']['id'],planner=lambda *a:(plan(),{}))
        self.assertEqual(second['status'],'ready')
        self.assertEqual(self.runs.get(first['run']['id'])['status'],'cancelled')
        self.assertEqual(load(self.repo)['status'],'defined')
        self.assertEqual(second['run']['configuration']['request']['directory'],str(self.repo))
        self.assertIn('Aclaración',second['run']['tasks'][0]['contract']['objective'])

    @unittest.skipUnless(shutil.which('bwrap'),'OS sandbox required')
    def test_native_planner_reads_context_but_cannot_write_source(self):
        from agent_hub.agents import Agent
        from agent_hub.engine.requests import native_plan,project_pack
        fake=self.repo/'native_fixture.py';value=plan()
        fake.write_text('import json,sys\nfrom pathlib import Path\nassert "read-only" in sys.argv\ntry:\n Path("main.py").write_text("not allowed")\n raise RuntimeError("source writable")\nexcept OSError as error:\n assert error.errno in (13,30)\nraw=sys.stdin.read();assert "directory" in raw and "software-architect" in raw\nprint(json.dumps({"type":"thread.started","thread_id":"native-planner"}))\nprint(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":'+repr(json.dumps(value))+'}}))\n')
        native_home=self.home/'.codex';native_home.mkdir()
        agent=Agent('codex','Codex','codex',str(native_home),[sys.executable,str(fake)])
        Profiles(self.cache.conn).register({'id':'codex','provider':'codex','adapter':'codex','format':'codex-jsonl','command':[sys.executable,str(fake)]})
        with patch('agent_hub.agents.registry',return_value=[agent]):
            result,evidence=native_plan(self.cache.conn,self.root/'state',project_pack(self.repo,'Change fixture'))
        self.assertEqual(result['status'],'ready')
        self.assertEqual(evidence['native_id'],'native-planner')
        self.assertEqual((self.repo/'main.py').read_text(),'original')

    def test_snapshot_cannot_introduce_git_or_copy_secret_configuration(self):
        (self.repo/'Web.config').write_text('DO_NOT_READ_OR_COPY')
        (self.repo/'.env').write_text('DO_NOT_READ_OR_COPY')
        prepared=prepare(self.runs,'Change '+str(self.repo),planner=lambda *a:(plan(),{}))
        task=prepared['run']['tasks'][0]['id'];spaces=Workspaces(self.cache.conn,self.root/'state')
        workspace=spaces.create_directory(task,self.repo);directory=Path(workspace['path'])
        self.assertFalse((directory/'Web.config').exists());self.assertFalse((directory/'.env').exists())
        (directory/'.git').mkdir()
        with self.assertRaisesRegex(ValueError,'sin autorización'):spaces.get(task)

    @unittest.skipUnless(shutil.which('bwrap'),'OS sandbox required')
    def test_architecture_changed_during_execution_prevents_applying_source(self):
        profiles=Profiles(self.cache.conn)
        profiles.register({'id':'worker','provider':'fixture','command':[sys.executable,'-c',"import json;from pathlib import Path;Path('main.py').write_text('changed');print(json.dumps({'text':'done'}))"]})
        profiles.register({'id':'reviewer','provider':'fixture','roles':['reviewer'],'command':[sys.executable,'-c',"import json;print(json.dumps({'text':json.dumps({'verdict':'approve','issues':[]})}))"]})
        prepared=prepare(self.runs,'Change '+str(self.repo),planner=lambda *a:(plan(),{}))
        original=self.runs.execute
        def mutate(ident):
            result=original(ident)
            current=load(self.repo)
            call('write',self.repo,'--document','architecture','--expected',current['revision'],'--status','draft',content='A concurrent architecture decision is pending.\n')
            return result
        with patch.object(self.runs,'execute',side_effect=mutate):
            result=execute_ready(self.runs,prepared)
        self.assertEqual(result['status'],'waiting_human')
        self.assertEqual((self.repo/'main.py').read_text(),'original')
        self.assertIn('arquitectura cambió',result['questions'][0])

    def test_concurrent_user_change_is_never_overwritten(self):
        prepared=prepare(self.runs,'Change '+str(self.repo),planner=lambda *args:(plan(),{}))
        task=prepared['run']['tasks'][0]['id'];spaces=Workspaces(self.cache.conn,self.root/'state')
        workspace=spaces.create_directory(task,self.repo)
        (Path(workspace['path'])/'main.py').write_text('agent')
        (self.repo/'main.py').write_text('user change')
        from agent_hub.engine.directory_workspace import apply
        with self.assertRaisesRegex(ValueError,'original cambió'):
            apply(spaces.baseline(task),workspace['path'],self.repo)
        self.assertEqual((self.repo/'main.py').read_text(),'user change')
