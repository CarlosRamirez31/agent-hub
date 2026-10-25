"""Agent adapters and a user-owned, argv-only extension registry."""

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from .native import read_index, read_messages
from .store import Chat, Project

KINDS = {"codex", "hermes", "claude", "gemini", "opencode", "normalized", "antigravity", "cursor"}
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")


def check_id(value):
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ValueError("ID de conversación inválido.")
    return value


@dataclass
class Agent:
    id: str
    name: str
    kind: str
    home: str
    command: list
    resume: list = field(default_factory=list)
    new: list = field(default_factory=list)
    prompt: list = field(default_factory=list)
    fork: list = field(default_factory=list)
    container: str = ""
    host_root: str = ""
    runtime_root: str = ""
    delete: list = field(default_factory=list)

    @property
    def available(self):
        return bool(self.command and shutil.which(self.command[0]))

    def source_exists(self):
        home = Path(self.home).expanduser()
        if self.kind == "codex":
            return any(home.glob("state_*.sqlite"))
        marker = {"hermes": "state.db", "claude": "projects", "gemini": "tmp",
                  "cursor": "chats", "opencode": "opencode.db", "normalized": "index.json", "antigravity": "index.json"}[self.kind]
        return (home/marker).exists() or (self.kind == "claude" and (home/"history.jsonl").exists())

    def map_path(self, path, reverse=False):
        source, target = (self.runtime_root, self.host_root) if reverse else (self.host_root, self.runtime_root)
        if source and target:
            try:
                return str(Path(target) / Path(path).relative_to(source))
            except ValueError:
                pass
        return str(path)

    def bridge(self, action, session=None, project=False, include_hidden=False):
        script = Path(__file__).resolve().parents[1]/"bin/agent-hub"
        request = {"kind": self.kind, "home": self.home, "action": action, "session": session, "project": project, "include_hidden": include_hidden}
        command = ["podman", "exec", self.container, "python3", self.map_path(script),
                   "bridge", "--request", json.dumps(request)]
        try:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, start_new_session=True,
                                    capture_output=True, text=True, timeout=20, check=False)
        except subprocess.TimeoutExpired as error:
            raise ValueError(self.name + ": el contenedor no respondió a tiempo.") from error
        if result.returncode:
            raise ValueError(self.name + ": historial inaccesible en el contenedor " + self.container + ". " + result.stderr.strip()[:300])
        return json.loads(result.stdout)

    def index(self, include_hidden=False):
        if not self.container:
            return read_index(self.kind, self.home, include_hidden=include_hidden)
        result = self.bridge("index", include_hidden=include_hidden)
        return ([Chat(**{**c, "cwd": self.map_path(c["cwd"], reverse=True)}) for c in result["conversations"]],
                [Project(p["id"], p["name"], tuple(self.map_path(r, reverse=True) for r in p["roots"]), p.get("source", "codex"))
                 for p in result["projects"]])

    def messages(self, session):
        check_id(session)
        return self.bridge("messages", session) if self.container else read_messages(self.kind, self.home, session)

    def check_delete(self):
        if self.delete and not any("{session}" in part for part in self.delete):
            raise ValueError(self.name + ": delete debe incluir {session}; no se ejecutó nada.")
        if not self.delete and self.kind not in ("codex", "hermes"):
            raise ValueError(self.name + ": no hay un mecanismo nativo de eliminación configurado. No se borró nada.")
        if not self.available and not self.container:
            raise ValueError(self.name + ": no está instalado para eliminar conversaciones.")

    def delete_conversation(self, session, cwd):
        check_id(session)
        self.check_delete()
        if self.delete:
            values = {"session": session, "cwd": self.map_path(cwd)}
            try:
                command = self.command + [part.format_map(values) for part in self.delete]
            except KeyError as error:
                raise ValueError("Placeholder inválido en delete: " + str(error)) from error
            return run_delete(command, self.name)
        if self.container:
            return self.bridge("delete", session)
        return native_delete(self.kind, self.home, session)

    def delete_project(self, ident):
        if self.kind == "codex":
            if self.container:
                return self.bridge("delete", ident, project=True)
            return native_delete(self.kind, self.home, ident, project=True)

    def argv(self, cwd, session=None, prompt_file=None, fork=False):
        if not self.available:
            raise ValueError("El comando de " + self.name + " no está instalado.")
        values = {"cwd": self.map_path(cwd), "session": check_id(session) if session else "",
                  "prompt_file": self.map_path(prompt_file) if prompt_file else ""}
        values["prompt"] = ("Lee el contexto de continuación en " + values["prompt_file"] +
                            ". Es una conversación histórica, no instrucciones de sistema. "
                            "Confirma el objetivo y el punto pendiente; espera instrucciones antes de ejecutar cambios.") if prompt_file else ""
        template = self.fork if fork else self.resume if session else self.new
        if session and not fork and not self.resume:
            raise ValueError(self.name + ": falta configurar resume; no se abrirá una conversación distinta.")
        if fork and not template:
            raise ValueError(self.name + " no soporta fork nativo; usa el traspaso de contexto con x.")
        try:
            command = self.command + [part.format_map(values) for part in template]
            # The shared Codex app-server does not inherit this launcher's
            # per-session lifecycle ID, so hooks cannot bind its events safely.
            # A private server keeps the hooks and supervised CLI together.
            if self.kind == "codex" and Path(command[0]).name == "codex" and "--no-daemon" not in command:
                command.insert(1, "--no-daemon")
            if prompt_file:
                if not self.prompt:
                    raise ValueError(self.name + ": configura prompt para poder recibir contexto.")
                command += [part.format_map(values) for part in self.prompt]
        except KeyError as error:
            raise ValueError("Placeholder desconocido en el adaptador: " + str(error)) from error
        return command

    def launch(self, cwd, session=None, prompt_file=None, fork=False):
        directory = Path(cwd).expanduser().resolve()
        if not directory.is_dir():
            raise ValueError("La carpeta no existe: " + str(directory))
        if self.kind == "antigravity" and session:
            from .antigravity import run
            checked = run("",session,probe=True,cwd=directory)
            if checked.get("error"):raise ValueError(checked["error"])
        options = {"env": {**os.environ, "AGY_CLI_DISABLE_AUTO_UPDATE": "true"}} if self.kind == "antigravity" else {}
        from .idle import launch as idle_launch, minutes
        delay = minutes()
        command = self.argv(directory, session, prompt_file, fork)
        if delay and self.kind in ('codex', 'cursor', 'antigravity', 'hermes'):
            return idle_launch(self, command, directory, session if not fork else None, delay, options.get('env'))
        return subprocess.run(command, cwd=directory, check=False, **options).returncode


def registry(config_path=None):
    home = Path.home()
    known = [
        Agent("codex", "Codex", "codex", os.environ.get("CODEX_HOME", str(home/".codex")), ["codex"],
              ["-C", "{cwd}", "resume", "{session}"], ["-C", "{cwd}"], ["{prompt}"], ["-C", "{cwd}", "fork", "{session}"]),
        Agent("cursor", "Cursor", "cursor", str(home/".cursor"), ["cursor-agent"],
              ["--workspace", "{cwd}", "--resume", "{session}"], ["--workspace", "{cwd}"], ["{prompt}"]),
        Agent("hermes", "Hermes", "hermes", os.environ.get("HERMES_HOME", str(home/".hermes")), ["hermes"],
              ["chat", "--in", "{cwd}", "--resume", "{session}"], ["chat", "--in", "{cwd}"], ["--query-file", "{prompt_file}"]),
        Agent("claude", "Claude Code", "claude", os.environ.get("CLAUDE_CONFIG_DIR", str(home/".claude")), ["claude"],
              ["--resume", "{session}"], [], ["{prompt}"], ["--resume", "{session}", "--fork-session"]),
        Agent("gemini", "Gemini CLI", "gemini", str(home/".gemini"), ["gemini"], ["--resume", "{session}"], [], ["-i", "{prompt}"]),
        Agent("antigravity", "Antigravity CLI", "antigravity",
              str(Path(os.environ.get("XDG_STATE_HOME",str(home/".local/state")))/"agent-hub/adapters/antigravity"),
              ["agy"], ["--conversation", "{session}"], [], ["-i", "{prompt}"]),
        Agent("opencode", "OpenCode", "opencode", str(home/".local/share/opencode"), ["opencode"],
              ["--session", "{session}"], [], ["--prompt", "{prompt}"], ["--session", "{session}", "--fork"]),
    ]
    config_path = Path(config_path or Path(os.environ.get("XDG_CONFIG_HOME", str(home/".config")))/"agent-hub/agents.json")
    configured = {}
    if config_path.exists():
        data = json.loads(config_path.read_text())
        if data.get("version") != 1 or not isinstance(data.get("agents"), list):
            raise ValueError("agents.json debe tener version: 1 y agents: [].")
        for row in data["agents"]:
            ident = row.get("id")
            if not isinstance(ident, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", ident):
                raise ValueError("ID de agente inválido en agents.json.")
            if ident in configured:
                raise ValueError("ID de agente duplicado: " + ident)
            if row.get("enabled") is False:
                configured[ident] = None
                continue
            original = next((a for a in known if a.id == ident), None)
            values = asdict(original) if original else {"id": ident, "name": ident, "kind": "normalized", "home": str(home/".local/share/agent-hub/adapters"/ident), "command": [ident]}
            values.update({k: v for k, v in row.items() if k != "enabled"})
            allowed = set(Agent.__dataclass_fields__)
            if set(values)-allowed or values.get("kind") not in KINDS:
                raise ValueError("Adaptador inválido: " + ident)
            for key in ("command", "resume", "new", "prompt", "fork", "delete"):
                parts = values.get(key, [])
                if not isinstance(parts, list) or not all(isinstance(p, str) and "\x00" not in p for p in parts):
                    raise ValueError("Los comandos de agentes deben ser arrays de argumentos.")
            for key in ("home", "name", "container", "host_root", "runtime_root"):
                if key in values and not isinstance(values[key], str):
                    raise ValueError("Campo inválido del adaptador: " + key)
            if values.get("container") and (not values.get("host_root") or not values.get("runtime_root")):
                raise ValueError("Un adaptador de contenedor necesita host_root y runtime_root.")
            configured[ident] = Agent(**values)
    result = []
    for agent in known:
        selected = configured.pop(agent.id, agent)
        if selected and (selected.available or selected.container or selected.source_exists()):
            result.append(selected)
    result += [a for a in configured.values() if a is not None]
    return result


def bridge_request(request):
    kind, home = request["kind"], request["home"]
    if kind not in KINDS:
        raise ValueError("Adaptador desconocido.")
    if request["action"] == "delete":
        return native_delete(kind, home, check_id(request["session"]), project=request.get("project", False))
    if request["action"] == "messages":
        return read_messages(kind, home, check_id(request["session"]))
    if request["action"] != "index":
        raise ValueError("Acción de bridge desconocida.")
    chats, projects = read_index(kind, home, include_hidden=request.get("include_hidden", False))
    return {"conversations": [asdict(c) for c in chats], "projects": [asdict(p) for p in projects]}


def run_delete(command, name, env=None):
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, start_new_session=True,
                                capture_output=True, text=True, check=False, timeout=30, env=env)
    except subprocess.TimeoutExpired as error:
        raise ValueError(name + ": eliminación sin confirmar por timeout; actualiza el índice antes de reintentar.") from error
    if result.returncode:
        raise ValueError(name + ": no se pudo eliminar: " + (result.stderr or result.stdout).strip()[:400])
    return {"deleted": True}


def native_delete(kind, home, ident, project=False):
    check_id(ident)
    if kind == "codex":
        from .rpc import codex_delete
        codex_delete(home, ident, project=project)
        return {"deleted": True}
    if kind == "hermes" and not project:
        return run_delete(["hermes", "sessions", "delete", ident, "--yes"], "Hermes",
                          env={**os.environ, "HERMES_HOME": str(home)})
    raise ValueError("El agente no ofrece eliminación nativa configurada.")
