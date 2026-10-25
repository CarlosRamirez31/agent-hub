import fcntl
from contextlib import closing
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
import termios
import time
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_hub.navigation import sidebar
from agent_hub.store import Chat, Library, Project, project_catalog, project_for, read_chats, read_projects, visible

ROOT = Path(__file__).resolve().parents[1]


class ProjectTests(unittest.TestCase):
    def test_import_saved_names_order_empty_projects_and_multiple_roots_read_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            db = Path(temporary) / "state_5.sqlite"
            with closing(sqlite3.connect(db)) as conn, conn:
                conn.executescript("""
                    CREATE TABLE projects (id TEXT, name TEXT, position INT);
                    CREATE TABLE project_roots (project_id TEXT, path TEXT, position INT);
                    CREATE TABLE threads (id TEXT, title TEXT, cwd TEXT, updated_at INT, archived INT, project_id TEXT);
                    INSERT INTO projects VALUES ('items', 'Items', 1), ('ppe', 'PPE', 0), ('empty', 'Vacío', 2);
                    INSERT INTO project_roots VALUES ('items', '/tmp/items-two', 1),
                        ('ppe', '/tmp/ppe', 0), ('items', '/tmp/items', 0);
                """)
                ident = str(uuid.UUID(int=1))
                conn.execute("INSERT INTO threads VALUES (?, 'chat', '/tmp/other', 1, 0, 'ppe')", (ident,))
            original = db.read_bytes()
            projects = read_projects(temporary)
            self.assertEqual([p.name for p in projects], ["PPE", "Items", "Vacío"])
            self.assertEqual(projects[1].roots, ("/tmp/items", "/tmp/items-two"))
            self.assertEqual(projects[2].roots, ())
            self.assertEqual(read_chats(temporary)[0].project_id, "ppe")
            self.assertEqual(db.read_bytes(), original)
        self.assertEqual(read_projects("/no-codex-hub-database"), [])

    def test_membership_prefers_explicit_then_most_specific_root_without_prefix_collisions(self):
        projects = [Project("parent", "Items", ("/tmp/items",)),
                    Project("nested", "Nested", ("/tmp/items/nested", "/tmp/second-root"))]
        self.assertEqual(project_for(Chat("a", "chat", "/tmp/items/src", 1), projects), "parent")
        self.assertEqual(project_for(Chat("b", "chat", "/tmp/items/nested/src", 1), projects), "nested")
        self.assertEqual(project_for(Chat("c", "chat", "/tmp/second-root/src", 1), projects), "nested")
        self.assertIsNone(project_for(Chat("d", "chat", "/tmp/items-copy", 1), projects))
        self.assertEqual(project_for(Chat("e", "chat", "/tmp/elsewhere", 1, project_id="parent"), projects), "parent")

    def test_empty_local_folder_persists_and_old_library_migrates_without_losing_sections(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "empty project"
            project.mkdir()
            state = root / "library.json"
            state.write_text(json.dumps({"version": 1, "sections": ["Trabajo"], "chats": {}}))
            library = Library(state)
            ident = library.add_project(project)
            link = root / "alias"
            link.symlink_to(project, target_is_directory=True)
            self.assertEqual(library.add_project(link), ident)
            loaded = Library(state)
            self.assertEqual(loaded.data["sections"], ["Trabajo"])
            self.assertEqual(len(loaded.data["projects"]), 1)
            self.assertEqual(project_catalog([], [], loaded)[0].roots, (str(project),))
            with self.assertRaisesRegex(ValueError, "no existe"):
                loaded.add_project(root / "missing")

    def test_imported_folder_is_not_duplicated_and_unregistered_chats_stay_discoverable(self):
        with tempfile.TemporaryDirectory() as temporary:
            library = Library(None)
            library.add_project(temporary)
            saved = Project("official", "My saved name", (temporary,))
            chats = [Chat("a", "nested", temporary + "/src", 1),
                     Chat("b", "elsewhere", "/tmp/hub-unknown", 2),
                     Chat("c", "explicit", "/tmp/hub-explicit", 3, project_id="official")]
            catalog = project_catalog(chats, [saved], library)
            self.assertEqual(len(catalog), 2)
            self.assertEqual(catalog[0], saved)
            self.assertEqual(catalog[1].source, "discovered")
            self.assertEqual([c.id for c in visible(chats, library, ("project", "official"), projects=catalog)], ["c", "a"])

    def test_sidebar_has_only_folders_and_counts_with_empty_projects(self):
        library = Library(None)
        project = Project("saved", "PPE", ("/tmp/ppe",))
        empty = Project("empty", "Nuevo", ("/tmp/empty",))
        chats = [Chat(str(i), f"chat {i}", "/tmp/ppe/src", i) for i in range(7)]
        library.change(chats[0], pinned=True)
        rows = sidebar(chats, [project, empty], library)
        self.assertEqual(rows[0].label, "▸ PPE (7)")
        self.assertEqual(rows[1].label, "▸ Nuevo (0)")
        self.assertFalse(any(r.kind in ("chat", "empty", "more") for r in rows))
        self.assertEqual(next(r.label for r in rows if r.kind == "recent"), "Recientes (7)")
        self.assertEqual(visible(chats, library, ("recent", ""))[0].id, "6")

    def test_opening_automatically_picks_up_additions_deletions_without_duplicating_or_rewriting(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "codex"
            data.mkdir()
            state = root / "state/codex-hub/library.json"
            local = Library(state)
            local.add_project(root)
            saved = state.read_bytes()
            with closing(sqlite3.connect(data / "state_5.sqlite")) as conn, conn:
                conn.executescript("""
                    CREATE TABLE projects (id TEXT, name TEXT, position INT);
                    CREATE TABLE project_roots (project_id TEXT, path TEXT, position INT);
                    CREATE TABLE threads (id TEXT, title TEXT, cwd TEXT, updated_at INT, archived INT);
                    INSERT INTO projects VALUES ('one', 'One', 0);
                    INSERT INTO project_roots VALUES ('one', '/tmp/one', 0);
                """)
            env = {**os.environ, "CODEX_HOME": str(data), "XDG_STATE_HOME": str(root / "state")}

            def open_count(expected):
                result = subprocess.run([str(ROOT / "bin/agent-hub"), "--agent", "codex", "--count"], env=env,
                                        capture_output=True, text=True, check=True)
                self.assertIn(expected, result.stdout)
                self.assertEqual(state.read_bytes(), saved)
                catalog = project_catalog(read_chats(data), read_projects(data), Library(state))
                self.assertEqual(len({p.id for p in catalog}), len(catalog))

            open_count("1 proyectos")
            open_count("1 proyectos")
            with closing(sqlite3.connect(data / "state_5.sqlite")) as conn, conn:
                conn.execute("INSERT INTO projects VALUES ('two', 'Two', 1)")
            open_count("2 proyectos")
            with closing(sqlite3.connect(data / "state_5.sqlite")) as conn, conn:
                conn.execute("DELETE FROM projects WHERE id='one'")
                conn.execute("DELETE FROM project_roots WHERE project_id='one'")
            open_count("1 proyectos")
            self.assertEqual([p.id for p in read_projects(data)], ["two"])


class FolderPickerTests(unittest.TestCase):
    def test_add_empty_folder_with_spaces_then_reopen_and_start_chat_there(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "Carpeta vacía con espacios"
            folder.mkdir()
            env = {**os.environ, "TERM": "xterm-256color", "CODEX_HOME": str(root / "codex"),
                   "XDG_STATE_HOME": str(root / "state"), "PYTHONDONTWRITEBYTECODE": "1"}
            library_path = root / "state/agent-hub/libraries/codex.json"
            record = root / "arguments.json"
            stub = root / "codex"
            stub.write_text("#!" + sys.executable + "\nimport sys,json,os\nfrom pathlib import Path\n"
                            "if sys.argv[1:2] == ['app-server']: sys.exit(0)\n"
                            "Path(os.environ['HUB_TEST_RECORD']).write_text(json.dumps(sys.argv[1:]))\n")
            stub.chmod(0o755)
            env.update(PATH=str(root) + os.pathsep + os.environ["PATH"], HUB_TEST_RECORD=str(record))
            env["CODEX_HOME"] = str(root / "codex-data")

            def session(add):
                master, slave = pty.openpty()
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 28, 120, 0, 0))
                process = subprocess.Popen([str(ROOT / "bin/agent-hub"), "--agent", "codex"], stdin=slave, stdout=slave,
                                           stderr=slave, env=env, cwd=ROOT)
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
                    self.assertTrue(marker in output, output.decode(errors="replace")[-2500:])

                def wait_file(path):
                    deadline = time.monotonic()+4
                    while not path.exists() and time.monotonic() < deadline:
                        if select.select([master], [], [], 0.1)[0]:
                            try:
                                output.extend(os.read(master, 65536))
                            except OSError:
                                break
                    self.assertTrue(path.exists(), output.decode(errors="replace")[-2500:])

                try:
                    wait_for(b"AGENT HUB")
                    if add:
                        os.write(master, b"p/\x15" + str(folder).encode() + b"\n ")
                        wait_file(library_path)
                    else:
                        wait_for(folder.name.encode())
                        os.write(master, b"n\n")
                        wait_file(record)
                        self.assertEqual(json.loads(record.read_text()), ["--no-daemon", "-C", str(folder)])
                    os.write(master, b"q")
                    self.assertEqual(process.wait(timeout=5), 0)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    os.close(master)

            session(True)
            self.assertEqual(Library(library_path).data["projects"][0]["path"], str(folder))
            session(False)
            self.assertEqual(list(folder.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
