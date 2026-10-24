"""Deterministic checks and independent, revision-bound structured reviews."""
import json
import time
from pathlib import Path
from .tasks import TaskStore, number, relative, text, fields
from .workspace import Workspaces
from .policy import Policies
from .process import execute


class Quality:
    def __init__(self, conn, state):
        self.conn, self.state = conn, state
        self.workspaces = Workspaces(conn, state)

    def verify(self, ident, checks, deadline=None):
        task = TaskStore(self.conn).get(ident)
        if task.status not in ('verifying', 'reviewing', 'changes_requested', 'waiting_human'):
            raise ValueError('La tarea debe haber producido trabajo antes de verificar.')
        if not isinstance(checks, list) or not checks or len(checks) > 30:
            raise ValueError('Se requieren checks explícitos como lista de argv.')
        for argv in checks:
            if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a and '\0' not in a for a in argv):
                raise ValueError('Cada check debe ser un array de argumentos.')
        fingerprint = self.workspaces.fingerprint(ident)
        workspace = self.workspaces.get(ident)
        evidence = []
        deadline = min(deadline or float('inf'), time.monotonic()+task.contract['budget']['timeout_seconds'])
        for argv in checks:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                evidence.append({'argv': argv, 'code': None, 'failure': 'timeout'});break
            result = execute(argv, workspace['path'], timeout=remaining, writable=False, network=False)
            evidence.append({'argv': argv, **result})
            if result['code'] != 0 or result['failure']:
                break
        changed = self.workspaces.changed_files(ident)
        allowed = task.contract['scope']['files']
        scope_ok = not changed or (bool(allowed) and set(changed) <= set(allowed))
        permissions_ok = task.contract['permissions']['filesystem'] == 'write' or not changed
        dependencies_ok = task.contract['permissions']['dependencies'] or not any(
            p.rsplit('/',1)[-1] in ('package.json','package-lock.json','requirements.txt','pyproject.toml','Cargo.toml','Cargo.lock','go.mod','go.sum') for p in changed)
        root=Path(workspace['path'])
        symlinks_ok=all(not (root/name).is_symlink() or root in (root/name).resolve().parents for name in changed)
        passed = (symlinks_ok and len(evidence) == len(checks) and all(r['code'] == 0 and not r['failure'] for r in evidence)
                  and scope_ok and permissions_ok and dependencies_ok and fingerprint == self.workspaces.fingerprint(ident))
        record = {'checks': evidence, 'scope_ok': scope_ok, 'permissions_ok': permissions_ok,
                  'dependencies_ok': dependencies_ok, 'symlinks_ok':symlinks_ok, 'files_changed': changed}
        with self.conn:
            self.conn.execute('INSERT INTO verifications(task,fingerprint,passed,evidence,created) VALUES (?,?,?,?,?)',
                              (number(ident), fingerprint, int(passed), json.dumps(record, ensure_ascii=False), int(time.time())))
            TaskStore(self.conn).event(ident, 'verification.passed' if passed else 'verification.failed', {'fingerprint': fingerprint})
        return {'task': ident, 'passed': passed, 'fingerprint': fingerprint, **record}

    def review(self, ident, reviewer, result, kind='code'):
        task = TaskStore(self.conn).get(ident)
        if kind not in ('code', 'security'):
            raise ValueError('Tipo de revisión inválido.')
        from .profiles import Profiles
        profile = Profiles(self.conn).get(reviewer)
        if 'reviewer' not in profile['roles'] or (kind == 'security' and 'security-review' not in profile['capabilities']):
            raise ValueError('El perfil no puede realizar esta revisión.')
        worker = self.conn.execute("SELECT profile FROM executions WHERE task=? AND role='worker' ORDER BY id DESC LIMIT 1", (number(ident),)).fetchone()
        if worker and worker[0] == reviewer:
            raise ValueError('El worker no puede aprobar su propio trabajo.')
        if not isinstance(result, dict) or result.get('verdict') not in ('approve', 'reject') or not isinstance(result.get('issues'), list):
            raise ValueError('La revisión debe contener verdict e issues estructurados.')
        fields(result,('verdict','issues'),'review result')
        if len(result['issues'])>1000:
            raise ValueError('Demasiados issues de revisión.')
        for issue in result['issues']:
            fields(issue,('severity','file','line','message'),'review issue')
            if not isinstance(issue, dict) or issue.get('severity') not in ('low','medium','high','critical'):
                raise ValueError('Issue de revisión inválido.')
            text(issue.get('message'), 'issue.message', 5000)
            if issue.get('file') is not None:
                relative(issue['file'])
            if issue.get('line') is not None and (type(issue['line']) is not int or issue['line'] < 1):
                raise ValueError('La línea debe ser un entero positivo.')
        if result['verdict'] == 'approve' and any(i['severity'] in ('high','critical') for i in result['issues']):
            raise ValueError('No se puede aprobar una revisión con issues high/critical.')
        fingerprint = self.workspaces.fingerprint(ident)
        with self.conn:
            self.conn.execute('INSERT INTO reviews(task,fingerprint,reviewer,verdict,issues,kind,created) VALUES (?,?,?,?,?,?,?)',
                              (number(ident), fingerprint, reviewer, result['verdict'], json.dumps(result['issues'], ensure_ascii=False), kind, int(time.time())))
            TaskStore(self.conn).event(ident, 'review.'+result['verdict'], {'reviewer': reviewer, 'kind': kind, 'fingerprint': fingerprint})
            if worker:
                self.conn.execute('UPDATE agent_metrics SET review_rejected=? WHERE execution=(SELECT id FROM executions WHERE task=? AND role=\'worker\' ORDER BY id DESC LIMIT 1)',
                                  (int(result['verdict']=='reject'), number(ident)))
        return {'task': ident, 'reviewer': reviewer, 'fingerprint': fingerprint, 'kind': kind, **result}

    def gate(self, ident):
        task = TaskStore(self.conn).get(ident)
        fingerprint = self.workspaces.fingerprint(ident)
        check = self.conn.execute('SELECT passed FROM verifications WHERE task=? AND fingerprint=? ORDER BY id DESC LIMIT 1', (number(ident), fingerprint)).fetchone()
        missing = [] if check and check[0] else ['verification']
        required=set(['code','security'] if task.contract['complexity']=='critical' else ['code'] if task.contract['review']['required'] else [])
        required.update(row[0] for row in self.conn.execute('SELECT DISTINCT kind FROM reviews WHERE task=? AND fingerprint=?',(number(ident),fingerprint)))
        for kind in sorted(required):
            review = self.conn.execute('SELECT verdict FROM reviews WHERE task=? AND fingerprint=? AND kind=? ORDER BY id DESC LIMIT 1', (number(ident), fingerprint, kind)).fetchone()
            if not review or review[0] != 'approve':
                missing.append(kind+' review')
        if task.contract['complexity']=='critical' and not Policies(self.conn).approved(ident,'critical-merge',fingerprint):
            missing.append('human approval')
        return {'task': ident, 'passed': not missing, 'missing': missing, 'fingerprint': fingerprint}
