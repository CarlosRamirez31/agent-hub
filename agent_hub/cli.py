"""Agent Hub CLI and JSON routing contract; browsing never calls a model."""

from dataclasses import asdict
import argparse
import curses
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid

from . import __version__
from .store import Chat, Library, Project
from .terminal import prepare_input, read_key

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "https://github.com/CarlosRamirez31/agent-hub.git"
LEGACY_UPSTREAM = "https://github.com/CarlosRamirez31/codex-hub.git"


def launch(chat=None, cwd=None, fork=False):
    from .agents import registry
    agent = next((a for a in registry() if a.id == "codex"), None)
    if not agent:
        raise ValueError("No se encontró codex en PATH.")
    return agent.launch(cwd or (chat.cwd if chat else str(Path.cwd())), chat.id if chat else None, fork=fork)


def update():
    remote = subprocess.check_output(["git", "-C", str(ROOT), "remote", "get-url", "origin"], text=True).strip()
    if remote not in (UPSTREAM, LEGACY_UPSTREAM):
        raise ValueError("Actualización cancelada: origin no apunta a " + UPSTREAM)
    if subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"], text=True):
        raise ValueError("Hay cambios locales. Guárdalos antes de actualizar.")
    if subprocess.check_output(["git", "-C", str(ROOT), "branch", "--show-current"], text=True).strip() != "main":
        raise ValueError("Cambia a main antes de actualizar.")
    if remote == LEGACY_UPSTREAM:
        subprocess.run(["git", "-C", str(ROOT), "remote", "set-url", "origin", UPSTREAM], check=True)
    return subprocess.run(["git", "-C", str(ROOT), "pull", "--ff-only", "origin", "main"], check=False).returncode


def choose_agent(screen, agents, title="AGENT HUB · ELIGE AGENTE"):
    from .ui import clean
    from .style import Style, edit_style
    style = Style()
    index = 0
    prepare_input(screen)
    while True:
        screen.erase()
        height, width = screen.getmaxyx()
        def line(y, text, style=0):
            if 0 <= y < height:
                try:
                    screen.addnstr(y, 2, clean(text), max(1, width-3), style)
                except curses.error:
                    pass
        line(1, "◈  " + title, curses.A_BOLD | style.color(1))
        line(2, "LOCAL · sin telemetría", style.color(3))
        room = max(1, height-7)
        offset = max(0, index-room+1)
        for i, agent in enumerate(agents[offset:offset+room], offset):
            line(3+i-offset, (("> " if i == index else "  ") + agent.name + " · " + agent.id).ljust(max(1, width-3)),
                 (style.color(2) | curses.A_BOLD) if i == index else curses.A_NORMAL)
        line(height-2, "j/k elige · Enter/l entra · S colores · Esc/q cancela", curses.A_DIM)
        screen.refresh()
        key = read_key(screen)
        if key in ("q", "\x1b"):
            return None
        if key == "S":
            style = Style(edit_style(screen, style))
        elif key in ("j", curses.KEY_DOWN):
            index = min(len(agents)-1, index+1)
        elif key in ("k", curses.KEY_UP):
            index = max(0, index-1)
        elif key in ("\n", "\r", "l", curses.KEY_ENTER):
            return agents[index].id


def run_ui(screen, manager, selected):
    from .ui import Hub
    agent_id = selected
    while True:
        if not agent_id:
            agent_id = manager.agents[0].id if len(manager.agents) == 1 else choose_agent(screen, manager.agents)
        if not agent_id:
            return
        chats, projects = manager.snapshot(agent_id)
        adapter = manager.agent(agent_id)
        hub = Hub(screen, manager.library(agent_id), chats, adapter.home, projects=projects,
                  manager=manager, adapter=adapter)
        if agent_id in manager.errors:
            hub.message = manager.errors[agent_id]
        hub.run()
        if not hub.next_agent:
            return
        agent_id = None if hub.next_agent == "select" else hub.next_agent


def parse_route(args):
    if args.route and args.route_file:
        raise ValueError("Usa --route o --route-file, no ambos.")
    if args.route_file:
        path = Path(args.route_file)
        if path.stat().st_size > 65536:
            raise ValueError("El archivo de ruta es demasiado grande.")
        return json.loads(path.read_text())
    if args.route:
        return json.loads(args.route)
    return {"version": 1, "agente": args.agent, "idCarpeta": args.folder, "idMessage": args.conversation}


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == 'idle':
        from .idle import main as idle_main
        return idle_main(arguments[1:])
    if arguments and arguments[0] == 'agy-run':
        from .antigravity import main as agy_main
        return agy_main(arguments[1:])
    if arguments and arguments[0] == 'work':
        from .engine.work_cli import main as work_main
        return work_main(arguments[1:])
    if arguments and arguments[0] == 'task':
        from .engine.cli import main as task_main
        return task_main(arguments[1:])
    parser = argparse.ArgumentParser(description="Agentes, proyectos y conversaciones en una terminal.")
    parser.add_argument("action", nargs="?", choices=["update", "agents", "projects", "conversations", "route", "open", "new", "transfer", "sync", "bridge", "bind", "style", "task", "work"])
    parser.add_argument("--version", action="version", version=__version__)
    from .style import PRESETS
    parser.add_argument("--preset", choices=PRESETS, help="guardar una paleta con la acción style")
    parser.add_argument("--agent")
    parser.add_argument("--to", dest="target")
    parser.add_argument("--folder")
    parser.add_argument("--conversation")
    parser.add_argument("--native-id")
    parser.add_argument("--route")
    parser.add_argument("--route-file")
    parser.add_argument("--request", help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--include-messages", action="store_true", help="importar texto visible de historiales a la base local")
    parser.add_argument("--launch", action="store_true", help="abrir inmediatamente la continuación preparada")
    parser.add_argument("--dry-run", action="store_true", help="validar una ruta sin iniciar el agente")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--count", action="store_true")
    args = parser.parse_args(arguments)
    if args.preset and args.action != "style":
        parser.error("--preset requiere la acción style")
    manager = None
    try:
        if args.action == "style":
            from .style import config_path, load, save
            config = save(args.preset) if args.preset else load()
            print(json.dumps({"path": str(config_path()), **config}, ensure_ascii=False, indent=2))
            return 0
        if args.action == "update":
            return update()
        if args.action == "bridge":
            from .agents import bridge_request
            print(json.dumps(bridge_request(json.loads(args.request)), ensure_ascii=False))
            return 0
        if args.demo:
            from .ui import Hub
            chats = [Chat(str(uuid.UUID(int=i+1)), title, "/demo/"+project, 1800000000-i)
                     for i, (title, project) in enumerate([("Mi configuración de Neovim", "dotfiles"),
                         ("Panel de chats y proyectos", "agent-hub"), ("Preparar la próxima versión", "agent-hub"),
                         ("Ideas para el portafolio", "portfolio")])]
            projects = [Project("demo-dotfiles", "dotfiles", ("/demo/dotfiles",)),
                        Project("demo-hub", "agent-hub", ("/demo/agent-hub",)), Project("demo-empty", "Proyecto nuevo", ("/demo/nuevo",))]
            if args.count:
                print(f"{len(chats)} conversaciones y {len(projects)} proyectos de Codex en el índice local. Solo lectura.")
                return 0
            curses.wrapper(lambda screen: Hub(screen, Library(None), chats, "", True, projects).run())
            return 0
        from .manager import Manager
        manager = Manager()
        if not manager.agents:
            raise ValueError("No se encontró ningún agente. Instala uno o regístralo en ~/.config/agent-hub/agents.json.")
        if args.action == "agents":
            print(json.dumps([{"id": a.id, "name": a.name, "installed": a.available, "reader": a.kind,
                               "home": a.home, "container": a.container or None} for a in manager.agents], ensure_ascii=False, indent=2))
            return 0
        stats = manager.sync([args.agent] if args.action == "sync" and args.agent else None,
                             include_messages=args.include_messages)
        if args.agent:
            manager.agent(args.agent)
        if args.action == "sync":
            print(json.dumps(stats, ensure_ascii=False, indent=2))
            return 1 if manager.errors else 0
        if args.count:
            for agent in manager.agents:
                if args.agent and args.agent != agent.id:
                    continue
                chats, projects = manager.snapshot(agent.id)
                imported = [p for p in projects if p.source == "codex"]
                print(f"{len(chats)} conversaciones y {len(imported)} proyectos de {agent.name} en el índice local. Solo lectura de fuentes.")
            return 0
        if args.action in ("projects", "conversations"):
            result = []
            for agent in manager.agents:
                if args.agent and agent.id != args.agent:
                    continue
                chats, projects = manager.snapshot(agent.id)
                if args.action == "projects":
                    result += [{**asdict(p), "agente": agent.id, "idCarpeta": p.id} for p in projects]
                else:
                    for chat in chats:
                        route = manager.route(agent.id, chat, projects)
                        if not args.folder or route["idCarpeta"] == args.folder:
                            result.append({**asdict(chat), "route": route})
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.action in ("route", "open", "transfer"):
            route = parse_route(args)
            agent, chat = manager.resolve(route)
            if args.action == "route":
                print(json.dumps(manager.route(agent.id, chat, manager.snapshot(agent.id)[1]), ensure_ascii=False))
                return 0
            if args.action == "transfer":
                route = manager.prepare_transfer(route, args.target)
                print(json.dumps(route, ensure_ascii=False), flush=True)
                return manager.open(route) if args.launch else 0
            if args.dry_run:
                print(json.dumps({"valid": True, "route": route, "cwd": chat.cwd}, ensure_ascii=False))
                return 0
            return manager.open(route)
        if args.action == "bind":
            manager.bind(args.agent, args.conversation, args.native_id)
            return 0
        if args.action == "new":
            agent = manager.agent(args.agent or (manager.agents[0].id if len(manager.agents) == 1 else ""))
            route = manager.prepare_new(agent.id, args.folder)
            print(json.dumps(route, ensure_ascii=False), flush=True)
            return manager.open(route) if args.launch else 0
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise ValueError("Usa una terminal interactiva o un subcomando JSON de agent-hub.")
        curses.wrapper(lambda screen: run_ui(screen, manager, args.agent))
        return 0
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, curses.error, subprocess.CalledProcessError) as error:
        print(f"agent-hub: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        if manager:
            manager.close()


if __name__ == "__main__":
    sys.exit(main())
