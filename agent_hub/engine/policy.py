"""Explicit local policies and fingerprint-bound human decisions."""
import json
from pathlib import Path
import shutil
import time
from .tasks import TaskStore, number, fields, text


class Policies:
    def __init__(self, conn):
        self.conn = conn

    def set(self, ident, spec):
        text(ident, 'policy id', 100)
        fields(spec, ('network', 'dependencies', 'git_commit', 'shell', 'runtime_write_paths'), 'policy')
        for key, value in spec.items():
            if key == 'runtime_write_paths':
                paths=value.values() if isinstance(value,dict) else [value]
                if any(not isinstance(items,list) or any(not isinstance(p,str) or not Path(p).is_absolute() for p in items) for items in paths):
                    raise ValueError('runtime_write_paths requiere rutas absolutas explícitas.')
            elif type(value) is not bool:
                raise ValueError('La policy requiere booleanos.')
        with self.conn:
            self.conn.execute('INSERT INTO policies VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET spec=excluded.spec,updated=excluded.updated',
                              (ident, json.dumps(spec), int(time.time())))
        return spec

    def get(self, ident='default'):
        row = self.conn.execute('SELECT spec FROM policies WHERE id=?', (ident,)).fetchone()
        # Deny privileged actions unless an explicit policy allows them.
        value = {'network': False, 'dependencies': False, 'git_commit': False,
                 'shell': False, 'runtime_write_paths': []}
        if not row and ident!='default':
            raise ValueError('Policy no registrada: '+ident)
        if row:
            value.update(json.loads(row[0]))
        return value

    def approve(self, task, operation, fingerprint, approved, reason):
        TaskStore(self.conn).get(task)
        if operation not in ('execute', 'critical-start', 'critical-merge', 'merge', 'git-commit', 'dependencies', 'network'):
            raise ValueError('Operación de aprobación no válida.')
        if type(approved) is not bool:
            raise ValueError('La decisión debe ser explícita.')
        text(reason, 'approval reason', 4000)
        with self.conn:
            self.conn.execute('INSERT INTO approvals(task,operation,fingerprint,approved,reason,created) VALUES (?,?,?,?,?,?)',
                              (number(task), operation, fingerprint, int(approved), reason, int(time.time())))
        return {'task': task, 'operation': operation, 'fingerprint': fingerprint, 'approved': approved}

    def approved(self, task, operation, fingerprint):
        row = self.conn.execute('SELECT approved FROM approvals WHERE task=? AND operation=? AND fingerprint=? ORDER BY id DESC LIMIT 1',
                                (number(task), operation, fingerprint)).fetchone()
        return bool(row and row[0])

    def check(self, task, profile, fingerprint, role='worker'):
        contract = task.contract
        policy = self.get(contract.get('policy','default'))
        caps=profile.get('permissions',{})
        if contract['permissions']['filesystem']=='write' and caps.get('filesystem','write')!='write':
            raise ValueError('El perfil no admite escritura.')
        for operation in ('network','dependencies','git_commit','shell'):
            if contract['permissions'][operation] and caps.get(operation,True) is False:
                raise ValueError('El perfil no admite: '+operation)
        if contract['permissions']['git_push']:
            raise ValueError('El motor no autoriza push; permanece bajo control del usuario.')
        if not shutil.which('bwrap'):
            raise ValueError('Falta bubblewrap: se rechaza la ejecución sin aislamiento.')
        for operation in ('network', 'dependencies', 'git_commit', 'shell'):
            if contract['permissions'][operation] and not policy[operation]:
                raise ValueError('La policy no permite: ' + operation)
        if role == 'worker' and contract['complexity'] == 'critical' and not self.approved(task.id, 'critical-start', fingerprint):
            raise ValueError('Falta aprobación humana para iniciar la tarea crítica.')
        if contract['permissions']['network'] and not self.approved(task.id, 'network', fingerprint):
            raise ValueError('Falta aprobación explícita de red para esta versión del trabajo.')
        if contract['permissions']['dependencies'] and not self.approved(task.id, 'dependencies', fingerprint):
            raise ValueError('Falta aprobación explícita para dependencias.')
        if 'shell' in profile.get('tools', []) and not contract['permissions']['shell']:
            raise ValueError('El perfil necesita shell y el contrato no la permite.')
        if role == 'orchestrator':
            raise ValueError('El orquestador coordina; no ejecuta código de un worker.')
        runtime=policy['runtime_write_paths']
        if isinstance(runtime,dict):
            policy={**policy,'runtime_write_paths':runtime.get(profile['id'],[])}
        return policy
