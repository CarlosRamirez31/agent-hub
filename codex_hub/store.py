"""Local metadata only. Never open credentials or write to Codex databases."""

import json
import os
from pathlib import Path
import sqlite3
import tempfile
import uuid
from contextlib import closing
from dataclasses import dataclass


@dataclass(frozen=True)
class Chat:
    id: str
    title: str
    cwd: str
    updated: int
    archived: bool = False
    project_id: str = ""


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    roots: tuple
    source: str = "codex"


def index_path(home):
    databases = sorted(
        Path(home).glob("state_*.sqlite"),
        key=lambda p: int(p.stem.split("_")[-1]) if p.stem.split("_")[-1].isdigit() else -1,
        reverse=True,
    )
    return databases[0] if databases else None


def read_chats(home):
    """Read the newest compatible local index, including paginated-history chats.

    This is an internal Codex schema: fail visibly if a future version changes it.
    No transcript, tool output, token, or credential is read.
    """
    database = index_path(home)
    if database is None:
        return []
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)) as conn:
        conn.execute("PRAGMA query_only=ON")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(threads)")}
        if not {"id", "title", "cwd", "updated_at", "archived"} <= columns:
            raise ValueError("El índice de Codex cambió; actualiza codex-hub. No se modificó la base.")
        project_column = "project_id" if "project_id" in columns else "''"
        rows = conn.execute(
            "SELECT id, title, cwd, updated_at, archived, " + project_column +
            " FROM threads ORDER BY updated_at DESC"
        ).fetchall()
    chats = []
    for ident, title, cwd, updated, archived, project_id in rows:
        try:
            uuid.UUID(ident)
            chats.append(Chat(ident, title or "Sin título", cwd, int(updated), bool(archived), project_id or ""))
        except (ValueError, TypeError, AttributeError):
            continue
    return chats


def read_projects(home):
    """Import saved names and ordered roots, including projects without chats."""
    database = index_path(home)
    if database is None:
        return []
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)) as conn:
        conn.execute("PRAGMA query_only=ON")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"projects", "project_roots"} <= tables:
            return []  # Older Codex versions only indexed conversations.
        for table, required in (("projects", {"id", "name", "position"}),
                                ("project_roots", {"project_id", "path", "position"})):
            columns = {r[1] for r in conn.execute("PRAGMA table_info(" + table + ")")}
            if not required <= columns:
                raise ValueError("El índice de proyectos de Codex cambió; no se modificó la base.")
        projects = conn.execute("SELECT id, name FROM projects ORDER BY position, id").fetchall()
        roots = conn.execute("SELECT project_id, path FROM project_roots ORDER BY position").fetchall()
    paths = {}
    for ident, path in roots:
        if isinstance(path, str) and path:
            paths.setdefault(ident, []).append(normalize(path))
    return [Project(ident, name, tuple(dict.fromkeys(paths.get(ident, []))))
            for ident, name in projects if isinstance(ident, str) and isinstance(name, str)]


def normalize(path):
    return str(Path(path).expanduser().resolve())


def project_for(chat, projects):
    """Explicit project membership wins; otherwise use the deepest matching root."""
    explicit = next((p for p in projects if p.id == chat.project_id), None)
    if explicit:
        return explicit.id
    cwd = Path(normalize(chat.cwd))
    matches = [(len(Path(root).parts), p.id) for p in projects for root in p.roots
               if cwd == Path(root) or Path(root) in cwd.parents]
    return max(matches, key=lambda item: item[0])[1] if matches else None


def project_catalog(chats, imported, library):
    """Keep saved projects first; discover unmatched working folders separately."""
    projects = list(imported)
    known = {root for project in projects for root in project.roots}
    for record in library.data["projects"]:
        root = normalize(record["path"])
        if root not in known:
            projects.append(Project("folder:" + root, record["name"], (root,), "local"))
            known.add(root)
    # Discover parents first so /repo/subdir does not produce duplicate projects.
    unassigned = {normalize(c.cwd) for c in chats if not project_for(c, projects)}
    for cwd in sorted(unassigned, key=lambda p: (len(Path(p).parts), p)):
        candidate = Chat("", "", cwd, 0)
        if not project_for(candidate, projects):
            projects.append(Project("folder:" + cwd, Path(cwd).name or cwd, (cwd,), "discovered"))
    return projects


class Library:
    """User organization lives separately from Codex and is written atomically."""

    def __init__(self, path):
        self.path = Path(path) if path is not None else None
        self.data = {"version": 1, "sections": [], "chats": {}, "projects": []}
        if self.path is None:
            return
        try:
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            return
        if (not isinstance(data, dict) or data.get("version") != 1
                or not isinstance(data.get("sections"), list)
                or not all(isinstance(s, str) for s in data["sections"])
                or not isinstance(data.get("chats"), dict)
                or not all(isinstance(v, dict) for v in data["chats"].values())
                or not isinstance(data.get("projects", []), list)
                or not all(isinstance(p, dict) and isinstance(p.get("name"), str)
                           and isinstance(p.get("path"), str) and bool(p["path"])
                           for p in data.get("projects", []))):
            raise ValueError("Formato de library.json desconocido; el archivo se ha conservado.")
        self.data = data
        self.data.setdefault("projects", [])

    def add_project(self, path, name=None):
        root = normalize(path)
        if not Path(root).is_dir():
            raise ValueError("La carpeta no existe: " + root)
        if not any(normalize(p["path"]) == root for p in self.data["projects"]):
            self.data["projects"].append({"path": root, "name": name or Path(root).name or root})
            self.save()
        return "folder:" + root

    def meta(self, chat):
        return self.data["chats"].get(chat.id, {})

    def change(self, chat, **values):
        self.data["chats"].setdefault(chat.id, {}).update(values)
        self.save()

    def add_section(self, name):
        name = name.strip()
        if name and name not in self.data["sections"]:
            self.data["sections"].append(name)
            self.save()

    def save(self):
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix=".library-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(self.data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def visible(chats, library, group, query="", archives=False, projects=None):
    kind, value = group
    result = []
    for chat in chats:
        meta = library.meta(chat)
        if chat.archived != archives:
            continue
        if kind == "pinned" and not meta.get("pinned"):
            continue
        if kind == "project":
            member = project_for(chat, projects) == value if projects is not None else chat.cwd == value
            if not member:
                continue
        if kind == "section" and meta.get("section") != value:
            continue
        title = meta.get("title") or chat.title
        if query.casefold() not in (title + " " + chat.cwd).casefold():
            continue
        result.append(chat)
    if kind == "recent":
        return sorted(result, key=lambda c: -c.updated)
    return sorted(result, key=lambda c: (not bool(library.meta(c).get("pinned")), -c.updated))
