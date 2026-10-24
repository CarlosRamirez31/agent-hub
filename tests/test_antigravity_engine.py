"""Full isolated worker/reviewer flow through the real guarded driver, fake agy."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from agent_hub.cache import Cache
from agent_hub.agents import Agent
from agent_hub.engine.tasks import TaskStore
from agent_hub.engine.profiles import Profiles
from agent_hub.engine.workspace import Workspaces,git
from agent_hub.engine.execution import Runner
from agent_hub.engine.quality import Quality
from agent_hub.engine.conversations import Conversations

@unittest.skipUnless(shutil.which('bwrap'),'OS sandbox required')
class AntigravityEngineTests(unittest.TestCase):
    def test_native_driver_workspace_review_and_exact_execution_route(self):
        with tempfile.TemporaryDirectory(prefix='.agy-engine-test-',dir=Path(__file__).resolve().parents[1]) as temporary:
            root=Path(temporary);binaries=root/'bin';binaries.mkdir()
            fake=binaries/'agy'
            fake.write_text('#!'+sys.executable+'\n'+'''import json,sys,os
from pathlib import Path
review='--schema' in sys.argv or '--json-schema' in sys.argv
native='11111111-1111-4111-8111-11111111111'+('2' if review else '1')
if '--conversation' in sys.argv:native=sys.argv[sys.argv.index('--conversation')+1]
print(json.dumps({'event':'init','conversation_id':native,'init':{'cwd':os.getcwd()}}),flush=True)
query=sys.stdin.read()
if not query:sys.exit(0)
if not review:Path('file').write_text('changed')
response=json.dumps({'verdict':'approve','issues':[]}) if review else 'done'
print(json.dumps({'event':'result','result':{'conversation_id':native,'status':'SUCCESS','response':response,'usage':{'total_tokens':2}}}),flush=True)
''');fake.chmod(0o755)
            with patch.dict(os.environ,PATH=str(binaries)+os.pathsep+os.environ['PATH']):
                state=root/'state';cache=Cache(state/'index.sqlite')
                try:
                    repo=root/'repo';repo.mkdir();git(repo,'init','-q');git(repo,'config','user.email','fixture@example.invalid');git(repo,'config','user.name','Fixture')
                    (repo/'file').write_text('base');git(repo,'add','.');git(repo,'commit','-qm','base')
                    tasks=TaskStore(cache.conn);profiles=Profiles(cache.conn)
                    for role in ('worker','reviewer'):
                        command=['agent-hub','agy-run','--no-record','--json']
                        if role=='reviewer':command+=['--schema',str(Path(__file__).resolve().parents[1]/'docs/review.schema.json')]
                        profiles.register({'id':role,'provider':'antigravity','adapter':'antigravity','roles':[role],'command':command,'resume_command':command+['--conversation','{session}']})
                    task=tasks.create({'title':'fixture','objective':'change file','complexity':'small','scope':{'files':['file']},'permissions':{'filesystem':'write'},'assignment':{'mode':'fixed','agent':'worker'}})
                    workspace=Workspaces(cache.conn,state).create(task.id,repo);tasks.status(task.id,'ready')
                    runner=Runner(cache.conn,state);worker=runner.run(task.id)
                    self.assertEqual(worker['status'],'completed',worker)
                    self.assertEqual((repo/'file').read_text(),'base')
                    self.assertEqual((Path(workspace['path'])/'file').read_text(),'changed')
                    quality=Quality(cache.conn,state)
                    self.assertTrue(quality.verify(task.id,[[sys.executable,'-c','pass']])['passed'])
                    review=runner.run(task.id,'reviewer','reviewer','code')
                    self.assertEqual(review['status'],'completed',review)
                    self.assertTrue(quality.gate(task.id)['passed'])
                    adapter=Agent('antigravity','Antigravity CLI','antigravity',str(state/'adapters/antigravity'),['agy'],['--conversation','{session}'])
                    with patch('agent_hub.agents.registry',return_value=[adapter]):
                        route=Conversations(cache.conn,state).route('EXEC-001')['route']
                        self.assertEqual(route['idMessage'],worker['result']['native_id'])
                        self.assertEqual(route['agente'],'antigravity')
                finally:cache.close()
