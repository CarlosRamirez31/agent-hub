"""Disposable end-to-end demonstration: real isolation, fictitious agents only."""
from pathlib import Path
import sys
import tempfile
from ..cache import Cache
from .profiles import Profiles
from .workspace import git
from .runs import Runs


def demo():
    with tempfile.TemporaryDirectory(prefix='agent-hub-demo-') as temporary:
        root=Path(temporary);repo=root/'repo';repo.mkdir()
        git(repo,'init','-q');git(repo,'config','user.name','Agent Hub Fixture')
        git(repo,'config','user.email','fixture@example.invalid');git(repo,'config','commit.gpgsign','false')
        (repo/'result.txt').write_text('base\n');git(repo,'add','result.txt');git(repo,'commit','-qm','Fictitious fixture')
        state=root/'state';cache=Cache(state/'index.sqlite')
        try:
            profiles=Profiles(cache.conn)
            profiles.register({'id':'fixture-worker','provider':'fixture','cost_class':'local',
                'command':[sys.executable,'-c','import json;from pathlib import Path;Path("result.txt").write_text("verified fixture\\n");print(json.dumps({"text":"Fictitious worker finished."}))']})
            profiles.register({'id':'fixture-reviewer','provider':'fixture','roles':['reviewer'],'cost_class':'local',
                'command':[sys.executable,'-c','print(\'{"verdict":"approve","issues":[]}\')']})
            runs=Runs(cache.conn,state)
            run=runs.create({'title':'Fictitious end-to-end demonstration','tasks':[{'key':'fixture',
                'contract':{'title':'Fictitious task','objective':'Verify isolation and quality gates without a model.',
                    'complexity':'small','scope':{'files':['result.txt']},'review':{'required':True},
                    'permissions':{'filesystem':'write'},'assignment':{'mode':'fixed','agent':'fixture-worker'}},
                'repo':str(repo),'reviewer':'fixture-reviewer',
                'checks':[[sys.executable,'-c','from pathlib import Path;assert Path("result.txt").read_text()=="verified fixture\\n"']]}]})
            result=runs.execute(run['id'])
            return {'demo':True,'status':result['status'],'models_started':False,'persistent_user_state_changed':False,
                    'tasks':[{'id':t['id'],'status':t['status']} for t in result['tasks']],
                    'original_checkout_unchanged':(repo/'result.txt').read_text()=='base\n',
                    'verifications':cache.conn.execute('SELECT COUNT(*) FROM verifications WHERE passed=1').fetchone()[0],
                    'reviews':cache.conn.execute("SELECT COUNT(*) FROM reviews WHERE verdict='approve'").fetchone()[0],
                    'errors':[r.get('error') for r in result['results'] if r.get('error')]}
        finally:
            cache.close()
