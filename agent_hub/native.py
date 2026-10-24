"""Read-only local history readers. No provider SDKs, credentials or network."""

from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3

from .store import Chat, Project, read_chats, read_projects

MAX_FILE = 32 * 1024 * 1024


def text_content(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(x.get("text", "") for x in value if isinstance(x, dict)
                         and x.get("type") in ("text", "input_text", "output_text"))
    return ""


def timestamp(value):
    if isinstance(value, (int, float)):
        return int(value / 1000 if value > 10**11 else value)
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def load_json(path):
    if path.stat().st_size > MAX_FILE:
        raise ValueError("Historial demasiado grande: " + str(path))
    return json.loads(path.read_text())


def json_lines(path):
    with path.open() as stream:
        for line in stream:
            if len(line) > MAX_FILE:
                raise ValueError("Entrada de historial demasiado grande.")
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # A writer may still be completing the final line.
            if isinstance(row, dict):
                yield row


def read_index(kind, home):
    home = Path(home).expanduser()
    if kind == "codex":
        return read_chats(home), read_projects(home)
    if kind == "hermes":
        db = home / "state.db"
        if not db.exists():
            return [], []
        with closing(sqlite3.connect(db.resolve().as_uri()+"?mode=ro", uri=True, timeout=3)) as conn:
            conn.execute("PRAGMA query_only=ON")
            columns = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
            if not {"id", "title", "cwd", "started_at"} <= columns:
                raise ValueError("El formato del índice de Hermes cambió.")
            updated = "COALESCE(last_activity_at, started_at)" if "last_activity_at" in columns else "started_at"
            archived = "archived" if "archived" in columns else "0"
            condition = " WHERE hidden=0" if "hidden" in columns else ""
            rows = conn.execute(f"SELECT id,title,cwd,{updated},{archived} FROM sessions" + condition).fetchall()
        return [Chat(str(i), title or "Hermes", cwd or str(Path.home()), timestamp(t), bool(a))
                for i, title, cwd, t, a in rows], []
    if kind == "claude":
        result = {}
        # history.jsonl provides a lightweight index without reading tool outputs.
        history = home / "history.jsonl"
        if history.exists():
            for row in json_lines(history):
                ident, cwd = row.get("sessionId"), row.get("project")
                if ident and cwd:
                    result[ident] = Chat(ident, str(row.get("display") or "Claude")[:240], cwd, timestamp(row.get("timestamp")))
        for path in home.glob("projects/*/sessions-index.json"):
            for row in load_json(path).get("entries", []):
                ident, cwd = row.get("sessionId"), row.get("projectPath")
                if ident and cwd:
                    result[ident] = Chat(ident, row.get("summary") or row.get("firstPrompt") or "Claude", cwd,
                                         timestamp(row.get("modified") or row.get("created")))
        # CLI builds without sessions-index still have direct session JSONL files.
        for path in home.glob("projects/*/*.jsonl"):
            if path.stem in result:
                continue
            for row in json_lines(path):
                if row.get("cwd") and not row.get("isSidechain"):
                    result[path.stem] = Chat(path.stem, "Claude · " + path.stem[:8], row["cwd"], int(path.stat().st_mtime))
                    break
        return list(result.values()), []
    if kind == "gemini":
        result = []
        mapping = {}
        projects = home / "projects.json"
        if projects.exists():
            data = load_json(projects)
            for path, ident in data.get("projects", data).items():
                if isinstance(path, str) and isinstance(ident, str):
                    mapping[ident] = path
        for path in home.glob("tmp/*/chats/session-*.json"):
            data = load_json(path)
            cwd = data.get("cwd") or data.get("projectRoot") or mapping.get(path.parents[1].name)
            marker = path.parents[1] / ".project_root"
            if not cwd and marker.exists():
                cwd = marker.read_text().strip()
            if not cwd:
                continue  # Never guess the working directory of an external route.
            ident = data.get("sessionId")
            if ident:
                title = data.get("summary") or next((m.get("content") for m in data.get("messages", [])
                                                      if m.get("type") == "user" and isinstance(m.get("content"), str)), "Gemini")
                result.append(Chat(ident, title[:240], cwd, timestamp(data.get("lastUpdated"))))
        return result, []
    if kind == "opencode":
        db = home / "opencode.db"
        if not db.exists():
            return [], []
        with closing(sqlite3.connect(db.resolve().as_uri()+"?mode=ro", uri=True, timeout=3)) as conn:
            conn.execute("PRAGMA query_only=ON")
            columns = {r[1] for r in conn.execute("PRAGMA table_info(session)")}
            if not {"id", "title", "directory", "time_updated"} <= columns:
                raise ValueError("OpenCode: usa un índice normalizado para esta versión del almacenamiento.")
            rows = conn.execute("SELECT id,title,directory,time_updated FROM session").fetchall()
        return [Chat(i, t, cwd, timestamp(updated)) for i, t, cwd, updated in rows], []
    if kind == "normalized":
        path = home / "index.json"
        if not path.exists():
            return [], []
        data = load_json(path)
        if data.get("version") != 1:
            raise ValueError("El índice normalizado debe tener version: 1.")
        chats = [Chat(str(c["id"]), c.get("title") or str(c["id"]), c["cwd"], timestamp(c.get("updated", 0)),
                      bool(c.get("archived", False)), c.get("project_id", "")) for c in data.get("conversations", [])]
        projects = [Project(str(p["id"]), p["name"], tuple(p["roots"])) for p in data.get("projects", [])]
        return chats, projects
    raise ValueError("Lector desconocido: " + kind)


def read_messages(kind, home, ident):
    """Only visible user/assistant text; never return system/tool/thinking fields."""
    home = Path(home).expanduser()
    if kind == "codex":
        from .rpc import codex_messages
        return codex_messages(home, ident)
    if kind == "hermes":
        with closing(sqlite3.connect((home/"state.db").resolve().as_uri()+"?mode=ro", uri=True, timeout=3)) as conn:
            conn.execute("PRAGMA query_only=ON")
            columns = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
            active = " AND active=1" if "active" in columns else ""
            rows = conn.execute("SELECT role,content FROM messages WHERE session_id=? AND role IN ('user','assistant')" + active + " ORDER BY id", (ident,)).fetchall()
        return [{"role": r, "text": text_content(c)} for r, c in rows if text_content(c)]
    if kind == "claude":
        paths = list(home.glob("projects/*/"+ident+".jsonl"))
        if not paths:
            raise ValueError("No se encontró el historial de Claude.")
        messages, seen = [], set()
        for row in json_lines(paths[0]):
            role = row.get("type")
            content = text_content(row.get("message", {}).get("content"))
            key = row.get("uuid")
            if role in ("user", "assistant") and content and (not key or key not in seen):
                messages.append({"role": role, "text": content})
                seen.add(key)
        return messages
    if kind == "gemini":
        for path in home.glob("tmp/*/chats/session-*.json"):
            data = load_json(path)
            if data.get("sessionId") == ident:
                return [{"role": "user" if m["type"] == "user" else "assistant", "text": text_content(m.get("content"))}
                        for m in data.get("messages", []) if m.get("type") in ("user", "gemini") and text_content(m.get("content"))]
        raise ValueError("No se encontró el historial de Gemini.")
    if kind == "opencode":
        with closing(sqlite3.connect((home/"opencode.db").resolve().as_uri()+"?mode=ro", uri=True, timeout=3)) as conn:
            conn.execute("PRAGMA query_only=ON")
            rows = conn.execute("SELECT m.data,p.data FROM message m JOIN part p ON p.message_id=m.id WHERE m.session_id=? ORDER BY m.time_created,p.time_created", (ident,)).fetchall()
        result = []
        for message, part in rows:
            m, p = json.loads(message), json.loads(part)
            if m.get("role") in ("user", "assistant") and p.get("type") == "text" and not p.get("synthetic"):
                result.append({"role": m["role"], "text": p.get("text", "")})
        return result
    if kind == "normalized":
        for chat in load_json(home/"index.json").get("conversations", []):
            if str(chat["id"]) == ident:
                return [{"role": m["role"], "text": m["text"]} for m in chat.get("messages", [])
                        if m.get("role") in ("user", "assistant") and isinstance(m.get("text"), str)]
        raise ValueError("No se encontró la conversación en el índice normalizado.")
    raise ValueError("Este adaptador no exporta contexto.")
