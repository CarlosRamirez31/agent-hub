"""Gemini's documented CLI/JSON contracts, entirely fictitious sessions."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from agent_hub.agents import Agent
from agent_hub.cache import Cache
from agent_hub.engine.bootstrap import initialize
from agent_hub.engine.execution import parse_result
from agent_hub.engine.profiles import Profiles
from agent_hub.manager import Manager

class GeminiTests(unittest.TestCase):
    def test_stream_chunks_preserve_answer_and_structured_review(self):
        events=[{'type':'init','session_id':'gemini-exact'},
                {'type':'message','role':'user','content':'never export'},
                {'type':'tool_result','output':'never export'},
                {'type':'message','role':'assistant','content':'{"verdict":','delta':True},
                {'type':'message','role':'assistant','content':'"approve","issues":[]}','delta':True},
                {'type':'result','status':'success','stats':{'total_tokens':42}}]
        result=parse_result({'format':'gemini-jsonl'},'\n'.join(map(json.dumps,events)))
        self.assertEqual(json.loads(result['text']),{'verdict':'approve','issues':[]})
        self.assertEqual(result['native_id'],'gemini-exact')
        self.assertEqual(result['tokens'],42)
        self.assertNotIn('never export',json.dumps(result))
        events[-1]={'type':'result','status':'error','error':{'message':'quota'}}
        result=parse_result({'format':'gemini-jsonl'},'\n'.join(map(json.dumps,events)))
        self.assertEqual(result['native_id'],'gemini-exact');self.assertIn('quota',result['error'])
    def test_bootstrap_registers_worker_and_reviewer_without_model_call(self):
        with CacheMemory() as cache:
            agent=Agent('gemini','Gemini CLI','gemini','/fixture/gemini',['gemini'],['--resume','{session}'])
            self.assertEqual(initialize(cache.conn,[agent])['created'],['gemini','gemini-reviewer'])
            profiles=Profiles(cache.conn)
            for ident in ('gemini','gemini-reviewer'):
                p=profiles.get(ident)
                self.assertEqual(p['adapter'],'gemini');self.assertEqual(p['format'],'gemini-jsonl')
                self.assertEqual(p['resume_command'][-2:],['--resume','{session}'])
                self.assertNotIn('--yolo',p['command']);self.assertNotIn('--skip-trust',p['command'])
            self.assertEqual(initialize(cache.conn,[agent])['created'],[])
    def test_multiple_sessions_same_project_route_resumes_only_selected(self):
        with tempfile.TemporaryDirectory(prefix="Gemini 日本語 ' $() ") as directory:
            root=Path(directory);home=root/'gemini';project=root/'project';project.mkdir()
            chats=home/'tmp'/'project-slug'/'chats';chats.mkdir(parents=True)
            (home/'projects.json').write_text(json.dumps({'projects':{str(project):'project-slug'}}))
            for ident in ('exact-first','different-newer'):
                (chats/('session-'+ident+'.json')).write_text(json.dumps({'sessionId':ident,'lastUpdated':'2026-10-24T00:00:00Z','messages':[{'type':'user','content':ident}]}))
            agent=Agent('gemini','Gemini CLI','gemini',str(home),[sys.executable],['--resume','{session}'])
            manager=Manager([agent],root/'state')
            try:
                manager.sync(['gemini']);sessions,projects=manager.snapshot('gemini')
                selected=next(c for c in sessions if c.id=='exact-first')
                route=manager.route('gemini',selected,projects)
                self.assertEqual(route['idMessage'],'exact-first')
                _,chat=manager.resolve(route)
                self.assertEqual(agent.argv(chat.cwd,chat.id),[sys.executable,'--resume','exact-first'])
                (chats/'session-exact-first.json').unlink();manager.sync(['gemini'])
                with self.assertRaises(ValueError):manager.resolve(route)
            finally:manager.close()

class CacheMemory:
    def __enter__(self):self.cache=Cache(':memory:');return self.cache
    def __exit__(self,*args):self.cache.close()
