"""Local scoped skills. Content is data, never executable discovery hooks."""
import json
import time
from .tasks import text,fields,AGENT_ID


# Only these bundled skills opt into relevance filtering. Custom global skills
# keep their historical always-included semantics.
BUNDLED = frozenset(('context-efficiency', 'software-architect', 'anti-overengineering',
                     'surgical-edits', 'repo-scaffold', 'appsec-guardrail'))


def relevant_bundled(contract):
    # Efficiency's full guide is opt-in; native sessions get a brief reminder.
    selected = set()
    if contract['complexity'] in ('medium', 'complex', 'critical') or contract['domain'] == 'architecture':
        selected.add('software-architect')
    permissions = contract['permissions']
    if permissions['filesystem'] == 'write':
        selected.update(('anti-overengineering', 'appsec-guardrail'))
        if contract['complexity'] in ('trivial', 'small'):
            selected.add('surgical-edits')
    if permissions['network'] or contract['domain'] == 'security':
        selected.add('appsec-guardrail')
    # New-project scaffolding is selected explicitly by the request planner or
    # the task/profile. Never infer it from untrusted filenames or prose.
    return selected


class Skills:
    def __init__(self, conn):
        self.conn = conn

    def register(self, ident, content, scope='global', owner=''):
        text(ident, 'skill id', 200)
        text(content, 'skill content', 200000)
        if scope not in ('global', 'agent', 'project') or (scope != 'global' and not owner):
            raise ValueError('Scope/owner de skill no válido.')
        if scope=='global' and owner:
            raise ValueError('Una skill global no tiene owner privado.')
        if scope=='agent' and (not isinstance(owner,str) or not AGENT_ID.fullmatch(owner)):
            raise ValueError('Owner de agente inválido.')
        if scope=='project':
            try:
                project=json.loads(owner)
                fields(project,('agent','id'),'skill project owner')
                owner=json.dumps({key:text(project.get(key),'project.'+key,4096) for key in ('agent','id')},sort_keys=True,ensure_ascii=False)
            except (ValueError,TypeError) as error:
                raise ValueError('El owner de proyecto debe ser JSON con agent e id opacos.') from error
        existing = self.conn.execute('SELECT scope,owner FROM skills WHERE id=?', (ident,)).fetchone()
        if existing and (existing['scope'], existing['owner']) != (scope, owner):
            raise ValueError('El ID de skill ya pertenece a otro scope; usa un ID específico.')
        with self.conn:
            self.conn.execute('INSERT INTO skills VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET content=excluded.content,updated=excluded.updated',
                              (ident, scope, owner, content, int(time.time())))
        return self.get(ident)

    def get(self, ident):
        row = self.conn.execute('SELECT * FROM skills WHERE id=?', (ident,)).fetchone()
        if not row:
            raise ValueError('Skill no registrada: ' + ident)
        return dict(row)

    def list(self):
        return [dict(row) for row in self.conn.execute('SELECT id,scope,owner,updated FROM skills ORDER BY id')]

    def for_task(self, task, profile):
        project = json.dumps(task.contract.get('project'), sort_keys=True, ensure_ascii=False)
        requested = list(dict.fromkeys(task.contract['skills'] + profile['skills']))
        selected = []
        relevant = relevant_bundled(task.contract) | set(requested)
        for row in self.conn.execute("SELECT * FROM skills WHERE scope='global' ORDER BY id"):
            if row['id'] not in BUNDLED or row['id'] in relevant:
                selected.append(dict(row))
        for ident in requested:
            item = self.get(ident)
            if item['scope'] == 'agent' and item['owner'] != profile['id']:
                raise ValueError('Skill privada de otro agente: ' + ident)
            if item['scope'] == 'project' and item['owner'] != project:
                raise ValueError('Skill de otro proyecto: ' + ident)
            if not any(s['id'] == ident for s in selected):
                selected.append(item)
        return selected
