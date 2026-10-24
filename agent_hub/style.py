"""Shared local terminal palette for every hub screen."""
import curses
import json
import os
from pathlib import Path

PRESETS = {
    "cyan": {"accent": "cyan", "secondary": "magenta", "selection_fg": "black", "selection_bg": "cyan"},
    "violet": {"accent": "magenta", "secondary": "cyan", "selection_fg": "black", "selection_bg": "magenta"},
    "green": {"accent": "green", "secondary": "yellow", "selection_fg": "black", "selection_bg": "green"},
    "blue": {"accent": "blue", "secondary": "cyan", "selection_fg": "white", "selection_bg": "blue"},
    "mono": {"accent": "default", "secondary": "default", "selection_fg": "black", "selection_bg": "white"},
}
COLORS = {name: index for index, name in enumerate(("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"))}
COLORS["default"] = -1


def config_path():
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home()/".config")))/"agent-hub/style.json"


def resolve(config):
    if not isinstance(config, dict) or set(config) - {"theme", "colors"}:
        raise ValueError("style.json: usa solo theme y colors.")
    theme = config.get("theme", "cyan")
    if not isinstance(theme, str) or theme not in PRESETS:
        raise ValueError("style.json: tema desconocido; usa " + ", ".join(PRESETS))
    overrides = config.get("colors", {})
    if not isinstance(overrides, dict) or set(overrides) - set(PRESETS[theme]):
        raise ValueError("style.json: colores admitidos: " + ", ".join(PRESETS[theme]))
    palette = {**PRESETS[theme], **overrides}
    if any(not isinstance(value, str) or value not in COLORS for value in palette.values()):
        raise ValueError("style.json: colores válidos: " + ", ".join(COLORS))
    return {"theme": theme, "colors": palette}


def load():
    path = config_path()
    return resolve(json.loads(path.read_text()) if path.exists() else {})


def save(theme):
    config = resolve({"theme": theme})
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)
    return config


class Style:
    def __init__(self):
        config = load()
        self.colors = False
        if not curses.has_colors() or config["theme"] == "mono":
            return
        try:
            curses.start_color()
            try:
                curses.use_default_colors()
                default = -1
            except curses.error:
                default = curses.COLOR_BLACK
            palette = {key: (COLORS[value] if value != "default" else default)
                       for key, value in config["colors"].items()}
            curses.init_pair(1, palette["accent"], default)
            curses.init_pair(2, palette["selection_fg"], palette["selection_bg"])
            curses.init_pair(3, palette["secondary"], default)
            self.colors = True
        except curses.error:
            pass

    def color(self, pair):
        if self.colors:
            return curses.color_pair(pair)
        return curses.A_REVERSE if pair == 2 else curses.A_NORMAL
