"""Palette persistence and shared rendering, without native agent access."""
import curses
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent_hub.cli import choose_agent, main
from agent_hub.style import Style, config_path, edit_style, load, resolve, save
from agent_hub.store import Library
from agent_hub.ui import Hub


class StyleTests(unittest.TestCase):
    def test_save_and_custom_colors_use_xdg_config_without_agent_discovery(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, XDG_CONFIG_HOME=directory):
            with patch('builtins.print'):
                self.assertEqual(main(['style', '--preset', 'violet']), 0)
            self.assertEqual(load()['colors']['selection_bg'], 'magenta')
            config_path().write_text(json.dumps({'theme': 'green', 'colors': {'selection_fg': 'white'}}))
            self.assertEqual(load()['colors']['selection_fg'], 'white')
            self.assertEqual(load()['colors']['accent'], 'green')

    def test_invalid_configuration_is_rejected(self):
        for config in ([], {'theme': []}, {'theme': 'missing'}, {'colors': {'accent': []}},
                       {'colors': {'background': 'red'}}, {'colors': {'accent': 'orange'}}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                resolve(config)

    def test_main_and_agent_selectors_share_curses_pairs(self):
        class Screen:
            def __init__(self): self.lines = []
            def keypad(self, enabled): pass
            def erase(self): pass
            def refresh(self): pass
            def getmaxyx(self): return 28, 120
            def addnstr(self, *args): self.lines.append(args)
            def get_wch(self): return '\n'
        screen = Screen()
        palette = resolve({'theme': 'green'})
        with patch('agent_hub.style.load', return_value=palette), \
             patch('curses.has_colors', return_value=True), patch('curses.start_color'), \
             patch('curses.use_default_colors'), patch('curses.init_pair') as pair, \
             patch('curses.color_pair', side_effect=lambda n: n * 256), patch('curses.curs_set'):
            hub = Hub(screen, Library(None), [], '/unused', demo=True)
            hub.draw()
            expected = pair.call_args_list[:]
            screen.lines.clear()
            self.assertEqual(choose_agent(screen, [SimpleNamespace(id='test', name='Test')]), 'test')
            self.assertEqual(pair.call_args_list[3:], expected)
            selected = next(line for line in screen.lines if '> Test' in line[2])
            self.assertEqual(selected[4], hub.color(2) | curses.A_BOLD)
            self.assertEqual(len(selected[2]), 117)

    def test_live_preview_cancel_save_and_demo(self):
        class Screen:
            def __init__(self, keys):
                self.keys = iter(keys)
                self.frames = []
            def keypad(self, value): pass
            def erase(self): pass
            def refresh(self): pass
            def getmaxyx(self): return 28, 120
            def addnstr(self, *args): self.frames.append(args[2])
            def get_wch(self):
                key = next(self.keys)
                if callable(key):
                    key()
                    return self.get_wch()
                return key
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, XDG_CONFIG_HOME=directory), \
             patch('curses.has_colors', return_value=False):
            save('cyan')
            original = config_path().read_bytes()
            current = Style()
            def assert_uncommitted():
                self.assertEqual(config_path().read_bytes(), original)
            screen = Screen(['l', assert_uncommitted, '\x1b'])
            self.assertEqual(edit_style(screen, current), current.config)
            self.assertEqual(config_path().read_bytes(), original)
            self.assertTrue(any('Tema: violet' in text for text in screen.frames))
            screen = Screen(['l', 'j', 'l', assert_uncommitted, '\n'])
            saved = edit_style(screen, current)
            self.assertEqual(saved['theme'], 'violet')
            self.assertEqual(saved['colors']['accent'], 'cyan')
            self.assertEqual(load(), saved)
            before_demo = config_path().read_bytes()
            edit_style(Screen(['l', '\n']), Style(), persist=False)
            self.assertEqual(config_path().read_bytes(), before_demo)

    def test_agent_selector_opens_settings_and_returns_to_same_agent(self):
        class Screen:
            def __init__(self): self.keys = iter(['S', '\n'])
            def keypad(self, value): pass
            def erase(self): pass
            def refresh(self): pass
            def getmaxyx(self): return 28, 120
            def addnstr(self, *args): pass
            def get_wch(self): return next(self.keys)
        with patch('agent_hub.style.edit_style', return_value=resolve({'theme': 'green'})) as editor, \
             patch('agent_hub.style.load', return_value=resolve({})), \
             patch('curses.has_colors', return_value=False), patch('curses.curs_set'):
            self.assertEqual(choose_agent(Screen(), [SimpleNamespace(id='test', name='Test')]), 'test')
            editor.assert_called_once()

    def test_colorless_terminal_keeps_selection_visible(self):
        with patch('agent_hub.style.load', return_value=resolve({})), \
             patch('curses.has_colors', return_value=False):
            self.assertEqual(Style().color(2), curses.A_REVERSE)
        with patch('agent_hub.style.load', return_value=resolve({'theme': 'mono'})), \
             patch('curses.has_colors', return_value=True), patch('curses.start_color') as start:
            self.assertEqual(Style().color(2), curses.A_REVERSE)
            start.assert_not_called()
