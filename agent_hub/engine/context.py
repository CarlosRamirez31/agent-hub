"""Bounded context packs and explicit structured handoffs, alongside raw transfer."""
import json
from pathlib import Path
import time
from .tasks import TaskStore, number, text, fields, relative, strings
from .skills import Skills
from .workspace import Workspaces, git


class Contexts:
    def __init__(self, conn, state):
        self.conn, self.state = conn, Path(state)

    def project_set(self, ident, value):
        if isinstance(ident,dict):
            fields(ident,('agent','id'),'project reference')
            ident=json.dumps({key:text(ident.get(key),'project.'+key,4096) for key in ('agent','id')},sort_keys=True,ensure_ascii=False)
        text(ident, 'project state id', 10000)
        if not isinstance(value, dict) or len(json.dumps(value)) > 200000:
            raise ValueError('Estado de proyecto inválido o demasiado grande.')
        with self.conn:
            self.conn.execute('INSERT INTO project_states VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,updated=excluded.updated',
                              (ident, json.dumps(value, ensure_ascii=False), int(time.time())))
        return value

    def build(self, ident, profile, history=()):
        task = TaskStore(self.conn).get(ident)
        workspace = Workspaces(self.conn, self.state).get(ident)
        limit = min(task.contract['budget']['max_chars'], profile['context_max_chars']) - 64  # reserve returned pack ID/metadata
        pack = {'version': 1, 'task': ident, 'contract': task.contract,
                'workspace': workspace['path'], 'branch': workspace['branch'],
                'base': workspace['base'], 'skills': Skills(self.conn).for_task(task, profile),
                'project_state': None, 'feedback': [], 'files': [], 'history': [], 'git_diff': '', 'omitted': []}
        project = json.dumps(task.contract.get('project'), sort_keys=True, ensure_ascii=False)
        row = self.conn.execute('SELECT state FROM project_states WHERE id=?', (project,)).fetchone()
        if row:
            pack['project_state'] = json.loads(row[0])
        for review in self.conn.execute('SELECT reviewer,verdict,issues,kind FROM reviews WHERE task=? ORDER BY id DESC LIMIT 2',(number(ident),)):
            issues=json.loads(review['issues'])
            selected=sorted(issues,key=lambda issue:{'critical':0,'high':1,'medium':2,'low':3}[issue['severity']])[:10]
            pack['feedback'].append({**dict(review),'issues':[{**issue,'message':issue['message'][:1000]} for issue in selected],'omitted_issues':max(0,len(issues)-len(selected))})
        last=self.conn.execute('SELECT result FROM executions WHERE task=? ORDER BY id DESC LIMIT 1',(number(ident),)).fetchone()
        if last and last[0]:
            result=json.loads(last[0])
            pack['feedback'].append({'last_result':{key:(value[:4000] if isinstance(value,str) else value) for key,value in result.items() if key in ('text','error','native_id','profile_snapshot')}})
        verification=self.conn.execute('SELECT passed,evidence FROM verifications WHERE task=? ORDER BY id DESC LIMIT 1',(number(ident),)).fetchone()
        if verification:
            evidence=json.loads(verification['evidence'])
            pack['feedback'].append({'verification':{'passed':bool(verification['passed']),'scope_ok':evidence.get('scope_ok'),'files_changed':evidence.get('files_changed',[])[:100],
                'checks':[{key:(value[:2000] if isinstance(value,str) else value) for key,value in check.items() if key in ('code','failure','stdout','stderr')} for check in evidence.get('checks',[])[:10]]}})
        def size():
            return len(json.dumps(pack, ensure_ascii=False))
        if size() > limit:
            raise ValueError('El contrato y las skills obligatorias exceden el budget de contexto.')
        root = Path(workspace['path'])
        for name in task.contract['scope']['files']:
            file = root/name
            if file.is_symlink() or root not in file.resolve().parents:
                raise ValueError('Archivo fuera del workspace: ' + name)
            if not file.exists():
                continue
            with file.open(encoding='utf-8', errors='replace') as source:
                content = source.read(limit+1)
            item = {'path': name, 'content': content}
            pack['files'].append(item)
            if size() > limit-200:
                pack['files'].pop(); pack['omitted'].append('file:' + name)
        for message in list(history)[-20:]:
            if not isinstance(message, dict) or message.get('role') not in ('user', 'assistant') or not isinstance(message.get('text'), str):
                continue
            pack['history'].append({'role': message['role'], 'text': message['text']})
            if size() > limit-200:
                pack['history'].pop();pack['omitted'].append('history');break
        diff = git(root, 'diff', '--no-ext-diff', '--no-textconv', workspace['base'], '--').decode('utf-8', errors='replace')
        available = max(0, limit-size()-500)
        pack['git_diff'] = diff[:available]
        if len(diff) > available:
            pack['omitted'].append('git_diff_tail')
        # JSON escaping may expand control characters: shrink the optional diff
        # until the serialized payload, not merely raw strings, fits the budget.
        while size() > limit and pack['git_diff']:
            pack['git_diff'] = pack['git_diff'][:len(pack['git_diff'])//2]
        if size() > limit:
            raise ValueError('El context pack supera el límite; reduce archivos o skills.')
        with self.conn:
            row = self.conn.execute('INSERT INTO context_packs(task,content,created) VALUES (?,?,?)',
                                    (number(ident), json.dumps(pack, ensure_ascii=False), int(time.time())))
        return {'id': row.lastrowid, **pack}

    def handoff(self, ident, source, target, reason, content, fixed_override=False):
        task = TaskStore(self.conn).get(ident)
        if task.status in ('running','done','cancelled'):
            raise ValueError('Detén/libera la tarea activa o crea una continuación para una tarea terminada.')
        assignment = task.contract['assignment']
        if assignment['mode'] == 'fixed' and target != assignment['agent'] and not fixed_override:
            raise ValueError('Fixed assignment requiere override humano explícito para cambiar agente.')
        if source == target:
            raise ValueError('El destino debe ser otro perfil.')
        from .profiles import Profiles
        Profiles(self.conn).get(source)
        profile = Profiles(self.conn).get(target)
        if 'worker' not in profile['roles']:
            raise ValueError('El destino no admite el rol worker.')
        Skills(self.conn).for_task(task,profile)
        if not Profiles(self.conn).available(profile):
            raise ValueError('El perfil destino no está disponible.')
        if not set(task.contract['capabilities']) <= set(profile['capabilities']):
            raise ValueError('El destino no tiene las capacidades requeridas.')
        if reason not in ('manual', 'quota_exhausted', 'token_limit', 'provider_unavailable', 'cli_failure'):
            raise ValueError('Motivo de handoff no válido.')
        fields(content, ('summary', 'files_changed', 'decisions', 'open_issues', 'next_steps'), 'handoff')
        text(content.get('summary'), 'handoff summary')
        content=dict(content)
        for key in ('files_changed','decisions','open_issues','next_steps'):
            if key in content:
                content[key]=strings(content[key],'handoff.'+key)
        if 'files_changed' in content:
            content['files_changed']=[relative(path) for path in content['files_changed']]
        if len(json.dumps(content, ensure_ascii=False)) > task.contract['budget']['max_chars']:
            raise ValueError('Handoff excede el budget de contexto.')
        chain = [dict(r) for r in self.conn.execute('SELECT source,target FROM structured_handoffs WHERE task=? ORDER BY id', (number(ident),))]
        seen = {a for row in chain for a in (row['source'], row['target'])}
        if chain and chain[-1]['target'] != source:
            raise ValueError('El origen no corresponde al último destino del handoff.')
        if len(chain) >= task.contract['budget']['max_handoff_depth'] or target in seen or source == target:
            if task.status not in ('done', 'cancelled', 'waiting_human'):
                TaskStore(self.conn).status(ident, 'waiting_human', reason='handoff cycle or depth budget')
            raise ValueError('Ciclo o budget de handoff: se requiere decisión humana.')
        with TaskStore(self.conn).transaction():
            if fixed_override and assignment['mode']=='fixed' and target!=assignment['agent']:
                TaskStore(self.conn).replace_contract(ident,{**task.contract,'assignment':{'mode':'fixed','agent':target}},'explicit human handoff override')
            row = self.conn.execute('INSERT INTO structured_handoffs(task,source,target,reason,content,created) VALUES (?,?,?,?,?,?)',
                                    (number(ident), source, target, reason, json.dumps(content, ensure_ascii=False), int(time.time())))
            self.conn.execute('UPDATE tasks SET status=?,revision=revision+1,updated=? WHERE id=?',('blocked' if task.blockers else 'ready',int(time.time()),number(ident)))
            TaskStore(self.conn).event(ident, 'handoff.created', {'source': source, 'target': target, 'reason': reason, 'override': fixed_override})
        return {'id': row.lastrowid, 'task': ident, 'source': source, 'target': target, 'reason': reason, **content}
