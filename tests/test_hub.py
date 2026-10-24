import json
import os
from pathlib import Path
import pty
import select
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid
import fcntl
import termios

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_hub.cli import launch, update
from codex_hub.store import Chat, Library, read_chats, visible
from codex_hub.ui import clean

ROOT = Path(__file__).resolve().parents[1]
ID = str(uuid.UUID(int=1))


class StoreTests(unittest.TestCase):
    def test_paginated_chat_and_read_only_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            db = Path(temporary) / "state_5.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE threads (id TEXT, title TEXT, cwd TEXT, updated_at INT, archived INT)")
                conn.execute("INSERT INTO threads VALUES (?, ?, ?, ?, ?)",
                             (ID, "Sin archivo rollout", "/tmp/project", 100, 0))
                conn.execute("INSERT INTO threads VALUES ('bad-id','no','/tmp',101,0)")
            original = db.read_bytes()
            self.assertEqual(read_chats(temporary), [Chat(ID, "Sin archivo rollout", "/tmp/project", 100)])
            self.assertEqual(original, db.read_bytes())

    def test_unknown_schema_fails_without_modifying(self):
        with tempfile.TemporaryDirectory() as temporary:
            db = Path(temporary) / "state_10.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE threads (id TEXT)")
            original = db.read_bytes()
            with self.assertRaisesRegex(ValueError, "índice de Codex cambió"):
                read_chats(temporary)
            self.assertEqual(db.read_bytes(), original)
        self.assertEqual(read_chats("/nonexistent-codex-hub-home"), [])

    def test_library_sections_search_pins_and_archives(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "library.json"
            lib = Library(path)
            a = Chat(ID, "Neovim", "/repo/dotfiles", 1)
            b = Chat(str(uuid.UUID(int=2)), "Otro", "/repo/app", 2)
            archived = Chat(str(uuid.UUID(int=3)), "Viejo", "/repo/app", 3, True)
            lib.add_section("Trabajo")
            lib.change(a, title="Editor", section="Trabajo", pinned=True)
            loaded = Library(path)
            self.assertEqual(visible([a,b,archived], loaded, ("all", "")), [a,b])
            self.assertEqual(visible([a,b], loaded, ("section", "Trabajo"), "EDITOR"), [a])
            self.assertEqual(visible([a,b], loaded, ("project", "/repo/app")), [b])
            self.assertEqual(visible([a,b], loaded, ("pinned", "")), [a])
            self.assertEqual(visible([a,b,archived], loaded, ("all", ""), archives=True), [archived])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_corrupt_library_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "library.json"
            path.write_text('{"version":999}')
            with self.assertRaises(ValueError):
                Library(path)
            self.assertEqual(path.read_text(), '{"version":999}')

    def test_terminal_metadata_cannot_inject_controls(self):
        self.assertNotIn("\x1b", clean("hello\x1b]52;clipboard\x07"))
        self.assertNotIn("\n", clean("fake\nline"))


class CommandsTests(unittest.TestCase):
    def test_resume_passes_literal_directory_and_id_without_shell(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cwd = root / "a $(touch PWNED); 'space'"
            cwd.mkdir()
            executable = root / "codex"
            record = root / "arguments.json"
            executable.write_text("#!/usr/bin/env python3\nimport os,sys,json\n"
                                  "from pathlib import Path\n"
                                  "Path(os.environ['RECORD']).write_text(json.dumps(sys.argv[1:]))\n")
            executable.chmod(0o755)
            with patch.dict(os.environ, {"PATH": str(root) + os.pathsep + os.environ["PATH"], "RECORD": str(record)}):
                self.assertEqual(launch(Chat(ID, "title", str(cwd), 0)), 0)
            self.assertEqual(json.loads(record.read_text()), ["-C", str(cwd), "resume", ID])
            self.assertFalse((cwd / "PWNED").exists())

    def test_installer_is_idempotent_and_refuses_to_replace(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = {**os.environ, "HOME": temporary}
            for _ in range(2):
                result = subprocess.run([str(ROOT / "install.sh")], env=env, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            link = Path(temporary) / ".local/bin/codex-hub"
            self.assertEqual(link.resolve(), ROOT / "bin/codex-hub")
            link.unlink()
            link.write_text("do not replace")
            result = subprocess.run([str(ROOT / "install.sh")], env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(link.read_text(), "do not replace")

    def test_update_rejects_other_origins_before_network(self):
        with patch("codex_hub.cli.subprocess.check_output", return_value="https://example.com/repo.git\n"), \
                patch("codex_hub.cli.subprocess.run") as run:
            with self.assertRaisesRegex(ValueError, "origin"):
                update()
            run.assert_not_called()

    def test_update_rejects_local_changes(self):
        with patch("codex_hub.cli.subprocess.check_output", side_effect=[
                "https://github.com/CarlosRamirez31/codex-hub.git\n", " M README.md\n"]), \
                patch("codex_hub.cli.subprocess.run") as run:
            with self.assertRaisesRegex(ValueError, "cambios locales"):
                update()
            run.assert_not_called()


class TerminalTests(unittest.TestCase):
    def test_real_handoff_to_local_codex_stub_returns_to_hub(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with sqlite3.connect(root / "state_5.sqlite") as conn:
                conn.execute("CREATE TABLE threads (id TEXT, title TEXT, cwd TEXT, updated_at INT, archived INT)")
                conn.execute("INSERT INTO threads VALUES (?, 'Test chat', ?, 1, 0)", (ID, str(root)))
            stub = root / "codex"
            stub.write_text("#!/bin/sh\nprintf 'LOCAL_CODEX_STUB\\n'\n")
            stub.chmod(0o755)
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 28, 110, 0, 0))
            env = {**os.environ, "TERM": "xterm-256color", "CODEX_HOME": temporary,
                   "XDG_STATE_HOME": str(root / "state"),
                   "PATH": str(root) + os.pathsep + os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"}
            process = subprocess.Popen([str(ROOT / "bin/codex-hub")], stdin=slave, stdout=slave, stderr=slave, env=env)
            os.close(slave)
            output = bytearray()

            def wait_for(marker):
                deadline = time.monotonic()+4
                while marker not in output and time.monotonic() < deadline:
                    if select.select([master], [], [], 0.1)[0]:
                        try:
                            output.extend(os.read(master, 65536))
                        except OSError:
                            break
                self.assertIn(marker, output, output.decode(errors="replace"))

            try:
                wait_for(b"Test chat")
                os.write(master, b"l\n")
                wait_for(b"LOCAL_CODEX_STUB")
                wait_for(b"Tu biblioteca sigue")
                os.write(master, b"q")
                self.assertEqual(process.wait(timeout=4), 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                os.close(master)

    def test_demo_keyboard_navigation_sections_and_exit_without_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 28, 110, 0, 0))
            env = {**os.environ, "TERM": "xterm-256color", "XDG_STATE_HOME": temporary,
                   "CODEX_HOME": str(Path(temporary) / "missing"), "PYTHONDONTWRITEBYTECODE": "1"}
            process = subprocess.Popen([str(ROOT / "bin/codex-hub"), "--demo"],
                                       stdin=slave, stdout=slave, stderr=slave, env=env)
            os.close(slave)
            output = bytearray()

            def drain_until(marker, timeout=4):
                deadline = time.monotonic()+timeout
                while marker not in output and time.monotonic() < deadline:
                    ready, _, _ = select.select([master], [], [], 0.1)
                    if ready:
                        try:
                            output.extend(os.read(master, 65536))
                        except OSError:
                            break
                self.assertIn(marker, output, output.decode(errors="replace"))

            try:
                drain_until(b"CODEX HUB")
                os.write(master, b"lj /Neovim\n")
                drain_until(b"Buscar")
                os.write(master, b"sPersonal\n")
                drain_until(b"Personal")
                os.write(master, b"\n")
                drain_until(b"Modo demo")
                os.write(master, b"q")
                self.assertEqual(process.wait(timeout=4), 0)
                self.assertFalse((Path(temporary) / "codex-hub").exists())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                os.close(master)


if __name__ == "__main__":
    unittest.main()
