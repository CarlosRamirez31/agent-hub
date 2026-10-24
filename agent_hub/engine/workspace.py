"""One task, one Git worktree; never reset, clean or merge the user's checkout."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from .tasks import TaskStore, number


def git(repo, *args):
    result = subprocess.run(['git', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=/dev/null', '-C', str(repo), *args], stdin=subprocess.DEVNULL,
                            capture_output=True, timeout=30, check=False)
    if result.returncode:
        raise ValueError('Git: ' + result.stderr.decode('utf-8', errors='replace').strip()[:2000])
    return result.stdout


class Workspaces:
    def __init__(self, conn, state):
        self.conn, self.state = conn, Path(state).resolve()

    def get(self, ident):
        TaskStore(self.conn).get(ident)
        row = self.conn.execute('SELECT * FROM workspaces WHERE task=?', (number(ident),)).fetchone()
        if not row:
            raise ValueError('La tarea todavía no tiene un workspace aislado.')
        value = dict(row)
        path = Path(value['path'])
        if not path.is_dir() or path.resolve() != path:
            raise ValueError('El workspace ya no está disponible o cambió de ubicación.')
        actual = git(path, 'rev-parse', '--show-toplevel').decode().strip()
        if actual != str(path):
            raise ValueError('El workspace ya no es el worktree registrado.')
        if git(path, 'branch', '--show-current').decode().strip() != value['branch']:
            raise ValueError('La rama del workspace cambió; requiere revisión humana.')
        return value

    def create(self, ident, repo, ref='HEAD'):
        store = TaskStore(self.conn)
        with store.transaction():
            task = store.get(ident)
            if task.status not in ('pending', 'ready', 'blocked', 'waiting_human'):
                raise ValueError('Prepara el workspace antes de ejecutar.')
            if self.conn.execute('SELECT 1 FROM workspaces WHERE task=?', (number(ident),)).fetchone():
                return self.get(ident)
            root = Path(repo).expanduser().resolve()
            root = Path(git(root, 'rev-parse', '--show-toplevel').decode().strip())
            if not isinstance(ref, str) or not ref or ref.startswith('-') or '\0' in ref:
                raise ValueError('Referencia Git no válida.')
            base = git(root, 'rev-parse', '--verify', ref + '^{commit}').decode().strip()
            directory = self.state/'worktrees'
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if directory.is_symlink():
                raise ValueError('El directorio de worktrees no debe ser un enlace.')
            path = directory/ident
            branch = 'agent-hub/' + ident.lower()
            git(root, 'worktree', 'add', '-b', branch, str(path), base)
            try:
                self.conn.execute('INSERT INTO workspaces VALUES (?,?,?,?,?)', (number(ident), str(root), str(path), branch, base))
                store.event(ident, 'workspace.created', {'repo': str(root), 'path': str(path), 'base': base, 'branch': branch})
            except BaseException:
                # Preserve files and branch after any uncertain DB error. Never remove
                # a worktree that another operation might already be inspecting.
                raise
        return self.get(ident)

    def fingerprint(self, ident):
        workspace = self.get(ident)
        path = Path(workspace['path'])
        digest = hashlib.sha256()
        digest.update(json.dumps(TaskStore(self.conn).get(ident).contract, sort_keys=True, ensure_ascii=False).encode())
        digest.update(workspace['base'].encode())
        # Hash content, permissions and symlinks, not staging/commit metadata.
        # A human commit of exactly the verified bytes does not invalidate checks.
        entries = set(git(path, 'ls-files', '-z').split(b'\0'))
        entries.update(git(path, 'ls-files', '--others', '-z').split(b'\0'))
        for raw in sorted(entries - {b''}):
            file = path/os.fsdecode(raw)
            digest.update(len(raw).to_bytes(8, 'big'));digest.update(raw)
            if file.is_symlink():
                digest.update(b'link:');digest.update(os.fsencode(os.readlink(file)))
            elif file.is_file():
                digest.update(b'file:');digest.update(str(file.stat().st_mode & 0o777).encode())
                with file.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(65536), b''):
                        digest.update(chunk)
            else:
                digest.update(b'missing')
            digest.update(b'\0END')
        return digest.hexdigest()

    def changed_files(self, ident):
        workspace = self.get(ident)
        path = workspace['path']
        data = git(path, 'diff', '--no-ext-diff', '--no-textconv', '--name-only', '-z', workspace['base'], '--')
        data += git(path, 'ls-files', '--others', '-z')
        return sorted({os.fsdecode(p) for p in data.split(b'\0') if p})

    def commit(self, ident, message):
        from .policy import Policies
        from .quality import Quality
        task = TaskStore(self.conn).get(ident)
        workspace = self.get(ident)
        fingerprint = self.fingerprint(ident)
        policy = Policies(self.conn)
        if not task.contract['permissions']['git_commit'] or not policy.get(task.contract.get('policy','default'))['git_commit']:
            raise ValueError('Commit no permitido por contrato/policy.')
        if not policy.approved(ident, 'git-commit', fingerprint):
            raise ValueError('Falta aprobación humana para este commit.')
        if not Quality(self.conn, self.state).gate(ident)['passed']:
            raise ValueError('Los quality gates deben pasar antes de commit.')
        if not isinstance(message, str) or not message.strip() or '\0' in message:
            raise ValueError('Mensaje de commit inválido.')
        # This worktree is owned by the task, never the user's working checkout.
        git(workspace['path'], 'add', '--all', '--', '.')
        git(workspace['path'], 'commit', '-m', message)
        head = git(workspace['path'], 'rev-parse', 'HEAD').decode().strip()
        with self.conn:
            TaskStore(self.conn).event(ident, 'workspace.committed', {'head': head, 'fingerprint': fingerprint})
        return {'task': ident, 'head': head}

    def merge(self, ident):
        from .policy import Policies
        from .quality import Quality
        workspace = self.get(ident)
        fingerprint = self.fingerprint(ident)
        if TaskStore(self.conn).get(ident).status != 'done':
            raise ValueError('Solo se integra una tarea terminada.')
        if not Quality(self.conn, self.state).gate(ident)['passed']:
            raise ValueError('Los quality gates no corresponden al trabajo actual.')
        if not Policies(self.conn).approved(ident, 'merge', fingerprint):
            raise ValueError('Falta aprobación humana de merge para este trabajo.')
        for path in (workspace['repo'], workspace['path']):
            if git(path, 'status', '--porcelain').strip():
                raise ValueError('Commit/revisión pendientes: se requiere un checkout limpio para integrar.')
        branch = git(workspace['repo'], 'branch', '--show-current').decode().strip()
        if not branch or branch == workspace['branch']:
            raise ValueError('Selecciona una rama de integración distinta, sin detached HEAD.')
        git(workspace['repo'], 'merge', '--ff-only', workspace['branch'])
        with self.conn:
            TaskStore(self.conn).event(ident, 'workspace.merged', {'branch': branch, 'fingerprint': fingerprint})
        return {'task': ident, 'branch': branch, 'merged': True}
