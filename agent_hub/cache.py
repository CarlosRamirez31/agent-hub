"""Private normalized index. Successful snapshots reconcile; failures preserve data."""

from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3
import time

from .store import Chat, Project


class Cache:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.conn = sqlite3.connect(self.path, timeout=5)
        os.chmod(self.path, 0o600)
        self.conn.row_factory = sqlite3.Row
        if self.conn.execute("PRAGMA user_version").fetchone()[0] > 1:
            self.conn.close()
            raise ValueError("La base de Agent Hub pertenece a una versión más nueva.")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS agents (id TEXT PRIMARY KEY, name TEXT, available INT, synced INT, error TEXT);
            CREATE TABLE IF NOT EXISTS agent_sources (agent TEXT PRIMARY KEY, reader TEXT, home TEXT, container TEXT);
            CREATE TABLE IF NOT EXISTS projects (agent TEXT, id TEXT, name TEXT, roots TEXT, source TEXT,
                PRIMARY KEY(agent,id));
            CREATE TABLE IF NOT EXISTS conversations (agent TEXT, id TEXT, title TEXT, cwd TEXT, updated INT,
                archived INT, project_id TEXT, PRIMARY KEY(agent,id));
            CREATE TABLE IF NOT EXISTS messages (agent TEXT, conversation TEXT, ordinal INT, role TEXT, text TEXT,
                PRIMARY KEY(agent,conversation,ordinal), FOREIGN KEY(agent,conversation)
                REFERENCES conversations(agent,id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS transfers (id TEXT PRIMARY KEY, source_agent TEXT, source_chat TEXT,
                target_agent TEXT, project_id TEXT, project_name TEXT, cwd TEXT, title TEXT,
                context_path TEXT, native_id TEXT, status TEXT, created INT);
            PRAGMA user_version=1;
        """)

    def close(self):
        self.conn.close()

    def record_error(self, agent, error):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO agent_sources VALUES (?,?,?,?)", (agent.id, agent.kind, agent.home, agent.container))
            self.conn.execute("INSERT INTO agents VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET error=excluded.error, available=excluded.available",
                              (agent.id, agent.name, int(agent.available), 0, str(error)))

    def sync(self, agent, chats, projects):
        previous_chats = {r["id"]: dict(r) for r in self.conn.execute("SELECT * FROM conversations WHERE agent=?", (agent.id,))}
        previous_projects = {r["id"]: dict(r) for r in self.conn.execute("SELECT * FROM projects WHERE agent=?", (agent.id,))}
        seen_chats, seen_projects = set(), set()
        changed = deleted = 0
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO agent_sources VALUES (?,?,?,?)", (agent.id, agent.kind, agent.home, agent.container))
            for chat in chats:
                seen_chats.add(chat.id)
                row = {"agent": agent.id, **asdict(chat), "archived": int(chat.archived)}
                if previous_chats.get(chat.id) != row:
                    self.conn.execute("INSERT INTO conversations VALUES (:agent,:id,:title,:cwd,:updated,:archived,:project_id) ON CONFLICT(agent,id) DO UPDATE SET title=excluded.title,cwd=excluded.cwd,updated=excluded.updated,archived=excluded.archived,project_id=excluded.project_id", row)
                    changed += 1
            for project in projects:
                seen_projects.add(project.id)
                row = {"agent": agent.id, "id": project.id, "name": project.name,
                       "roots": json.dumps(list(project.roots)), "source": project.source}
                if previous_projects.get(project.id) != row:
                    self.conn.execute("INSERT INTO projects VALUES (:agent,:id,:name,:roots,:source) ON CONFLICT(agent,id) DO UPDATE SET name=excluded.name,roots=excluded.roots,source=excluded.source", row)
                    changed += 1
            for ident in previous_chats.keys()-seen_chats:
                self.conn.execute("DELETE FROM conversations WHERE agent=? AND id=?", (agent.id, ident))
                deleted += 1
            for ident in previous_projects.keys()-seen_projects:
                self.conn.execute("DELETE FROM projects WHERE agent=? AND id=?", (agent.id, ident))
                deleted += 1
            self.conn.execute("INSERT INTO agents VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,available=excluded.available,synced=excluded.synced,error=excluded.error",
                              (agent.id, agent.name, int(agent.available), int(time.time()), ""))
        return {"changed": changed, "deleted": deleted, "conversations": len(seen_chats), "projects": len(seen_projects)}

    def snapshot(self, agent):
        chats = {r["id"]: Chat(r["id"], r["title"], r["cwd"], r["updated"], bool(r["archived"]), r["project_id"])
                 for r in self.conn.execute("SELECT * FROM conversations WHERE agent=?", (agent,))}
        projects = {r["id"]: Project(r["id"], r["name"], tuple(json.loads(r["roots"])), r["source"])
                    for r in self.conn.execute("SELECT * FROM projects WHERE agent=?", (agent,))}
        for transfer in self.conn.execute("SELECT * FROM transfers WHERE target_agent=?", (agent,)):
            native = chats.get(transfer["native_id"])
            if transfer["native_id"] and native is None:
                continue  # A subsequently deleted native destination stays deleted.
            existing = projects.get(transfer["project_id"])
            projects[transfer["project_id"]] = Project(transfer["project_id"], transfer["project_name"],
                                                       existing.roots if existing else (transfer["cwd"],),
                                                       existing.source if existing else "local")
            if native:
                chats[native.id] = Chat(native.id, native.title, native.cwd, native.updated, native.archived, transfer["project_id"])
            else:
                chats[transfer["id"]] = Chat(transfer["id"], transfer["title"], transfer["cwd"], transfer["created"], False, transfer["project_id"])
        return list(chats.values()), list(projects.values())

    def messages(self, agent, conversation, values=None):
        if values is not None:
            filtered = [(agent, conversation, i, m["role"], m["text"]) for i, m in enumerate(values)
                        if m.get("role") in ("user", "assistant") and isinstance(m.get("text"), str)]
            with self.conn:
                self.conn.execute("DELETE FROM messages WHERE agent=? AND conversation=?", (agent, conversation))
                self.conn.executemany("INSERT INTO messages VALUES (?,?,?,?,?)", filtered)
        return [{"role": r["role"], "text": r["text"]} for r in self.conn.execute(
            "SELECT role,text FROM messages WHERE agent=? AND conversation=? ORDER BY ordinal", (agent, conversation))]

    def transfer(self, ident):
        row = self.conn.execute("SELECT * FROM transfers WHERE id=?", (ident,)).fetchone()
        return dict(row) if row else None
