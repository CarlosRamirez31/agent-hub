"""The hub itself has no network client; only an explicit update uses Git."""

import argparse
import curses
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import uuid

from . import __version__
from .store import Chat, Library, Project, read_chats, read_projects

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "https://github.com/CarlosRamirez31/codex-hub.git"


def launch(chat=None, cwd=None, fork=False):
    executable = shutil.which("codex")
    if not executable:
        raise ValueError("No se encontró codex en PATH. Instala el CLI oficial primero.")
    directory = Path(cwd or (chat.cwd if chat else Path.cwd())).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError("La carpeta no existe: " + str(directory))
    command = [executable, "-C", str(directory)]
    if chat:
        command += ["fork" if fork else "resume", str(uuid.UUID(chat.id))]
    # An argv array, never a shell. Preserve Codex's own approvals and sandbox.
    return subprocess.run(command, cwd=directory, check=False).returncode


def update():
    """Only the owner's repo; never download from other registries or upstreams."""
    remote = subprocess.check_output(
        ["git", "-C", str(ROOT), "remote", "get-url", "origin"], text=True
    ).strip()
    if remote != UPSTREAM:
        raise ValueError("Actualización cancelada: origin no apunta a " + UPSTREAM)
    if subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"], text=True):
        raise ValueError("Hay cambios locales. Guárdalos antes de actualizar.")
    branch = subprocess.check_output(
        ["git", "-C", str(ROOT), "branch", "--show-current"], text=True
    ).strip()
    if branch != "main":
        raise ValueError("Cambia a main antes de actualizar.")
    return subprocess.run(
        ["git", "-C", str(ROOT), "pull", "--ff-only", "origin", "main"], check=False
    ).returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tus chats de Codex, organizados en la terminal.")
    parser.add_argument("action", nargs="?", choices=["update"], help="actualización manual desde tu repositorio")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--demo", action="store_true", help="interfaz con datos ficticios, sin iniciar Codex")
    parser.add_argument("--count", action="store_true", help="comprobar el índice sin mostrar conversaciones")
    args = parser.parse_args(argv)
    try:
        if args.action:
            return update()
        home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        state = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
        library = Library(None if args.demo else state / "codex-hub/library.json")
        if args.demo:
            chats = [Chat(str(uuid.UUID(int=i + 1)), title, "/demo/" + project, 1800000000-i)
                     for i, (title, project) in enumerate([
                         ("Mi configuración de Neovim", "dotfiles"),
                         ("Panel de chats y proyectos", "codex-hub"),
                         ("Preparar la próxima versión", "codex-hub"),
                         ("Ideas para el portafolio", "portfolio")])]
            projects = [Project("demo-dotfiles", "dotfiles", ("/demo/dotfiles",)),
                        Project("demo-hub", "codex-hub", ("/demo/codex-hub",)),
                        Project("demo-empty", "Proyecto nuevo", ("/demo/nuevo",))]
        else:
            chats = read_chats(home)
            projects = read_projects(home)
        if args.count:
            print(f"{len(chats)} conversaciones y {len(projects)} proyectos de Codex en el índice local. Solo lectura.")
            return 0
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise ValueError("Abre codex-hub en una terminal interactiva; usa --count para comprobar el índice.")
        from .ui import Hub
        curses.wrapper(lambda screen: Hub(screen, library, chats, home, args.demo, projects).run())
        return 0
    except (OSError, ValueError, sqlite3.Error, curses.error, subprocess.CalledProcessError) as error:
        print(f"codex-hub: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
