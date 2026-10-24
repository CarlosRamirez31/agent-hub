import json
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from agent_hub.cache import Cache
from agent_hub.engine.tasks import TaskStore
from agent_hub.engine.tui import Dashboard
from agent_hub.engine.bootstrap import initialize
from agent_hub.engine.profiles import Profiles
from agent_hub.agents import Agent

class Screen:
    def __init__(self,keys):self.keys=iter(keys);self.frames=[]
    def getmaxyx(self):return (28,120)
    def keypad(self,*args):pass
    def erase(self):pass
    def refresh(self):pass
    def addnstr(self,*args):self.frames.append(args[2])
    def move(self,*args):pass
    def clrtoeol(self):pass
    def get_wch(self):return next(self.keys)

class DashboardTests(unittest.TestCase):
    def test_vim_navigation_create_and_detail_do_not_launch_models(self):
        cache=Cache(':memory:')
        try:
            screen=Screen(['n',*'Fixture','\n','\n','\x1b','h','l','q'])
            with patch('curses.has_colors',return_value=False),patch('subprocess.Popen',side_effect=AssertionError('No model')):
                dashboard=Dashboard(screen,cache,Path('.'),demo=True);dashboard.run()
            self.assertEqual(TaskStore(cache.conn).list()[0].contract['title'],'Fixture')
            self.assertEqual(dashboard.tab,3)
            self.assertTrue(any('Fixture' in frame for frame in screen.frames))
        finally:cache.close()
    def test_native_bootstrap_preserves_custom_profiles_and_auth(self):
        cache=Cache(':memory:')
        try:
            profiles=Profiles(cache.conn)
            profiles.register({'id':'codex','provider':'codex','model':'custom-model',
                               'command':[sys.executable,'--model','{model}']})
            fake=Agent('codex','Codex','codex','/does/not/read', ['codex'])
            with patch('subprocess.Popen',side_effect=AssertionError('No native process')):
                first=initialize(cache.conn,[fake]);second=initialize(cache.conn,[fake])
            self.assertIn('codex',first['preserved'])
            self.assertEqual(first['created'],['codex-reviewer'])
            self.assertEqual(second['created'],[])
            self.assertEqual(profiles.get('codex')['model'],'custom-model')
            self.assertFalse(first['models_started'])
        finally:cache.close()

if __name__=='__main__':unittest.main()
