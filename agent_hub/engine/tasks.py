"""Versioned task contracts, audited transitions and transaction-safe DAGs."""
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import PurePosixPath, Path
import re
import time
import uuid

STATES = ('pending', 'ready', 'blocked', 'running', 'verifying', 'reviewing',
          'changes_requested', 'waiting_human', 'failed', 'done', 'cancelled')
COMPLEXITIES = ('trivial', 'small', 'medium', 'complex', 'critical')
TRANSITIONS = {
    'pending': {'ready', 'blocked', 'waiting_human', 'cancelled'},
    'ready': {'running', 'blocked', 'waiting_human', 'cancelled'},
    'blocked': {'ready', 'waiting_human', 'cancelled'},
    'running': {'verifying', 'failed', 'blocked', 'waiting_human', 'cancelled'},
    'verifying': {'reviewing', 'done', 'changes_requested', 'failed', 'waiting_human', 'cancelled'},
    'reviewing': {'done', 'changes_requested', 'failed', 'waiting_human', 'cancelled'},
    'changes_requested': {'ready', 'waiting_human', 'cancelled'},
    'waiting_human': {'ready', 'blocked', 'cancelled'},
    'failed': {'ready', 'cancelled'},
    'done': set(), 'cancelled': set(),
}
AGENT_ID = re.compile(r'[a-z][a-z0-9_-]{0,63}\Z')


def text(value, name, maximum=200000):
    if not isinstance(value, str) or not value.strip() or '\0' in value or len(value) > maximum:
        raise ValueError('Texto no válido: ' + name)
    return value


def fields(value, allowed, name):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError('Campos no válidos en ' + name)


def strings(value, name):
    if not isinstance(value, list) or len(value) > 1000:
        raise ValueError('Se espera una lista acotada: ' + name)
    return [text(v, name) for v in value]


def relative(value):
    text(value, 'scope.files', 4096)
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or '\\' in value or str(p) == '.':
        raise ValueError('El alcance debe usar archivos relativos dentro del workspace.')
    return value


@dataclass(frozen=True)
class TaskContract:
    value: dict

    @classmethod
    def parse(cls, raw):
        fields(raw, ('version', 'title', 'objective', 'scope', 'constraints', 'acceptance',
                     'complexity', 'assignment', 'permissions', 'review', 'budget', 'project',
                     'domain', 'capabilities', 'specializations', 'skills', 'policy'), 'task contract')
        if type(raw.get('version', 1)) is not int or raw.get('version', 1) != 1:
            raise ValueError('Versión de contrato no compatible.')
        value = {'version': 1, 'title': text(raw.get('title'), 'title', 500),
                 'objective': text(raw.get('objective'), 'objective')}
        scope = raw.get('scope', {'files': []})
        fields(scope, ('files',), 'scope')
        value['scope'] = {'files': [relative(v) for v in strings(scope.get('files', []), 'scope.files')]}
        for field in ('constraints', 'acceptance', 'capabilities', 'specializations', 'skills'):
            value[field] = strings(raw.get(field, []), field)
        complexity = raw.get('complexity', 'medium')
        if complexity not in COMPLEXITIES:
            raise ValueError('Complejidad no válida.')
        value['complexity'] = complexity
        assignment = raw.get('assignment', {'mode': 'orchestrated'})
        fields(assignment, ('mode', 'agent'), 'assignment')
        mode = assignment.get('mode')
        if mode not in ('fixed', 'orchestrated'):
            raise ValueError('Asignación no válida.')
        if mode == 'fixed':
            if not isinstance(assignment.get('agent'), str) or not AGENT_ID.fullmatch(assignment['agent']):
                raise ValueError('La asignación fixed requiere un ID de agente válido.')
        elif 'agent' in assignment:
            raise ValueError('Una asignación orchestrated no debe fijar agente.')
        value['assignment'] = dict(assignment)
        permissions = {'filesystem': 'read', 'network': False, 'dependencies': False,
                       'git_commit': False, 'git_push': False, 'shell': False}
        supplied = raw.get('permissions', {})
        fields(supplied, permissions, 'permissions')
        permissions.update(supplied)
        if permissions['filesystem'] not in ('read', 'write') or any(
                type(permissions[k]) is not bool for k in permissions if k != 'filesystem'):
            raise ValueError('Permisos no válidos.')
        value['permissions'] = permissions
        review = raw.get('review', {})
        fields(review, ('required',), 'review')
        required = review.get('required', complexity in ('medium', 'complex', 'critical'))
        if type(required) is not bool or (complexity == 'critical' and not required):
            raise ValueError('Las tareas críticas requieren revisión.')
        value['review'] = {'required': required}
        budget = {'max_turns': 12, 'max_retries': 2, 'max_agents': 3,
                  'max_handoff_depth': 3, 'max_chars': 40000, 'timeout_seconds': 300}
        fields(raw.get('budget', {}), budget, 'budget')
        budget.update(raw.get('budget', {}))
        for k, v in budget.items():
            if type(v) is not int or v < (0 if k == 'max_retries' else 1) or v > 1000000:
                raise ValueError('Budget no válido: ' + k)
        value['budget'] = budget
        if 'project' in raw:
            fields(raw['project'], ('agent', 'id'), 'project')
            value['project'] = {k: text(raw['project'].get(k), 'project.' + k, 4096) for k in ('agent', 'id')}
        value['domain'] = text(raw.get('domain', 'general'), 'domain', 100)
        value['policy'] = text(raw.get('policy', 'default'), 'policy', 100)
        return cls(value)


@dataclass(frozen=True)
class Task:
    id: str
    status: str
    contract: dict
    dependencies: tuple
    blockers: tuple
    created: int
    updated: int
    revision: int

    def json(self):
        return {**self.__dict__, 'dependencies': list(self.dependencies), 'blockers': list(self.blockers)}


def task_id(number):
    return f'TASK-{number:03d}'


def number(ident):
    if not isinstance(ident, str) or not re.fullmatch(r'TASK-[0-9]{3,12}', ident):
        raise ValueError('ID de tarea inválido; usa TASK-001.')
    result = int(ident[5:])
    if result < 1 or task_id(result) != ident:
        raise ValueError('ID de tarea no canónico.')
    return result


class TaskStore:
    def __init__(self, conn):
        self.conn = conn

    @contextmanager
    def transaction(self):
        nested = self.conn.in_transaction
        savepoint = 'task_' + uuid.uuid4().hex
        self.conn.execute('SAVEPOINT '+savepoint if nested else 'BEGIN IMMEDIATE')
        try:
            yield
            if nested:
                self.conn.execute('RELEASE SAVEPOINT '+savepoint)
            else:
                self.conn.commit()
        except BaseException:
            if nested:
                self.conn.execute('ROLLBACK TO SAVEPOINT '+savepoint)
                self.conn.execute('RELEASE SAVEPOINT '+savepoint)
            else:
                self.conn.rollback()
            raise

    def event(self, ident, kind, payload):
        self.conn.execute('INSERT INTO task_events(task,type,payload,created) VALUES (?,?,?,?)',
                          (number(ident), kind, json.dumps(payload, ensure_ascii=False), int(time.time())))

    def get(self, ident):
        row = self.conn.execute('SELECT * FROM tasks WHERE id=?', (number(ident),)).fetchone()
        if row is None:
            raise ValueError('No existe la tarea: ' + ident)
        deps = self.conn.execute('SELECT d.dependency,t.status FROM task_dependencies d JOIN tasks t ON t.id=d.dependency WHERE d.task=? ORDER BY d.dependency', (row['id'],)).fetchall()
        return Task(ident, row['status'], json.loads(row['contract']),
                    tuple(task_id(d[0]) for d in deps), tuple(task_id(d[0]) for d in deps if d[1] != 'done'),
                    row['created'], row['updated'], row['revision'])

    def list(self, status=None):
        if status is not None and status not in STATES:
            raise ValueError('Estado de tarea no válido.')
        rows = self.conn.execute('SELECT id FROM tasks' + (' WHERE status=?' if status else '') + ' ORDER BY id',
                                 (status,) if status else ()).fetchall()
        return [self.get(task_id(r[0])) for r in rows]

    def _dependency(self, ident, dependency):
        self.get(dependency)
        if ident == dependency:
            raise ValueError('Una tarea no puede depender de sí misma.')
        cyclic = self.conn.execute('''WITH RECURSIVE upstream(id) AS (
            SELECT dependency FROM task_dependencies WHERE task=? UNION
            SELECT d.dependency FROM task_dependencies d JOIN upstream u ON d.task=u.id)
            SELECT 1 FROM upstream WHERE id=?''', (number(dependency), number(ident))).fetchone()
        if cyclic:
            raise ValueError('La dependencia produciría un ciclo.')
        self.conn.execute('INSERT OR IGNORE INTO task_dependencies VALUES (?,?)', (number(ident), number(dependency)))

    def create(self, contract, dependencies=()):
        value = TaskContract.parse(contract).value
        with self.transaction():
            now = int(time.time())
            row = self.conn.execute('INSERT INTO tasks(contract,status,created,updated) VALUES (?,?,?,?)',
                                    (json.dumps(value, ensure_ascii=False), 'pending', now, now))
            ident = task_id(row.lastrowid)
            for dependency in dict.fromkeys(dependencies):
                self._dependency(ident, dependency)
            self.event(ident, 'task.created', {'contract': value, 'dependencies': list(dict.fromkeys(dependencies))})
        return self.get(ident)

    def dependency(self, ident, dependency, remove=False):
        with self.transaction():
            task = self.get(ident)
            if task.status not in ('pending', 'ready', 'blocked'):
                raise ValueError('Solo se modifican dependencias antes de ejecutar la tarea.')
            if remove:
                self.get(dependency)
                self.conn.execute('DELETE FROM task_dependencies WHERE task=? AND dependency=?', (number(ident), number(dependency)))
            else:
                self._dependency(ident, dependency)
            updated = self.get(ident)
            state = 'blocked' if updated.status == 'ready' and updated.blockers else updated.status
            self.conn.execute('UPDATE tasks SET revision=revision+1,updated=?,status=? WHERE id=?', (int(time.time()), state, number(ident)))
            self.event(ident, 'task.dependency_removed' if remove else 'task.dependency_added', {'dependency': dependency})
        return self.get(ident)

    def status(self, ident, status, expected_revision=None, reason=None):
        if status not in STATES:
            raise ValueError('Estado de tarea no válido.')
        with self.transaction():
            task = self.get(ident)
            if expected_revision is not None and task.revision != expected_revision:
                raise ValueError('La tarea cambió; vuelve a leer su revisión.')
            if task.status == status:
                return task
            if status not in TRANSITIONS[task.status]:
                raise ValueError(f'Transición no permitida: {task.status} → {status}')
            if status in ('ready', 'running', 'done') and task.blockers:
                raise ValueError('Dependencias pendientes: ' + ', '.join(task.blockers))
            if status == 'done' and self.conn.execute("SELECT 1 FROM executions WHERE task=?", (number(ident),)).fetchone():
                from .quality import Quality
                state = Path(self.conn.execute('PRAGMA database_list').fetchone()[2]).parent
                gate = Quality(self.conn, state).gate(ident)
                if not gate['passed']:
                    raise ValueError('Quality gates pendientes: ' + ', '.join(gate['missing']))
            self.conn.execute('UPDATE tasks SET status=?,updated=?,revision=revision+1 WHERE id=?',
                              (status, int(time.time()), number(ident)))
            self.event(ident, 'task.status_changed', {'from': task.status, 'to': status, 'reason': reason})
        return self.get(ident)

    def events(self, ident):
        self.get(ident)
        return [{'id': r['id'], 'type': r['type'], 'payload': json.loads(r['payload']), 'created': r['created']}
                for r in self.conn.execute('SELECT * FROM task_events WHERE task=? ORDER BY id', (number(ident),))]

    def replace_contract(self, ident, contract, reason):
        value = TaskContract.parse(contract).value
        text(reason, 'reason', 4000)
        with self.transaction():
            task = self.get(ident)
            if task.status in ('running', 'done', 'cancelled'):
                raise ValueError('No se modifica el contrato de una tarea activa o terminada.')
            self.conn.execute('UPDATE tasks SET contract=?,revision=revision+1,updated=? WHERE id=?',
                              (json.dumps(value, ensure_ascii=False), int(time.time()), number(ident)))
            self.event(ident, 'task.contract_replaced', {'old': task.contract, 'new': value, 'reason': reason})
        return self.get(ident)
