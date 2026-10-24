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
