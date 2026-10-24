"""Exercise the real key loop, including independent folder and chat selection."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_hub.store import Chat, Library, Project
from agent_hub.ui import Hub


class Screen:
    def __init__(self):
        self.events = []

    def getmaxyx(self):
        return 28, 120

    def keypad(self, value):
        pass

    def erase(self):
        pass

    def refresh(self):
        pass

    def addnstr(self, *args):
        pass

    def get_wch(self):
        while callable(self.events[0]):
            self.events.pop(0)()
        return self.events.pop(0)


class NavigationTests(unittest.TestCase):
    def make_hub(self):
        screen = Screen()
        projects = [Project("one", "One", ("/tmp/one",)), Project("two", "Two", ("/tmp/two",))]
        chats = [Chat("a", "Older one", "/tmp/one", 1), Chat("b", "Newer one", "/tmp/one", 2),
                 Chat("c", "Two chat", "/tmp/two", 3)]
        with patch("agent_hub.ui.curses.curs_set"), patch("agent_hub.ui.curses.has_colors", return_value=False):
            hub = Hub(screen, Library(None), chats, "/not-used", demo=True, projects=projects)
        return hub, screen

    def test_open_shortcut_enters_folder_then_resumes_selected_chat(self):
        hub, screen = self.make_hub()
        screen.events = ['o', 'j', 'o', 'q']
        with patch.object(hub, 'open_chat') as opened:
            hub.run()
        opened.assert_called_once_with(hub.current()[1])

    def test_actions_and_remaining_quota_are_visible_without_overlapping_chats(self):
        hub, screen = self.make_hub()
        from types import SimpleNamespace
        hub.usage = SimpleNamespace(lines=lambda: ['CUOTA', '5 h: 82% restante · reinicia en 1h', 'Semana: 46% restante'])
        for height in (16, 28):
            recorded = []
            with patch.object(screen, 'getmaxyx', return_value=(height, 120)), patch.object(screen, 'addnstr', side_effect=lambda *args: recorded.append(args)):
                hub.draw()
            text = ' '.join(str(args[2]) for args in recorded)
            self.assertIn('Nueva conversación', text)
            self.assertIn('82% restante', text)
            self.assertIn('Semana: 46%', text)
            quota_rows = {args[0] for args in recorded if 'restante' in str(args[2])}
            chat_rows = {args[0] for args in recorded if 'Newer one' in str(args[2]) or 'Two chat' in str(args[2])}
            self.assertFalse(quota_rows & chat_rows)

    def test_d_requires_explicit_confirmation_and_cancel_keeps_chat(self):
        hub, screen = self.make_hub()
        def unchanged():
            self.assertEqual(len(hub.chats), 3)
        def deleted():
            self.assertEqual(len(hub.chats), 2)
        screen.events = ['l', 'd', '\n', '\x1b', unchanged, 'd', 'c', deleted, 'q']
        with patch.object(hub, 'prompt', return_value='ELIMINAR') as prompt:
            hub.run()
        prompt.assert_called_once_with('Escribe ELIMINAR')

    def test_delete_last_chat_returns_focus_to_folders_and_shortcuts_keep_working(self):
        hub, screen = self.make_hub()
        def empty_folder():
            self.assertEqual(hub.current(), [])
            self.assertEqual(hub.focus, 0)
        def moved():
            self.assertEqual(hub.nav, 2)
        screen.events = ['j', 'l', 'd', 'c', empty_folder, '\x18', 'j', moved, 'q']
        with patch.object(hub, 'prompt', return_value='ELIMINAR'):
            hub.run()

    def test_demo_folder_delete_never_touches_files_or_calls_backend(self):
        hub, screen = self.make_hub()
        screen.events = ['d', 'q']
        with patch('agent_hub.deletion.folder_plan') as plan:
            hub.run()
        plan.assert_not_called()
        self.assertEqual(len(hub.chats), 3)

    def test_style_settings_return_without_changing_navigation(self):
        hub, screen = self.make_hub()
        original_style = hub.style
        screen.events = ['j', 'S', 'q']
        with patch('agent_hub.ui.edit_style', return_value=hub.style.config) as editor, \
             patch('curses.has_colors', return_value=False):
            hub.run()
        editor.assert_called_once_with(screen, original_style, persist=False)
        self.assertEqual((hub.nav, hub.focus, hub.group), (1, 0, ('recent', '')))

    def test_hovering_preserves_active_list_and_selection_until_l_enters_folder(self):
        hub, screen = self.make_hub()

        def check(group, focus, selected, nav):
            def assert_state():
                self.assertEqual((hub.group, hub.focus, hub.selected, hub.nav), (group, focus, selected, nav))
            return assert_state

        screen.events = [
            "j", check(("recent", ""), 0, 0, 1),
            "l", check(("project", "two"), 1, 0, 1),
            "h", "k", check(("project", "two"), 0, 0, 0),
            "l", "j", check(("project", "one"), 1, 1, 0),
            "h", "j", check(("project", "one"), 0, 1, 1), "q",
        ]
        hub.run()

    def test_enter_resumes_selected_chat_and_f_explicitly_forks_it(self):
        hub, screen = self.make_hub()
        screen.events = ["l", "j", "\n", "f", "q"]
        with patch.object(hub, "open_chat") as open_chat:
            hub.run()
        self.assertEqual(open_chat.call_args_list[0].args[0].id, "a")
        self.assertEqual(open_chat.call_args_list[0].kwargs, {})
        self.assertEqual(open_chat.call_args_list[1].args[0].id, "a")
        self.assertEqual(open_chat.call_args_list[1].kwargs, {"fork": True})

    def test_search_stays_in_entered_project_and_does_not_change_sidebar_counts(self):
        hub, screen = self.make_hub()

        def check():
            self.assertEqual(hub.group, ("project", "one"))
            self.assertEqual([c.id for c in hub.current()], ["a"])
            self.assertEqual(hub.rows()[0].label, "▸ One (2)")

        screen.events = ["l", "/", check, "q"]
        with patch.object(hub, "prompt", return_value="Older"):
            hub.run()


if __name__ == "__main__":
    unittest.main()
