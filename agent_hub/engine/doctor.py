"""Explicit installation probes. --help and true never invoke a model."""
import shutil
import subprocess
from .profiles import Profiles
from ..migrations import SCHEMA_VERSION


def doctor(conn):
    profiles=Profiles(conn)
    checks={'git':bool(shutil.which('git')),'bubblewrap':bool(shutil.which('bwrap')),
            'schema':conn.execute('PRAGMA user_version').fetchone()[0]}
    if checks['bubblewrap']:
        result=subprocess.run(['bwrap','--die-with-parent','--unshare-pid','--unshare-ipc','--unshare-uts','--ro-bind','/','/','--proc','/proc','--unshare-net','--','/usr/bin/true'],
                              stdin=subprocess.DEVNULL,capture_output=True,timeout=10,check=False)
        checks['sandbox_works']=result.returncode==0
    else:checks['sandbox_works']=False
    details=[]
    for profile in profiles.list():
        row={'id':profile['id'],'available':profile['available'],'help_ok':False,'sandbox_works':checks['sandbox_works']}
        if profile['available']:
            command=[profile['command'][0],'--help']
            if profile.get('container'):
                prefix=['podman','exec',profile['container']['name']]
                probe=subprocess.run([*prefix,'bwrap','--die-with-parent','--unshare-pid','--unshare-ipc','--unshare-uts','--ro-bind','/','/','--ro-bind','/proc','/proc','--unshare-net','--','/usr/bin/true'],
                                     stdin=subprocess.DEVNULL,capture_output=True,timeout=10,check=False)
                row['sandbox_works']=probe.returncode==0
                command=[*prefix,*command]
            try:
                probe=subprocess.run(command,stdin=subprocess.DEVNULL,capture_output=True,timeout=15,check=False)
                row['help_ok']=probe.returncode==0
            except (OSError,subprocess.TimeoutExpired):pass
        details.append(row)
    return {'checks':checks,'profiles':details,'models_started':False,'passed':checks['git'] and checks['sandbox_works'] and checks['schema']==SCHEMA_VERSION and all(p['help_ok'] and p['sandbox_works'] for p in details if p['available'])}
