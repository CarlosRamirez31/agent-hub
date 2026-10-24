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


def read_chats(home):
    """Read the newest compatible local index, including paginated-history chats.

    This is an internal Codex schema: fail visibly if a future version changes it.
    No transcript, tool output, token, or credential is read.
    """
    databases = sorted(
        Path(home).glob("state_*.sqlite"),
        key=lambda p: int(p.stem.split("_")[-1]) if p.stem.split("_")[-1].isdigit() else -1,
        reverse=True,
    )
    if not databases:
        return []
    with closing(sqlite3.connect(databases[0].resolve().as_uri() + "?mode=ro", uri=True, timeout=2)) as conn:
        conn.execute("PRAGMA query_only=ON")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(threads)")}
        if not {"id", "title", "cwd", "updated_at", "archived"} <= columns:
            raise ValueError("El índice de Codex cambió; actualiza codex-hub. No se modificó la base.")
        rows = conn.execute(
            "SELECT id, title, cwd, updated_at, archived FROM threads ORDER BY updated_at DESC"
        ).fetchall()
    chats = []
    for ident, title, cwd, updated, archived in rows:
        try:
            uuid.UUID(ident)
            chats.append(Chat(ident, title or "Sin título", cwd, int(updated), bool(archived)))
        except (ValueError, TypeError, AttributeError):
            continue
    return chats


class Library:
    """User organization lives separately from Codex and is written atomically."""

    def __init__(self, path):
        self.path = Path(path) if path is not None else None
        self.data = {"version": 1, "sections": [], "chats": {}}
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
                or not all(isinstance(v, dict) for v in data["chats"].values())):
            raise ValueError("Formato de library.json desconocido; el archivo se ha conservado.")
        self.data = data

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


def visible(chats, library, group, query="", archives=False):
    kind, value = group
    result = []
    for chat in chats:
        meta = library.meta(chat)
        if chat.archived != archives:
            continue
        if kind == "pinned" and not meta.get("pinned"):
            continue
        if kind == "project" and chat.cwd != value:
            continue
        if kind == "section" and meta.get("section") != value:
            continue
        title = meta.get("title") or chat.title
        if query.casefold() not in (title + " " + chat.cwd).casefold():
            continue
        result.append(chat)
    return sorted(result, key=lambda c: (not bool(library.meta(c).get("pinned")), -c.updated))
