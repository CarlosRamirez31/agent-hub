"""Antigravity public stream/observation contracts; no models or native storage."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch
from agent_hub.antigravity import run,record
from agent_hub.agents import Agent
from agent_hub.native import read_index,read_messages
from agent_hub.cache import Cache
from agent_hub.engine.bootstrap import initialize
from agent_hub.engine.profiles import Profiles
from agent_hub.engine.execution import parse_result

NATIVE='0A51AA8B-32A4-4334-8460-BEA4E627D3D5'
class AntigravityTests(unittest.TestCase):
    def command(self,root,native=NATIVE):
        script=('import json,sys;from pathlib import Path;'
                'print(json.dumps({"event":"init","conversation_id":'+repr(native)+'}),flush=True);'
                'prompt=sys.stdin.read();Path('+repr(str(root/'received'))+').write_text(prompt);'
                'print(json.dumps({"event":"result","result":{"conversation_id":'+repr(native)+',"status":"SUCCESS","response":"reply","usage":{"total_tokens":2}}}),flush=True)')
        return [sys.executable,'-c',script]
    def test_init_is_verified_before_prompt_and_no_latest_or_bypass(self):
        with tempfile.TemporaryDirectory(prefix="agy ñ ' $() ") as directory:
            root=Path(directory);command=self.command(root)
            result=run('query 日本語 ; $(no)',NATIVE,command=command)
            self.assertEqual(result['native_id'],NATIVE)
            self.assertEqual(result['text'],'reply');self.assertEqual(result['tokens'],2)
            self.assertEqual(json.loads((root/'received').read_text()),{'event':'user','message':{'content':'query 日本語 ; $(no)'}})
    def test_mismatched_init_sends_no_prompt_and_wrong_workspace_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with self.assertRaisesRegex(ValueError,'otra conversación'):
                run('MUST_NOT_SEND',NATIVE,command=self.command(root,str(uuid.uuid4())))
            self.assertFalse((root/'received').exists() and (root/'received').read_text())
            command=[sys.executable,'-c','import json,time;print(json.dumps({"event":"init","conversation_id":"'+NATIVE+'","init":{"cwd":"/wrong-workspace"}}),flush=True);time.sleep(10)']
            with self.assertRaisesRegex(ValueError,'otro workspace'):run('MUST_NOT_SEND',command=command)
    def test_probe_never_sends_a_model_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run('',NATIVE,probe=True,command=self.command(root))
            self.assertEqual((root/'received').read_text(),'')
    def test_auth_error_and_timeout_fail_closed(self):
        with self.assertRaisesRegex(ValueError,'authentication required'):
            run('secret',command=[sys.executable,'-c','import sys;print("authentication required",file=sys.stderr);sys.exit(1)'])
        with self.assertRaisesRegex(ValueError,'authentication required'):
            run('secret',command=[sys.executable,'-c','import json;print(json.dumps({"event":"result","result":{"status":"ERROR","error":"authentication required"}}))'])
        with self.assertRaisesRegex(ValueError,'tiempo límite'):
            run('secret',timeout=.1,command=[sys.executable,'-c','import time;time.sleep(20)'])
    def test_observer_keeps_exact_id_and_only_own_visible_index(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,XDG_STATE_HOME=directory):
            root=Path(directory);route=record(NATIVE,str(root),[{'role':'user','text':'hello'},{'role':'assistant','text':'reply'}],transcript='/not-read/private.sqlite')
            self.assertEqual(route['idMessage'],NATIVE)
            home=root/'agent-hub/adapters/antigravity'
            chats,projects=read_index('antigravity',home)
            self.assertEqual(chats[0].id,NATIVE)
            self.assertEqual(read_messages('antigravity',home,NATIVE),[{'role':'user','text':'hello'},{'role':'assistant','text':'reply'}])
            self.assertEqual((home/'index.json').stat().st_mode&0o777,0o600)
            other=root/'other';other.mkdir()
            with self.assertRaisesRegex(ValueError,'otro workspace'):record(NATIVE,str(other))
    def test_profiles_use_guarded_public_driver_and_preserve_review_schema(self):
        cache=Cache(':memory:')
        try:
            agent=Agent('antigravity','Antigravity CLI','antigravity','/fixture',['agy'],['--conversation','{session}'])
            self.assertEqual(initialize(cache.conn,[agent])['created'],['antigravity','antigravity-reviewer'])
            for row in Profiles(cache.conn).list():
                self.assertEqual(row['command'][:3],['agent-hub','agy-run','--no-record'])
                self.assertIn('--conversation',row['resume_command'])
                self.assertNotIn('--dangerously-skip-permissions',row['command'])
            self.assertIn('--schema',Profiles(cache.conn).get('antigravity-reviewer')['command'])
            value=parse_result({'format':'json'},json.dumps({'text':'','native_id':NATIVE,'error':'quota'}))
            self.assertEqual(value['native_id'],NATIVE)
        finally:cache.close()
