"""Confirmed-idle cleanup for native CLIs launched by Agent Hub only."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys
import time
import uuid

from .engine.process import token

BUSY = {'UserPromptSubmit', 'PreToolUse', 'PermissionRequest', 'PreInvocation', 'SubagentStart',
        'beforeSubmitPrompt', 'preToolUse', 'beforeShellExecution', 'beforeMCPExecution', 'subagentStart'}
IDLE = {'Stop', 'stop', 'SessionStart', 'sessionStart'}


def state_dir():
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state')))/'agent-hub'


def config_path():
    return Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config')))/'agent-hub/idle.json'


def minutes():
    try:
        value = json.loads(config_path().read_text()).get('minutes', 0)
        return value if type(value) is int and 1 <= value <= 1440 else 0
    except (OSError, ValueError, AttributeError):
        return 0


def database(state=None):
    path = Path(state or state_dir())/'idle.sqlite'
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn = sqlite3.connect(path, timeout=3)
    path.chmod(0o600)
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE IF NOT EXISTS launches (id TEXT PRIMARY KEY, agent TEXT, session TEXT, cwd TEXT, pid INTEGER, token TEXT, status TEXT, idle_since REAL)')
    return conn


def register(conn, agent, session, cwd, pid):
    ident = uuid.uuid4().hex
    with conn:
        conn.execute('INSERT INTO launches VALUES (?,?,?,?,?,?,?,?)',
                     (ident, agent, session, str(Path(cwd).resolve()), pid, token(pid), 'unknown', None))
    return ident


def observe(agent, event, payload, state=None, owner=None, now=None):
    """Retain only identity/lifecycle metadata, never prompts, tool results or auth."""
    from .agents import check_id
    session = payload.get('conversation_id') or payload.get('session_id') or payload.get('conversationId')
    try:
        check_id(session)
    except ValueError:
        return False
    with closing(database(state)) as conn:
        if owner:
            rows = conn.execute('SELECT * FROM launches WHERE id=? AND agent=?', (owner, agent)).fetchall()
        else:
            rows = conn.execute('SELECT * FROM launches WHERE agent=? AND session=?', (agent, session)).fetchall()
        rows = [r for r in rows if r['token'] and token(r['pid']) == r['token']]
        if len(rows) != 1:
            return False  # Never guess a new session from cwd or shared-daemon ancestry.
        row = rows[0]
        if row['session'] and row['session'] != session:
            return False
        if event in BUSY:
            status, since = 'busy', None
        elif event in IDLE:
            # A resumed SessionStart during compaction is not proof the task ended.
            if event in ('SessionStart', 'sessionStart') and row['status'] == 'busy':
                return False
            status, since = 'idle', time.monotonic() if now is None else now
        else:
            return False
        with conn:
            conn.execute('UPDATE launches SET session=?,status=?,idle_since=? WHERE id=?',
                         (session, status, since, row['id']))
    return True


def expired(conn, ident, seconds, now=None):
    row = conn.execute('SELECT * FROM launches WHERE id=?', (ident,)).fetchone()
    current = time.monotonic() if now is None else now
    return bool(row and row['session'] and row['status'] == 'idle' and row['idle_since'] is not None
                and current-row['idle_since'] >= seconds and row['token'] and token(row['pid']) == row['token'])


def launch(agent, argv, directory, session, delay, env=None):
    with closing(database()) as conn:
        # The child inherits its terminal and native approvals unchanged.
        # A tiny gate prevents SessionStart beating registration.
        read_fd, write_fd = os.pipe()
        gate = 'import os,sys; fd=int(sys.argv[1]); os.read(fd,1); os.close(fd); os.execvpe(sys.argv[2],sys.argv[2:],os.environ)'
        ident = uuid.uuid4().hex
        environment = {**(os.environ if env is None else env), 'AGENT_HUB_LAUNCH_ID': ident}
        if agent.container and argv[:2] == ['podman', 'exec']:
            argv = [*argv[:2], '--env', 'AGENT_HUB_LAUNCH_ID='+ident, *argv[2:]]
        try:
            process = subprocess.Popen([sys.executable, '-c', gate, str(read_fd), *argv], cwd=directory,
                                       pass_fds=(read_fd,), env=environment)
            with conn:
                conn.execute('INSERT INTO launches VALUES (?,?,?,?,?,?,?,?)',
                             (ident, agent.id, session, str(directory), process.pid, token(process.pid), 'unknown', None))
            os.write(write_fd, b'1')
        finally:
            os.close(read_fd)
            os.close(write_fd)
        try:
            while process.poll() is None:
                if expired(conn, ident, delay*60):
                    # Only this unreaped child can receive SIGTERM. Never killpg,
                    # SIGKILL or shared services; an active/unknown task stays alive.
                    process.terminate()
                    process.wait()
                    print('\nAgent Hub: sesión guardada; cerrada tras '+str(delay)+' minutos sin tarea.', file=sys.stderr)
                    return 0
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
            return process.returncode
        except KeyboardInterrupt:
            # Native CLI receives terminal Ctrl-C as usual; keep waiting if alive.
            return process.wait()
        finally:
            with conn:
                conn.execute('DELETE FROM launches WHERE id=?', (ident,))


def install_hooks(home=None):
    from .manager import private_json
    home = Path(home or Path.home())
    executable = str(Path(__file__).resolve().parents[1]/'bin/agent-hub')
    saved = []
    for agent, path, events in (
        ('codex', Path(os.environ.get('CODEX_HOME', str(home/'.codex')))/'hooks.json',
         ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PermissionRequest', 'SubagentStart', 'Stop')),
        ('cursor', home/'.cursor/hooks.json',
         ('sessionStart', 'beforeSubmitPrompt', 'preToolUse', 'subagentStart', 'stop')),
        ('antigravity', home/'.gemini/config/hooks.json',
         ('SessionStart', 'PreToolUse', 'PreInvocation', 'Stop')),
    ):
        data = json.loads(path.read_text()) if path.exists() else {}
        before = json.dumps(data, sort_keys=True)
        if agent == 'antigravity':
            hooks = data.setdefault('agent-hub-idle', {})
        else:
            hooks = data.setdefault('hooks', {})
        for event in events:
            command = shlex.join([executable, 'idle', 'observe', '--agent', agent, '--event', event])
            handler = {'type': 'command', 'command': command, 'timeout': 5}
            if agent == 'cursor':
                entry = {'command': command}
            elif agent == 'codex' or event == 'PreToolUse':
                entry = {'hooks': [handler]}
                if event == 'PreToolUse':
                    entry['matcher'] = '*'
            else:
                entry = handler
            entries = hooks.setdefault(event, [])
            if entry not in entries:
                entries.append(entry)
        if agent == 'cursor':
            data.setdefault('version', 1)
        if json.dumps(data, sort_keys=True) != before:
            if path.exists():
                private_json(state_dir()/'backups'/('hooks-'+agent+'-'+uuid.uuid4().hex+'.json'), json.loads(path.read_text()))
            private_json(path, data)
        saved.append(str(path))
    return saved


def install_hermes_plugin(agent):
    """Public Hermes lifecycle plugin in its existing container; no Coucou edits."""
    root = str(Path(__file__).resolve().parents[1])
    mapped = agent.map_path(root)
    state = agent.map_path(state_dir().parent)
    config = agent.map_path(config_path())
    code = f'''import os,subprocess,json,threading,time,signal

def register(ctx):
    active=set()
    lock=threading.Lock()
    idle_since=None

    def timeout_seconds():
        try:
            with open({config!r}) as source:value=json.load(source).get('minutes',0)
            return value*60 if type(value) is int and 1<=value<=1440 else 0
        except (OSError,ValueError,AttributeError):return 0

    def emit(event, **kwargs):
        nonlocal idle_since
        session=kwargs.get('session_id')
        if not isinstance(session,str) or not session:return
        if event in ('SessionStart','UserPromptSubmit','PreToolUse'):
            with lock:active.add(session);idle_since=None
        elif event=='Stop':
            with lock:
                active.discard(session)
                if not active:idle_since=time.monotonic()
        # Lifecycle metadata only; never forward messages, prompts, tools or credentials.
        try:
            subprocess.run(['python3','-B',{mapped!r}+'/bin/agent-hub','idle','observe',
                            '--agent',{agent.id!r},'--event',event],
                           input=json.dumps({{'session_id':session}}),text=True,
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3,
                           env={{**os.environ,'XDG_STATE_HOME':{state!r}}},check=False)
        except (OSError,subprocess.TimeoutExpired):pass

    def reap_when_idle():
        while True:
            time.sleep(1)
            with lock:
                since=idle_since
                busy=bool(active)
            delay=timeout_seconds()
            if delay and since is not None and not busy and time.monotonic()-since>=delay:
                # The plugin runs inside Hermes, including launches outside Hub.
                # End only this native process; never search by process name.
                os.kill(os.getpid(),signal.SIGTERM)
                return

    threading.Thread(target=reap_when_idle,daemon=True,name='agent-hub-idle').start()
    ctx.register_hook('on_session_start',lambda **kw:emit('SessionStart',**kw))
    ctx.register_hook('pre_llm_call',lambda **kw:emit('UserPromptSubmit',**kw))
    ctx.register_hook('pre_tool_call',lambda **kw:emit('PreToolUse',**kw))
    # on_session_end is emitted by the finalizer once run_conversation finishes.
    # post_llm_call can occur before tools, so it is deliberately not an idle signal.
    ctx.register_hook('on_session_end',lambda **kw:emit('Stop',**kw))
'''
    manifest = 'name: agent-hub-idle\nversion: 1.0.0\ndescription: Confirmed idle lifecycle for Agent Hub\nprovides_tools: []\nprovides_hooks:\n  - on_session_start\n  - pre_llm_call\n  - pre_tool_call\n  - on_session_end\n'
    installer = "import json,sys;from pathlib import Path;p=json.load(sys.stdin);d=Path(p['home'])/'plugins/agent-hub-idle';d.mkdir(parents=True,exist_ok=True);(d/'__init__.py').write_text(p['code']);(d/'plugin.yaml').write_text(p['manifest'])"
    subprocess.run(['podman','exec','-i',agent.container,'python3','-c',installer],
                   input=json.dumps({'home':agent.home,'code':code,'manifest':manifest}),text=True,check=True,timeout=10)
    subprocess.run(['podman','exec',agent.container,'/usr/local/bin/hermes','plugins','enable','agent-hub-idle'],
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, check=True, timeout=15)
    return agent.container+':'+agent.home+'/plugins/agent-hub-idle'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    configure = sub.add_parser('configure')
    configure.add_argument('--minutes', type=int, required=True)
    configure.add_argument('--install-hooks', action='store_true')
    sub.add_parser('status')
    hook = sub.add_parser('observe')
    hook.add_argument('--agent', required=True)
    hook.add_argument('--event', required=True)
    args = parser.parse_args(argv)
    if args.action == 'observe':
        try:
            payload = json.loads(sys.stdin.read(1024*1024))
            if isinstance(payload, dict):
                observe(args.agent, args.event, payload, owner=os.environ.get('AGENT_HUB_LAUNCH_ID'))
        except (OSError, ValueError, sqlite3.Error):
            pass  # Observational, never block a native task or approval.
        print('{}')
        return 0
    if args.action == 'configure':
        if not 0 <= args.minutes <= 1440:
            parser.error('minutes debe estar entre 0 (desactivado) y 1440')
        from .manager import private_json
        hooks = install_hooks() if args.install_hooks else []
        if args.install_hooks:
            from .agents import registry
            for agent in registry():
                if agent.kind == 'hermes' and agent.container:
                    hooks.append(install_hermes_plugin(agent))
        private_json(config_path(), {'version': 1, 'minutes': args.minutes})
        print(json.dumps({'minutes': args.minutes, 'hooks': hooks}))
        return 0
    with closing(database()) as conn:
        rows = [dict(r) for r in conn.execute('SELECT agent,session,pid,status FROM launches')]
    print(json.dumps({'minutes': minutes(), 'launches': rows}))
    return 0
