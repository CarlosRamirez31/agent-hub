"""Opt-in JSON control plane for external clients; no TUI shortcuts are replaced."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

from ..cache import Cache
from .cli import read_contract, clean
from .tasks import TaskStore, number
from .profiles import Profiles
from .workspace import Workspaces, git
from .policy import Policies
from .skills import Skills
from .quality import Quality
from .context import Contexts
from .routing import Router, classify
from .execution import Runner
from .runs import Runs, run_number


def parser():
    root=argparse.ArgumentParser(prog='agent-hub work',description='Control local de ejecución. Operaciones explícitas; salida JSON.')
    root.add_argument('--json',action='store_true')
    common=argparse.ArgumentParser(add_help=False)
    common.add_argument('--json',action='store_true',default=argparse.SUPPRESS)
    groups=root.add_subparsers(dest='group',required=True)
    groups.add_parser('demo',parents=[common],help='probar worktree, worker ficticio, checks y review sin modelos ni estado persistente')
    groups.add_parser('doctor',parents=[common],help='probar binarios y sandbox sin iniciar modelos')
    groups.add_parser('tui',parents=[common],help='abrir el panel de tareas con navegación Vim')
    groups.add_parser('init',parents=[common],help='registrar perfiles nativos sin iniciar modelos ni cambiar policies')
    def sub(name):
        parent=groups.add_parser(name,parents=[common]);return parent.add_subparsers(dest='operation',required=True)
    def action(parent,name,ident=False):
        child=parent.add_parser(name,parents=[common])
        if ident:child.add_argument('id')
        return child
    profiles=sub('profile')
    action(profiles,'list');action(profiles,'show',True);action(profiles,'disable',True)
    action(profiles,'register').add_argument('--file',required=True)
    executions=sub('execution')
    listing=action(executions,'list');listing.add_argument('--task',required=True)
    for name in ('show','route'):action(executions,name,True)
    bind=action(executions,'bind',True);bind.add_argument('--native-id',required=True)
    opened=action(executions,'open',True);opened.add_argument('--dry-run',action='store_true')
    skills=sub('skill');action(skills,'list')
    register=action(skills,'register',True);register.add_argument('--file',required=True)
    register.add_argument('--scope',choices=('global','agent','project'),default='global');register.add_argument('--owner',default='')
    policies=sub('policy');show=action(policies,'show');show.add_argument('--id',default='default')
    put=action(policies,'set');put.add_argument('--id',default='default');put.add_argument('--file',required=True)
    spaces=sub('workspace')
    create=action(spaces,'create',True);create.add_argument('--repo',required=True);create.add_argument('--ref',default='HEAD')
    for name in ('show','fingerprint','diff','merge'):action(spaces,name,True)
    commit=action(spaces,'commit',True);commit.add_argument('--message',required=True)
    for name in ('execute','verify','review','approve','route','classify','context','handoff','cancel'):
        child=groups.add_parser(name,parents=[common]);child.add_argument('id')
        if name=='execute':
            child.add_argument('--new-session',action='store_true',help='crear otra conversación solo por elección explícita');child.add_argument('--profile');child.add_argument('--role',choices=('worker','reviewer'),default='worker')
            child.add_argument('--kind',choices=('code','security'),default='code')
        elif name=='verify':child.add_argument('--checks',required=True)
        elif name=='review':
            child.add_argument('--profile',required=True);child.add_argument('--report',required=True)
            child.add_argument('--kind',choices=('code','security'),default='code')
        elif name=='approve':
            child.add_argument('action');child.add_argument('--reason',required=True)
            choice=child.add_mutually_exclusive_group(required=True);choice.add_argument('--yes',action='store_true');choice.add_argument('--reject',action='store_true')
        elif name=='route':child.add_argument('--role',choices=('worker','reviewer'),default='worker')
        elif name=='context':child.add_argument('--profile',required=True);child.add_argument('--history')
        elif name=='handoff':
            child.add_argument('--from',dest='source',required=True);child.add_argument('--to',dest='target',required=True)
            child.add_argument('--reason',choices=('manual','quota_exhausted','token_limit','provider_unavailable','cli_failure'),default='manual')
            child.add_argument('--file',required=True);child.add_argument('--override-fixed',action='store_true')
    projects=sub('project-state');put=action(projects,'set',True);put.add_argument('--file',required=True);put.add_argument('--agent');show=action(projects,'show',True);show.add_argument('--agent')
    runs=sub('run')
    action(runs,'list');create=action(runs,'create');create.add_argument('--file',required=True)
    plan=action(runs,'plan');plan.add_argument('--intent',required=True);plan.add_argument('--repo');plan.add_argument('--file',dest='files',action='append',default=[]);plan.add_argument('--agent')
    request=action(runs,'request');request.add_argument('--intent',required=True);request.add_argument('--repo');request.add_argument('--agent');request.add_argument('--auto',action='store_true');request.add_argument('--continue-run')
    for name in ('show','cancel','recover','prepare'):action(runs,name,True)
    execute=action(runs,'execute',True);execute.add_argument('--parallel',type=int)
    configure=action(runs,'configure',True);configure.add_argument('--file',required=True)
    metrics=groups.add_parser('metrics',parents=[common]);metrics.add_argument('--profile');metrics.add_argument('--domain')
    events=groups.add_parser('events',parents=[common]);events.add_argument('--task');events.add_argument('--run');events.add_argument('--after',type=int,default=0);events.add_argument('--limit',type=int,default=100)
    return root


def dispatch(args, cache, state):
    conn=cache.conn;tasks=TaskStore(conn);spaces=Workspaces(conn,state)
    group=args.group
    if group=='doctor':
        from .doctor import doctor
        return doctor(conn)
    if group=='tui':
        import curses
        from .tui import Dashboard
        curses.wrapper(lambda screen:Dashboard(screen,cache,state).run())
        return {'closed':True}
    if group=='init':
        from .bootstrap import initialize
        return initialize(conn)
    if group=='profile':
        profiles=Profiles(conn)
        return (profiles.list() if args.operation=='list' else profiles.get(args.id) if args.operation=='show' else
                profiles.unregister(args.id) if args.operation=='disable' else profiles.register(read_contract(args.file)))
    if group=='execution':
        from .conversations import Conversations
        conversations=Conversations(conn,state)
        if args.operation=='list':return conversations.list(args.task)
        if args.operation=='show':return conversations.get(args.id)
        if args.operation=='route':return conversations.route(args.id)
        if args.operation=='bind':return conversations.bind(args.id,args.native_id)
        return conversations.open(args.id,args.dry_run)
    if group=='skill':
        skills=Skills(conn)
        if args.operation=='list':return skills.list()
        path=Path(args.file)
        if path.stat().st_size>200000:raise ValueError('Skill demasiado grande.')
        return skills.register(args.id,path.read_text(encoding='utf-8'),args.scope,args.owner)
    if group=='policy':
        return Policies(conn).get(args.id) if args.operation=='show' else Policies(conn).set(args.id,read_contract(args.file))
    if group=='workspace':
        if args.operation=='create':return spaces.create(args.id,args.repo,args.ref)
        if args.operation=='show':return spaces.get(args.id)
        if args.operation=='fingerprint':return {'task':args.id,'fingerprint':spaces.fingerprint(args.id)}
        if args.operation=='commit':return spaces.commit(args.id,args.message)
        if args.operation=='merge':return spaces.merge(args.id)
        space=spaces.get(args.id)
        return {'task':args.id,'diff':spaces.diff(args.id)}
    if group=='execute':return Runner(conn,state).run(args.id,args.profile,args.role,args.kind,new_session=args.new_session)
    if group=='verify':return Quality(conn,state).verify(args.id,read_contract(args.checks))
    if group=='review':return Quality(conn,state).review(args.id,args.profile,read_contract(args.report),args.kind)
    if group=='approve':return Policies(conn).approve(args.id,args.action,spaces.fingerprint(args.id),args.yes,args.reason)
    if group=='route':return Router(conn).choose(args.id,args.role)
    if group=='classify':return {'task':args.id,**classify(tasks.get(args.id).contract)}
    if group=='context':return Contexts(conn,state).build(args.id,Profiles(conn).get(args.profile),read_contract(args.history) if args.history else [])
    if group=='handoff':return Contexts(conn,state).handoff(args.id,args.source,args.target,args.reason,read_contract(args.file),args.override_fixed)
    if group=='cancel':return Runner(conn,state).cancel(args.id)
    if group=='project-state':
        project={'agent':args.agent,'id':args.id} if args.agent else args.id
        if args.operation=='set':return Contexts(conn,state).project_set(project,read_contract(args.file))
        key=json.dumps(project,sort_keys=True,ensure_ascii=False) if isinstance(project,dict) else project
        row=conn.execute('SELECT state FROM project_states WHERE id=?',(key,)).fetchone()
        if not row:raise ValueError('Estado de proyecto no encontrado.')
        return json.loads(row[0])
    if group=='run':
        runs=Runs(conn,state)
        if args.operation=='list':return runs.list()
        if args.operation=='create':return runs.create(read_contract(args.file))
        if args.operation=='plan':return runs.plan(args.intent,args.repo,args.files,args.agent)
        if args.operation=='request':
            from .requests import prepare, execute_ready
            result=prepare(runs,args.intent,args.repo,args.agent,continue_run=args.continue_run)
            return execute_ready(runs,result) if args.auto and result['status']=='ready' else result
        if args.operation=='show':return runs.get(args.id)
        if args.operation=='cancel':return runs.cancel(args.id)
        if args.operation=='recover':return runs.recover(args.id)
        if args.operation=='execute':
            run=runs.get(args.id)
            if run['configuration'].get('request'):
                from .requests import execute_ready
                return execute_ready(runs,{'run':run,'status':run['configuration']['request']['status'],'summary':run['title'],'questions':[]})
            return runs.execute(args.id,args.parallel)
        run=runs.get(args.id)
        if run['status'] in ('running','done','cancelled'):raise ValueError('El run no se puede modificar mientras está activo o terminado.')
        if args.operation=='prepare':
            prepared=[]
            for task in run['tasks']:
                if not task['blockers']:
                    setting=run['configuration']['tasks'][task['id']]
                    if not setting.get('repo'):raise ValueError('Falta repo explícito para '+task['id'])
                    prepared.append(spaces.create_directory(task['id'],setting['repo']) if setting.get('workspace_mode')=='directory' else spaces.create(task['id'],setting['repo'],setting.get('ref','HEAD')))
            return {'run':args.id,'workspaces':prepared}
        settings=read_contract(args.file)
        if not isinstance(settings,dict) or set(settings)-set(run['configuration']['tasks']):
            raise ValueError('Configura solo IDs que pertenecen a este run.')
        from .tasks import fields
        for ident,value in settings.items():
            fields(value,('repo','ref','checks','reviewer','security_reviewer'),'run settings')
            if 'checks' in value and (not isinstance(value['checks'],list) or any(not isinstance(a,list) or not a or not all(isinstance(v,str) and v for v in a) for a in value['checks'])):
                raise ValueError('Checks no válidos.')
            run['configuration']['tasks'][ident].update(value)
        with conn:
            conn.execute('UPDATE runs SET budget=? WHERE id=?',(json.dumps(run['configuration'],ensure_ascii=False),run_number(args.id)))
            runs.event(args.id,'run.configured',{'settings':settings})
        return runs.get(args.id)
    if group=='metrics':
        clauses=[];values=[]
        for field in ('profile','domain'):
            if getattr(args,field):clauses.append(field+'=?');values.append(getattr(args,field))
        where=' WHERE '+' AND '.join(clauses) if clauses else ''
        result=[dict(r) for r in conn.execute('SELECT profile,model,domain,complexity,COUNT(*) AS samples,AVG(success) AS success_rate,AVG(duration) AS average_duration,AVG(review_rejected) AS review_rejection_rate,SUM(tokens) AS reported_tokens,SUM(cost) AS reported_cost FROM agent_metrics'+where+' GROUP BY profile,model,domain,complexity ORDER BY profile,domain,complexity',values)]
        for item in result:
            item['failure_rate']=1-item['success_rate']
            item['average_retries']=conn.execute("SELECT AVG(attempts-1) FROM (SELECT COUNT(*) AS attempts FROM executions e JOIN agent_metrics m ON m.execution=e.id WHERE e.profile=? AND e.role='worker' AND m.domain=? AND m.complexity=? GROUP BY e.task)",
                                                 (item['profile'],item['domain'],item['complexity'])).fetchone()[0]
        return result
    if group=='events':
        if args.limit<1 or args.limit>1000 or args.after<0:raise ValueError('Paginación no válida.')
        if args.task:return [event for event in tasks.events(args.task) if event['id']>args.after][:args.limit]
        query='SELECT * FROM engine_events WHERE id>?';values=[args.after]
        if args.run:query+=' AND run=?';values.append(run_number(args.run))
        values.append(args.limit)
        return [{**dict(r),'payload':json.loads(r['payload'])} for r in conn.execute(query+' ORDER BY id LIMIT ?',values)]
    raise ValueError('Operación no implementada.')


def main(argv):
    args=parser().parse_args(argv)
    cache=None
    try:
        if args.group=='demo':
            from .demo import demo
            result=demo()
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 0 if result['status']=='done' else 1
        state=Path(os.environ.get('XDG_STATE_HOME',str(Path.home()/'.local/state')))/'agent-hub'
        cache=Cache(state/'index.sqlite')
        result=dispatch(args,cache,state)
        if args.group=='execution' and args.operation=='open' and not args.dry_run:
            return result
        print(json.dumps(result,ensure_ascii=False,indent=2))
        # Failures must be visible to callers even when structured evidence exists.
        operation_failure = args.group in ('execute','verify','review','doctor') or (args.group=='run' and args.operation=='execute')
        if operation_failure and isinstance(result,dict) and (result.get('passed') is False or result.get('verdict')=='reject' or result.get('status') in ('failed','changes_requested','waiting_human','cancelled')):
            return 1
        return 0
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as error:
        print('agent-hub work: '+clean(error),file=sys.stderr);return 1
    except KeyboardInterrupt:
        return 130
    finally:
        if cache:cache.close()
