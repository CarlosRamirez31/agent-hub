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
from agent_hub.style import Style, config_path, load, resolve
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

    def test_colorless_terminal_keeps_selection_visible(self):
        with patch('agent_hub.style.load', return_value=resolve({})), \
             patch('curses.has_colors', return_value=False):
            self.assertEqual(Style().color(2), curses.A_REVERSE)
        with patch('agent_hub.style.load', return_value=resolve({'theme': 'mono'})), \
             patch('curses.has_colors', return_value=True), patch('curses.start_color') as start:
            self.assertEqual(Style().color(2), curses.A_REVERSE)
            start.assert_not_called()
