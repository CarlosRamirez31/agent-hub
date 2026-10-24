"""Persistent DAG coordination; parallelism only over isolated verified workspaces."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import json
from pathlib import Path
import re
import time

from ..cache import Cache
from .tasks import TaskContract, TaskStore, task_id, number, text, fields
from .routing import Router, classify
from .execution import Runner
from .workspace import Workspaces, git
from .quality import Quality
from .context import Contexts


def run_number(ident):
    if not isinstance(ident,str) or not re.fullmatch(r'RUN-[0-9]{3,12}',ident):
        raise ValueError('ID de run no válido.')
    value=int(ident[4:])
    if value<1 or ident!=f'RUN-{value:03d}':
        raise ValueError('ID de run no canónico.')
    return value


class Runs:
    def __init__(self, conn, state):
        self.conn,self.state=conn,Path(state)
        self.tasks=TaskStore(conn)

    def event(self, ident, kind, payload, task=None):
        self.conn.execute('INSERT INTO engine_events(task,run,type,payload,created) VALUES (?,?,?,?,?)',
                          (number(task) if task else None,run_number(ident),kind,json.dumps(payload,ensure_ascii=False),int(time.time())))

    def get(self, ident):
        row=self.conn.execute('SELECT * FROM runs WHERE id=?',(run_number(ident),)).fetchone()
        if not row:
            raise ValueError('Run no encontrado: '+ident)
        tasks=[self.tasks.get(task_id(r[0])).json() for r in self.conn.execute('SELECT task FROM run_tasks WHERE run=? ORDER BY task',(row['id'],))]
        return {'id':ident,'title':row['title'],'status':row['status'],'configuration':json.loads(row['budget']),
                'tasks':tasks,'created':row['created'],'updated':row['updated']}

    def list(self):
        return [{'id':f'RUN-{r["id"]:03d}','title':r['title'],'status':r['status']}
                for r in self.conn.execute('SELECT id,title,status FROM runs ORDER BY id')]

    def create(self, spec):
        fields(spec,('title','tasks','budget'),'run')
        text(spec.get('title'),'run title',500)
        items=spec.get('tasks')
        if not isinstance(items,list) or not 1<=len(items)<=1000:
            raise ValueError('El run necesita entre 1 y 1000 contratos de tarea.')
        limits={'max_parallel':1,'max_agents':3,'max_turns':100,'timeout_seconds':1800}
        fields(spec.get('budget',{}),limits,'run budget')
        limits.update(spec.get('budget',{}))
        if any(type(v) is not int or not 1<=v<=100000 for v in limits.values()) or limits['max_parallel']>limits['max_agents'] or limits['max_parallel']>16 or limits['max_agents']>64:
            raise ValueError('Budget de run no válido.')
        keys={}
        for item in items:
            fields(item,('key','contract','depends_on','repo','ref','checks','reviewer','security_reviewer'),'run task')
            key=text(item.get('key'),'task key',100)
            if key in keys:
                raise ValueError('Key de tarea duplicada.')
            TaskContract.parse(item.get('contract'))
            keys[key]=item
            dependencies=item.get('depends_on',[])
            if not isinstance(dependencies,list) or not all(isinstance(k,str) for k in dependencies):
                raise ValueError('depends_on debe ser una lista de keys.')
            checks=item.get('checks',[])
            if not isinstance(checks,list) or any(not isinstance(argv,list) or not argv or not all(isinstance(a,str) and a and '\0' not in a for a in argv) for argv in checks):
                raise ValueError('Los checks del plan deben ser argv explícitos.')
        with self.tasks.transaction():
            now=int(time.time())
            row=self.conn.execute('INSERT INTO runs(title,status,budget,created,updated) VALUES (?,?,?,?,?)',
                                  (spec['title'],'pending','{}',now,now))
            ident=f'RUN-{row.lastrowid:03d}'
            created={k:self.tasks.create(item['contract']).id for k,item in keys.items()}
            settings={}
            for key,item in keys.items():
                target=created[key]
                for dependency in item.get('depends_on',[]):
                    if dependency not in created:
                        raise ValueError('Key de dependencia no encontrada: '+dependency)
                    self.tasks.dependency(target,created[dependency])
                self.conn.execute('INSERT INTO run_tasks VALUES (?,?)',(run_number(ident),number(target)))
                settings[target]={k:v for k,v in item.items() if k not in ('contract','depends_on','key')}
            self.conn.execute('UPDATE runs SET budget=? WHERE id=?',
                              (json.dumps({'limits':limits,'tasks':settings},ensure_ascii=False),run_number(ident)))
            self.event(ident,'run.created',{'tasks':created,'limits':limits})
        return self.get(ident)

    def plan(self, intent, repo=None, files=(), fixed=None):
        text(intent,'intent')
        contract={'title':intent[:500],'objective':intent,'scope':{'files':list(files)},
                  'assignment':{'mode':'fixed','agent':fixed} if fixed else {'mode':'orchestrated'}}
        contract=TaskContract.parse(contract).value
        hints=classify(contract)
        contract['complexity']=hints['complexity'];contract['domain']=hints['domain']
        contract['review']['required']=hints['complexity'] in ('medium','complex','critical')
        if hints['complexity'] in ('complex','critical'):
            # Deterministic decomposition creates reviewable contracts, not silent
            # code edits or a fabricated implementation plan from an LLM.
            analysis={**contract,'title':'Analizar: '+intent[:470],'objective':'Analizar alcance, riesgos y pasos para: '+intent,
                      'permissions':{**contract['permissions'],'filesystem':'read'}}
            implementation={**contract,'title':'Implementar: '+intent[:465]}
            tasks=[{'key':'analysis','contract':analysis,'repo':repo,'checks':[]},
                   {'key':'implementation','contract':implementation,'depends_on':['analysis'],'repo':repo,'checks':[]}]
        else:
            tasks=[{'key':'work','contract':contract,'repo':repo,'checks':[]}]
        return self.create({'title':intent[:500],'tasks':tasks})

    def cancel(self, ident):
        run=self.get(ident)
        with self.conn:
            self.conn.execute("UPDATE runs SET status='cancelled',updated=? WHERE id=?",(int(time.time()),run_number(ident)))
            self.event(ident,'run.cancelled',{'reason':'explicit user cancellation'})
        for task in run['tasks']:
            if task['status'] not in ('done','cancelled'):
                Runner(self.conn,self.state).cancel(task['id'])
        return self.get(ident)

    def recover(self, ident):
        from .process import token
        run=self.get(ident)
        active=self.conn.execute("SELECT e.* FROM executions e JOIN run_tasks rt ON rt.task=e.task WHERE rt.run=? AND e.status='running'",(run_number(ident),)).fetchall()
        from .profiles import Profiles
        from .container import controls
        if any(Profiles(self.conn).get(r['profile']).get('container') and not (controls(self.state,r['id'])/'complete').exists() for r in active):
            raise ValueError('El runner del contenedor no confirmó el cierre; no se forzará una recuperación ambigua.')
        if any(r['pid'] and r['process_token'] and token(r['pid'])==r['process_token'] for r in active):
            raise ValueError('Todavía hay un proceso propio activo; no se forzará su bloqueo.')
        with self.conn:
            for row in active:
                self.conn.execute("UPDATE executions SET status='failed',finished=?,result=? WHERE id=?",(time.time(),json.dumps({'error':'orphaned process; human recovery'}),row['id']))
                self.conn.execute("UPDATE tasks SET status='failed',revision=revision+1,updated=? WHERE id=? AND status='running'",(int(time.time()),row['task']))
            self.conn.execute("UPDATE runs SET status='waiting_human',updated=? WHERE id=?",(int(time.time()),run_number(ident)))
            self.event(ident,'run.recovered',{'orphaned_executions':[r['id'] for r in active]})
        return self.get(ident)

    def _prepare_dependencies(self, ident):
        workspaces=Workspaces(self.conn,self.state)
        for dependency in self.tasks.get(ident).dependencies:
            dep=workspaces.get(dependency)
            files=workspaces.changed_files(dependency)
            if not files:
                continue
            if git(dep['path'],'status','--porcelain').strip():
                raise ValueError('Integra primero el trabajo verificado de '+dependency+'; no se mezclarán cambios sin aprobación.')
            head=git(dep['path'],'rev-parse','HEAD').decode().strip()
            # merge-base --is-ancestor gives a clear error on an unintegrated
            # parent. Never cherry-pick or merge into the user's repo silently.
            git(dep['repo'],'merge-base','--is-ancestor',head,'HEAD')

    def _pipeline(self, ident, settings, deadline):
        # Every concurrent pipeline has its own connection and its own worktree.
        cache=Cache(self.state/'index.sqlite')
        try:
            store=TaskStore(cache.conn);runner=Runner(cache.conn,self.state)
            current=store.get(ident)
            self_local=Runs(cache.conn,self.state)
            if current.status=='done':
                return {'task':ident,'status':'done'}
            self_local._prepare_dependencies(ident)
            workspace=Workspaces(cache.conn,self.state)
            if not cache.conn.execute('SELECT 1 FROM workspaces WHERE task=?',(number(ident),)).fetchone():
                if not settings.get('repo'):
                    raise ValueError('Falta repositorio explícito para preparar un worktree.')
                workspace.create(ident,settings['repo'],settings.get('ref','HEAD'))
            if not settings.get('checks'):
                raise ValueError('Define checks deterministas antes de ejecutar el worker.')
            previous=cache.conn.execute("SELECT status,fingerprint FROM executions WHERE task=? AND role='worker' ORDER BY id DESC LIMIT 1",(number(ident),)).fetchone()
            resume_gates=current.status=='waiting_human' and previous and previous['status']=='completed' and previous['fingerprint']==workspace.fingerprint(ident)
            if resume_gates:
                with cache.conn:
                    cache.conn.execute("UPDATE tasks SET status='verifying',revision=revision+1,updated=? WHERE id=?",(int(time.time()),number(ident)))
                    store.event(ident,'task.resumed_gates',{'reason':'human decision received; worker result unchanged'})
            elif current.status in ('pending','blocked','failed','changes_requested','waiting_human'):
                store.status(ident,'ready')
            if store.get(ident).status=='ready':
                target=cache.conn.execute('SELECT target FROM structured_handoffs WHERE task=? ORDER BY id DESC LIMIT 1',(number(ident),)).fetchone()
                outcome=runner.run(ident,target[0] if target else None,deadline=deadline)
                if outcome['status']!='completed':
                    return outcome
            task=store.get(ident)
            quality=Quality(cache.conn,self.state)
            verification=quality.verify(ident,settings['checks'],deadline=deadline)
            if not verification['passed']:
                store.status(ident,'changes_requested',reason='deterministic checks failed')
                return {'task':ident,'status':'changes_requested','verification':verification}
            if quality.gate(ident)['passed']:
                store.status(ident,'done')
                return {'task':ident,'status':'done','fingerprint':quality.gate(ident)['fingerprint']}
            if task.contract['review']['required']:
                if store.get(ident).status=='verifying':
                    store.status(ident,'reviewing')
                for kind in (('code','security') if task.contract['complexity']=='critical' else ('code',)):
                    profile=settings.get('security_reviewer' if kind=='security' else 'reviewer')
                    if profile is None and kind=='security':
                        options=Router(cache.conn).candidates(store.get(ident),'reviewer')
                        from .profiles import Profiles
                        profile=next((p['id'] for p in options if 'security-review' in Profiles(cache.conn).get(p['id'])['capabilities']),None)
                        if profile is None:
                            raise ValueError('Falta reviewer independiente de seguridad.')
                    reviewed=runner.run(ident,profile,role='reviewer',review_kind=kind,deadline=deadline)
                    if reviewed['status']!='completed' or reviewed.get('result',{}).get('review',{}).get('verdict')!='approve':
                        store.status(ident,'changes_requested',reason='review rejected or failed')
                        return {'task':ident,'status':'changes_requested','review':reviewed}
            gate=quality.gate(ident)
            if not gate['passed']:
                raise ValueError('Gates pendientes: '+', '.join(gate['missing']))
            store.status(ident,'done')
            return {'task':ident,'status':'done','fingerprint':gate['fingerprint']}
        except (ValueError,OSError,KeyError,TypeError) as error:
            task=TaskStore(cache.conn).get(ident)
            if task.status not in ('done','cancelled','waiting_human'):
                TaskStore(cache.conn).status(ident,'waiting_human',reason=str(error))
            return {'task':ident,'status':'waiting_human','error':str(error)}
        finally:
            cache.close()

    def execute(self, ident, max_parallel=None):
        run=self.get(ident)
        limits=run['configuration']['limits']
        parallel=limits['max_parallel'] if max_parallel is None else max_parallel
        if type(parallel) is not int or not 1<=parallel<=min(limits['max_parallel'],limits['max_agents']):
            raise ValueError('Paralelismo fuera del budget del run.')
        with self.tasks.transaction():
            row=self.conn.execute('SELECT status FROM runs WHERE id=?',(run_number(ident),)).fetchone()
            if row[0] in ('running','done','cancelled'):
                raise ValueError('El run ya está activo o terminó; usa recuperación explícita si quedó huérfano.')
            self.conn.execute("UPDATE runs SET status='running',updated=? WHERE id=?",(int(time.time()),run_number(ident)))
            self.event(ident,'run.started',{'parallel':parallel})
        deadline=time.monotonic()+limits['timeout_seconds']
        attempted=set();results=[];active={}
        pool=ThreadPoolExecutor(max_workers=parallel)
        try:
            while True:
                if self.get(ident)['status']=='cancelled':
                    break
                if time.monotonic()>=deadline:
                    for task in self.get(ident)['tasks']:
                        if task['status']=='running':
                            Runner(self.conn,self.state).cancel(task['id'])
                    results.append({'error':'run timeout'})
                    break
                run=self.get(ident)
                candidates=[t for t in run['tasks'] if t['id'] not in attempted and t['status'] not in ('done','cancelled','running') and not t['blockers']]
                for task in candidates[:max(0,parallel-len(active))]:
                    attempted.add(task['id'])
                    future=pool.submit(self._pipeline,task['id'],run['configuration']['tasks'][task['id']],deadline)
                    active[future]=task['id']
                if not active:
                    break
                finished,_=wait(active,timeout=.1,return_when=FIRST_COMPLETED)
                for future in finished:
                    task=active.pop(future)
                    result=future.result()
                    results.append(result)
                    current=self.tasks.get(task)
                    attempts=self.conn.execute("SELECT COUNT(*) FROM executions WHERE task=? AND role='worker'",(number(task),)).fetchone()[0]
                    retryable=result.get('status') in ('failed','changes_requested') and attempts<=current.contract['budget']['max_retries']
                    error=str(result.get('result',{}).get('error') or result.get('error') or '').casefold()
                    reason=next((reason for phrase,reason in (('quota','quota_exhausted'),('token limit','token_limit'),('provider unavailable','provider_unavailable')) if phrase in error),None)
                    if retryable and reason:
                        if current.contract['assignment']['mode']=='fixed':
                            retryable=False
                        else:
                            source=result.get('profile')
                            chain={r[0] for r in self.conn.execute('SELECT target FROM structured_handoffs WHERE task=?',(number(task),))}
                            options=Router(self.conn).candidates(current)
                            target=next((p['id'] for p in options if p['id']!=source and p['id'] not in chain),None)
                            if not source or not target:
                                retryable=False
                            else:
                                try:
                                    Contexts(self.conn,self.state).handoff(task,source,target,reason,
                                        {'summary':'Continuation after '+reason,'open_issues':[error[:2000]],'next_steps':['Complete the existing task contract in the same isolated workspace.']})
                                except ValueError:
                                    retryable=False
                    if retryable:
                        attempted.discard(task)
                    with self.conn:
                        self.event(ident,'task.pipeline_finished',result,task)
        except KeyboardInterrupt:
            self.cancel(ident)
            raise
        finally:
            pool.shutdown(wait=True,cancel_futures=True)
        final=self.get(ident)
        if final['status']!='cancelled':
            status='done' if all(t['status']=='done' for t in final['tasks']) else 'waiting_human'
            with self.conn:
                self.conn.execute('UPDATE runs SET status=?,updated=? WHERE id=?',(status,int(time.time()),run_number(ident)))
                self.event(ident,'run.'+status,{'results':results})
        return {**self.get(ident),'results':results}
