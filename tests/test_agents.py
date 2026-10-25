from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_hub.agents import Agent, registry
from agent_hub.manager import Manager, private_json
from agent_hub.native import read_index, read_messages
from agent_hub.rpc import codex_messages
from agent_hub.cli import run_ui

ROOT = Path(__file__).resolve().parents[1]


def adapter(root, ident, name=None):
    home = root/ident
    home.mkdir()
    private_json(home/"index.json", {"version": 1, "projects": [], "conversations": []})
    return Agent(ident, name or ident, "normalized", str(home), [sys.executable],
                 ["--resume", "{session}"], [], ["{prompt}"], ["--fork", "{session}"])


def seed(agent, cwd, ident="same-id", text="Continue with marker TEST_CONTEXT", extra=None):
    private_json(Path(agent.home)/"index.json", {"version": 1,
        "projects": [{"id": "PPE", "name": "PPE", "roots": [str(cwd)]}],
        "conversations": [{"id": ident, "title": "Work", "cwd": str(cwd), "updated": 10,
            "project_id": "PPE", "messages": [{"role": "system", "text": "DO_NOT_EXPORT_SYSTEM"},
            {"role": "user", "text": text}, {"role": "assistant", "text": "Pending work."},
            {"role": "tool", "text": "DO_NOT_EXPORT_TOOL"}, *(extra or [])]}]})


class AgentTests(unittest.TestCase):
    def test_codex_uses_a_private_server_so_idle_hooks_keep_launch_identity(self):
        agent = Agent("codex", "Codex", "codex", "/tmp/codex", ["codex"],
                      ["-C", "{cwd}", "resume", "{session}"], ["-C", "{cwd}"])
        with patch("agent_hub.agents.shutil.which", return_value="/usr/bin/codex"):
            self.assertEqual(agent.argv("/tmp")[:2], ["codex", "--no-daemon"])
            self.assertEqual(agent.argv("/tmp", "session-1")[:2], ["codex", "--no-daemon"])

    def test_new_conversation_has_stable_route_before_native_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            agent = adapter(root, "custom")
            seed(agent, root)
            manager = Manager([agent], root/"state")
            try:
                manager.sync()
                with patch.object(agent, "launch") as launch:
                    route = manager.prepare_new(agent.id, "PPE")
                    launch.assert_not_called()
                self.assertTrue(route["idMessage"].startswith("new-"))
                self.assertEqual(route["idCarpeta"], "PPE")
                self.assertEqual(manager.resolve(route)[1].cwd, str(root))
                self.assertEqual(manager.cache.transfer(route["idMessage"])["status"], "prepared")
            finally:
                manager.close()

    def test_one_agent_enters_directly_and_multiple_agents_show_selector(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            a, b = adapter(root, "one"), adapter(root, "two")
            manager = Manager([a, b], root/"state")
            try:
                manager.sync()
                with patch("agent_hub.cli.choose_agent", return_value="two") as choose, patch("agent_hub.ui.Hub") as hub:
                    hub.return_value.next_agent = None
                    run_ui(object(), manager, None)
                    choose.assert_called_once()
                    self.assertEqual(hub.call_args.kwargs["adapter"].id, "two")
                manager.agents = [a]
                with patch("agent_hub.cli.choose_agent") as choose, patch("agent_hub.ui.Hub") as hub:
                    hub.return_value.next_agent = None
                    run_ui(object(), manager, None)
                    choose.assert_not_called()
                    self.assertEqual(hub.call_args.kwargs["adapter"].id, "one")
            finally:
                manager.close()

    def test_custom_agent_registry_accepts_argv_and_rejects_shell_strings(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/"agents.json"
            disabled = [{"id": i, "enabled": False} for i in ("codex", "hermes", "claude", "gemini", "opencode", "antigravity", "cursor")]
            custom = {"id": "mine", "command": [sys.executable], "home": temporary,
                      "resume": ["--session", "{session}"], "prompt": ["{prompt_file}"]}
            private_json(path, {"version": 1, "agents": disabled+[custom]})
            agents = registry(path)
            self.assertEqual([a.id for a in agents], ["mine"])
            self.assertTrue(agents[0].available)
            custom["command"] = "sh -c unsafe"
            private_json(path, {"version": 1, "agents": disabled+[custom]})
            with self.assertRaisesRegex(ValueError, "arrays"):
                registry(path)

    def test_local_database_is_idempotent_namespaces_ids_and_preserves_cache_on_source_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            a, b = adapter(root, "one"), adapter(root, "two")
            seed(a, root); seed(b, root)
            manager = Manager([a, b], root/"state")
            try:
                manager.sync()
                self.assertEqual(len(manager.snapshot("one")[0]), 1)
                self.assertEqual(len(manager.snapshot("two")[0]), 1)
                stats = manager.sync()
                self.assertEqual(stats["one"]["changed"], 0)
                self.assertEqual(stats["two"]["changed"], 0)
                self.assertEqual(manager.cache.path.stat().st_mode & 0o777, 0o600)
                (Path(a.home)/"index.json").unlink()
                self.assertIn("error", manager.sync()["one"])
                self.assertEqual(len(manager.snapshot("one")[0]), 1)
                private_json(Path(a.home)/"index.json", {"version": 1, "projects": [], "conversations": []})
                self.assertEqual(manager.sync()["one"]["deleted"], 2)
                self.assertEqual(manager.snapshot("one"), ([], []))
                self.assertEqual(len(manager.snapshot("two")[0]), 1)
            finally:
                manager.close()

    def test_route_checks_exact_agent_folder_and_conversation_without_launching(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            a = adapter(root, "custom")
            seed(a, root)
            manager = Manager([a], root/"state")
            try:
                manager.sync()
                chats, projects = manager.snapshot(a.id)
                route = manager.route(a.id, chats[0], projects)
                self.assertEqual(set(route), {"version", "idCarpeta", "idMessage", "agente"})
                self.assertEqual(manager.resolve(route)[1].id, "same-id")
                for wrong in ({**route, "idCarpeta": "wrong"}, {**route, "agente": "missing"},
                              {**route, "idMessage": "--dangerous"}, {**route, "version": 9}):
                    with self.assertRaises(ValueError):
                        manager.resolve(wrong)
            finally:
                manager.close()

    def test_handoff_has_private_context_named_folder_and_stable_route_after_native_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = adapter(root, "codex", "Codex"), adapter(root, "hermes", "Hermes")
            seed(source, root)
            manager = Manager([source, target], root/"state")
            try:
                manager.sync()
                chats, projects = manager.snapshot(source.id)
                route = manager.prepare_transfer(manager.route(source.id, chats[0], projects), target.id)
                transfer = manager.cache.transfer(route["idMessage"])
                self.assertEqual(transfer["project_name"], "PPE - From Codex")
                self.assertEqual(transfer["cwd"], str(root))
                context = Path(transfer["context_path"]).read_text()
                self.assertIn("TEST_CONTEXT", context)
                self.assertNotIn("DO_NOT_EXPORT", context)
                self.assertEqual(Path(transfer["context_path"]).stat().st_mode & 0o777, 0o600)
                self.assertEqual([m["role"] for m in manager.cache.messages(source.id, "same-id")], ["user", "assistant"])

                def create_native(*args, **kwargs):
                    self.assertIsNotNone(kwargs.get("prompt_file"))
                    seed(target, root, "native-new")
                    return 0

                with patch.object(target, "launch", side_effect=create_native) as start:
                    self.assertEqual(manager.open(route), 0)
                    self.assertEqual(start.call_count, 1)
                self.assertEqual(manager.cache.transfer(route["idMessage"])["native_id"], "native-new")
                resolved = manager.resolve(route)[1]
                self.assertEqual(resolved.id, "native-new")
                self.assertEqual(manager.route(target.id, resolved, manager.snapshot(target.id)[1]), route)
                with patch.object(target, "launch", return_value=0) as resume:
                    manager.open(route)
                self.assertEqual(resume.call_args.args, (str(root), "native-new"))
            finally:
                manager.close()

    def test_ambiguous_handoff_does_not_launch_another_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = adapter(root, "source"), adapter(root, "target")
            seed(source, root)
            manager = Manager([source, target], root/"state")
            try:
                manager.sync()
                chats, projects = manager.snapshot(source.id)
                route = manager.prepare_transfer(manager.route(source.id, chats[0], projects), target.id)
                with patch.object(target, "launch", return_value=0) as start:
                    manager.open(route)
                    with self.assertRaisesRegex(ValueError, "no se creará un duplicado"):
                        manager.open(route)
                    self.assertEqual(start.call_count, 1)
            finally:
                manager.close()

    def test_hermes_reader_reads_visible_active_messages_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with closing(sqlite3.connect(root/"state.db")) as conn, conn:
                conn.executescript("""
                    CREATE TABLE sessions (id TEXT,title TEXT,cwd TEXT,started_at REAL,archived INT,hidden INT);
                    CREATE TABLE messages (id INT, session_id TEXT,role TEXT,content TEXT,active INT,reasoning TEXT);
                    INSERT INTO sessions VALUES ('session-1','Title','/tmp',1,0,0);
                    INSERT INTO messages VALUES (1,'session-1','user','Visible',1,'SECRET'),
                      (2,'session-1','assistant','Answer',1,'SECRET'),
                      (3,'session-1','system','SECRET',1,'SECRET'),
                      (4,'session-1','tool','SECRET',1,'SECRET'),
                      (5,'session-1','user','Inactive',0,'SECRET');
                """)
            before = (root/"state.db").read_bytes()
            self.assertEqual(read_index("hermes", root)[0][0].id, "session-1")
            self.assertEqual(read_messages("hermes", root, "session-1"),
                             [{"role": "user", "text": "Visible"}, {"role": "assistant", "text": "Answer"}])
            self.assertEqual((root/"state.db").read_bytes(), before)

    def test_paginated_codex_export_filters_non_visible_items(self):
        pages = [
            {"data": [{"items": [{"type": "userMessage", "content": [{"type": "text", "text": "Question"}]},
                                   {"type": "reasoning", "text": "SECRET"}]}], "nextCursor": "next"},
            {"data": [{"items": [{"type": "agentMessage", "text": "Answer"},
                                   {"type": "commandExecution", "output": "SECRET"}]}], "nextCursor": None},
        ]
        with patch("agent_hub.rpc.CodexReader") as reader:
            reader.return_value.call.side_effect = [{}, *pages]
            result = codex_messages("/tmp", "uuid")
            self.assertEqual(result, [{"role": "user", "text": "Question"}, {"role": "assistant", "text": "Answer"}])
            self.assertEqual(reader.return_value.call.call_args_list[-1].args[1]["cursor"], "next")
            reader.return_value.close.assert_called_once()

    def test_cli_json_contract_and_invalid_open_return_nonzero_without_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            a = adapter(root, "custom")
            seed(a, root)
            config = root/"config/agent-hub/agents.json"
            private_json(config, {"version": 1, "agents":
                [{"id": i, "enabled": False} for i in ("codex", "hermes", "claude", "gemini", "opencode", "antigravity", "cursor")]+
                [{"id": a.id, "command": [sys.executable], "home": a.home, "resume": ["{session}"]}]})
            env = {**os.environ, "XDG_CONFIG_HOME": str(root/"config"), "XDG_STATE_HOME": str(root/"state")}
            result = subprocess.run([str(ROOT/"bin/agent-hub"), "conversations", "--json"], env=env, capture_output=True, text=True, check=True)
            route = json.loads(result.stdout)[0]["route"]
            checked = subprocess.run([str(ROOT/"bin/agent-hub"), "open", "--route", json.dumps(route), "--dry-run"], env=env, capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertTrue(json.loads(checked.stdout)["valid"])
            route["idCarpeta"] = "invalid"
            invalid = subprocess.run([str(ROOT/"bin/agent-hub"), "open", "--route", json.dumps(route)], env=env, capture_output=True, text=True)
            self.assertNotEqual(invalid.returncode, 0)
            self.assertEqual(invalid.stdout, "")


if __name__ == "__main__":
    unittest.main()
