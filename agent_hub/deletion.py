"""Explicit native deletion and reviewed cross-agent directory removal."""
from pathlib import Path
import os
import shutil
import sqlite3

from .store import normalize


def inside(path, roots):
    path = Path(normalize(path))
    return any(path == root or root in path.parents for root in roots)


def forget(manager, agent_id, chat):
    """Remove only our normalized records after native deletion succeeded."""
    conn = manager.cache.conn
    transfers = [dict(row) for row in conn.execute(
        "SELECT * FROM transfers WHERE target_agent=? AND (id=? OR native_id=?)", (agent_id, chat.id, chat.id))]
    with conn:
        conn.execute("DELETE FROM conversations WHERE agent=? AND id=?", (agent_id, chat.id))
        conn.execute("DELETE FROM transfers WHERE target_agent=? AND (id=? OR native_id=?)", (agent_id, chat.id, chat.id))
    library = manager.library(agent_id)
    for ident in [chat.id, *(t['id'] for t in transfers)]:
        library.data['chats'].pop(ident, None)
    library.save()
    for transfer in transfers:
        # Only our exact private export directory; never follow a stored arbitrary path.
        directory = manager.state/'handoffs'/transfer['id']
        if directory.is_dir() and not directory.is_symlink():
            shutil.rmtree(directory)


def delete_chat(manager, agent_id, chat, confirmed=False):
    if not confirmed:
        raise ValueError("Falta confirmar la eliminación.")
    agent = manager.agent(agent_id)
    transfer = manager.cache.transfer(chat.id)
    prepared = transfer and transfer['target_agent'] == agent_id and not transfer['native_id']
    if prepared and transfer['status'] != 'prepared':
        raise ValueError("Esta continuación se inició sin enlazar su sesión. Enlázala antes de borrarla.")
    if not prepared:
        agent.delete_conversation(chat.id, chat.cwd)
        chats, _ = agent.index(include_hidden=True)
        if any(c.id == chat.id for c in chats):
            raise ValueError(agent.name + ": el agente todavía devuelve la conversación; no se confirmó su eliminación.")
    forget(manager, agent_id, chat)


def checked_roots(manager, paths):
    requested = [Path(path).expanduser().absolute() for path in paths]
    if any(path.is_symlink() or path.resolve() != path for path in requested):
        raise ValueError("La ruta cambió o contiene enlaces simbólicos; vuelve a revisar la carpeta.")
    roots = sorted(set(requested), key=lambda p: (len(p.parts), str(p)))
    roots = [root for i, root in enumerate(roots) if not any(parent in root.parents for parent in roots[:i])]
    if not roots:
        raise ValueError("La carpeta no tiene rutas físicas para eliminar.")
    protected = [Path.home().resolve(), manager.state.resolve(), Path(__file__).resolve().parents[1],
                 *[Path(a.host_root).resolve() if a.container else Path(a.home).expanduser().resolve()
                   for a in manager.agents if a.home]]
    system_roots = {Path(p).resolve() for p in ("/bin", "/sbin", "/etc", "/usr", "/var", "/boot", "/dev", "/proc", "/sys", "/run", "/lib", "/lib64", "/opt")}
    for root in roots:
        if root in system_roots or root == Path(root.anchor) or any(root == p or root in p.parents for p in protected):
            raise ValueError("No se permite borrar una raíz del sistema, tu home, Agent Hub o los historiales: " + str(root))
        if root.is_symlink() or (root.exists() and not root.is_dir()) or os.path.ismount(root):
            raise ValueError("La ruta debe ser un directorio normal, sin montajes: " + str(root))
        if root.exists():
            def failed(error):
                raise error
            for directory, children, _ in os.walk(root, followlinks=False, onerror=failed):
                for name in children:
                    if os.path.ismount(Path(directory)/name):
                        raise ValueError("La carpeta contiene otro montaje; no se puede eliminar desde el hub.")
    return roots


def folder_plan(manager, agent_id, folder_id):
    manager.sync()
    if manager.errors:
        raise ValueError("No se puede revisar todos los agentes: " + "; ".join(manager.errors.values()))
    _, projects = manager.snapshot(agent_id)
    project = next((p for p in projects if p.id == folder_id), None)
    if not project:
        raise ValueError("El proyecto ya no existe.")
    roots = checked_roots(manager, project.roots)
    conversations, projects_to_remove = [], []
    for agent in manager.agents:
        chats, projects = manager.snapshot(agent.id)
        native_chats, _ = agent.index(include_hidden=True)
        chats = list({c.id: c for c in [*native_chats, *chats]}.values())
        associated = {p.id for p in projects if p.roots and all(inside(path, roots) for path in p.roots)}
        for chat in chats:
            if inside(chat.cwd, roots) or chat.project_id in associated:
                transfer = manager.cache.transfer(chat.id)
                if not transfer or transfer['native_id']:
                    agent.check_delete()
                elif transfer['status'] != 'prepared':
                    raise ValueError("Hay una continuación sin ID nativo enlazado; enlázala antes de eliminar la carpeta.")
                conversations.append((agent.id, chat))
        for entry in projects:
            if entry.roots and all(inside(path, roots) for path in entry.roots):
                projects_to_remove.append((agent.id, entry))
    fingerprints = {str(root): (root.stat().st_dev, root.stat().st_ino) if root.exists() else None for root in roots}
    return {'agent': agent_id, 'folder': folder_id, 'name': project.name, 'roots': [str(r) for r in roots],
            'conversations': conversations, 'projects': projects_to_remove, 'fingerprints': fingerprints}


def delete_folder(manager, plan, confirmed=False):
    if not confirmed:
        raise ValueError("Falta confirmar la eliminación de la carpeta y sus archivos.")
    fresh = folder_plan(manager, plan['agent'], plan['folder'])
    def scope(value):
        return (value['roots'], value['fingerprints'],
                sorted((agent, chat.id) for agent, chat in value['conversations']),
                sorted((agent, p.id, p.roots) for agent, p in value['projects']))
    if scope(fresh) != scope(plan):
        raise ValueError("La carpeta o sus conversaciones cambiaron; revisa una nueva confirmación.")
    deleted = 0
    try:
        for agent_id, chat in fresh['conversations']:
            # An earlier native delete may have cascaded to a delegate session.
            current, _ = manager.agent(agent_id).index(include_hidden=True)
            transfer = manager.cache.transfer(chat.id)
            if any(c.id == chat.id for c in current) or (transfer and not transfer['native_id']):
                delete_chat(manager, agent_id, chat, confirmed=True)
            else:
                forget(manager, agent_id, chat)
            deleted += 1
        for agent_id, project in fresh['projects']:
            agent = manager.agent(agent_id)
            if agent.kind == 'codex' and project.source == 'codex':
                agent.delete_project(project.id)
        if inside(Path.cwd(), [Path(r) for r in fresh['roots']]):
            os.chdir(Path.home())
        for root in checked_roots(manager, fresh['roots']):
            fingerprint = (root.stat().st_dev, root.stat().st_ino) if root.exists() else None
            if fingerprint != fresh['fingerprints'][str(root)]:
                raise ValueError('El directorio cambió durante la eliminación; no se borraron sus archivos: ' + str(root))
            if root.exists():
                shutil.rmtree(root)
        for agent in manager.agents:
            library = manager.library(agent.id)
            library.data['projects'] = [p for p in library.data['projects'] if not inside(p['path'], [Path(r) for r in fresh['roots']])]
            removed = library.data.setdefault('removed_projects', [])
            for ident, project in fresh['projects']:
                if ident == agent.id and project.id not in removed:
                    removed.append(project.id)
            library.save()
        manager.sync()
    except (OSError, ValueError, sqlite3.Error) as error:
        raise ValueError(f"Eliminación parcial: {deleted} conversaciones eliminadas. {error}") from error
    return deleted
