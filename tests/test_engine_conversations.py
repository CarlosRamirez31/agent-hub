import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from agent_hub.cache import Cache
from agent_hub.agents import Agent
from agent_hub.engine.tasks import TaskStore
from agent_hub.engine.profiles import Profiles
from agent_hub.engine.conversations import Conversations

class ExecutionConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.state=self.root/'state'
        self.cache=Cache(self.state/'index.sqlite');self.addCleanup(self.cache.close)
        self.home=self.root/'native';self.home.mkdir();self.workspace=self.root/'project';self.workspace.mkdir()
        self.native='native-exact'
        self.seed()
        self.agent=Agent('fixture-native','Fixture','normalized',str(self.home),[sys.executable],['{session}'])
        self.profile={'id':'worker','provider':'fixture','adapter':'fixture-native','command':[sys.executable]}
        Profiles(self.cache.conn).register(self.profile)
        task=TaskStore(self.cache.conn).create({'title':'test','objective':'test'})
        self.cache.conn.execute('INSERT INTO executions(task,profile,role,status,started,finished,result) VALUES (?,?,?,?,?,?,?)',
            (1,'worker','worker','completed',1,2,json.dumps({'text':'response','native_id':self.native,'profile_snapshot':self.profile})))
        self.cache.conn.commit()
        self.conversations=Conversations(self.cache.conn,self.state)
    def seed(self,deleted=False):
        (self.home/'index.json').write_text(json.dumps({'version':1,'projects':[{'id':'opaque project','name':'Project','roots':[str(self.workspace)]}],
            'conversations':[] if deleted else [{'id':self.native,'title':'Title','cwd':str(self.workspace),'updated':1,'project_id':'opaque project'}]}))
    def test_route_persists_full_descriptor_and_uses_execution_snapshot(self):
        with patch('agent_hub.agents.registry',return_value=[self.agent]):
            value=self.conversations.route('EXEC-001')
            self.assertEqual(value['route'],{'version':1,'agente':'fixture-native','idCarpeta':'opaque project','idMessage':self.native})
            # Later editing the profile must not reinterpret an earlier execution.
            Profiles(self.cache.conn).register({**self.profile,'adapter':'different'})
            self.assertEqual(self.conversations.route('EXEC-001')['route'],value['route'])
            self.assertEqual(self.conversations.get('EXEC-001')['result']['route'],value['route'])
    def test_deleted_and_running_sessions_do_not_fall_back_or_recreate(self):
        with patch('agent_hub.agents.registry',return_value=[self.agent]):
            self.conversations.route('EXEC-001');self.seed(deleted=True)
            with self.assertRaises(ValueError):self.conversations.route('EXEC-001')
        self.cache.conn.execute("UPDATE executions SET status='running'");self.cache.conn.commit()
        with self.assertRaisesRegex(ValueError,'activa'):self.conversations.route('EXEC-001')
    def test_binding_requires_exact_existing_native_id(self):
        self.cache.conn.execute('UPDATE executions SET result=?',(json.dumps({'error':'unknown start','profile_snapshot':self.profile}),));self.cache.conn.commit()
        with patch('agent_hub.agents.registry',return_value=[self.agent]):
            with self.assertRaises(ValueError):self.conversations.bind('EXEC-001','missing-native')
            self.assertEqual(self.conversations.bind('EXEC-001',self.native)['result']['native_id'],self.native)
            with self.assertRaises(ValueError):self.conversations.bind('EXEC-001','other-native')

if __name__=='__main__':unittest.main()
