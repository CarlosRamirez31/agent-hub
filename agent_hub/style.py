"""Shared local terminal palette for every hub screen."""
import curses
import json
import os
from pathlib import Path

from .terminal import read_key

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
    config = resolve({"theme": theme} if isinstance(theme, str) else theme)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)
    return config


class Style:
    def __init__(self, config=None):
        self.config = load() if config is None else resolve(config)
        self.apply()

    def apply(self):
        config = self.config
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


def edit_style(screen, current, persist=True):
    """Preview in memory; only Enter commits, Esc restores the original palette."""
    from .ui import clean
    draft = resolve(current.config)
    fields = [("theme", "Tema"), ("accent", "Títulos y divisores"),
              ("secondary", "Detalles"), ("selection_fg", "Texto seleccionado"),
              ("selection_bg", "Fondo seleccionado")]
    selected = 0
    message = ""
    try:
        while True:
            preview = Style(draft)
            screen.erase()
            height, width = screen.getmaxyx()
            def line(y, text, attr=0):
                if 0 <= y < height and width > 3:
                    try:
                        screen.addnstr(y, 2, clean(text), width-3, attr)
                    except curses.error:
                        pass
            line(1, "◈  AGENT HUB · AJUSTES DE COLORES", preview.color(1) | curses.A_BOLD)
            line(2, "VISTA PREVIA · " + ("sin guardar en modo demo" if not persist else "Enter guarda · Esc cancela"), preview.color(3))
            if height >= 16 and width >= 40:
                for i, (field, label) in enumerate(fields):
                    value = draft["theme"] if field == "theme" else draft["colors"][field]
                    line(4+i, (("> " if i == selected else "  ") + label + ": " + value).ljust(width-3),
                         (preview.color(2) | curses.A_BOLD) if i == selected else curses.A_NORMAL)
                line(10, "PROYECTOS  │  PPE · 2 conversaciones", preview.color(1) | curses.A_BOLD)
                line(11, " ▸ PPE (2) │ Conversación seleccionada ".ljust(width-3), preview.color(2) | curses.A_BOLD)
                line(12, "LOCAL · Detalles de la conversación", preview.color(3))
            else:
                line(4, "Amplía la terminal a 40 × 16 para editar.")
            if message:
                line(height-3, message, preview.color(1))
            line(height-2, "j/k opción · h/l color · Enter guardar · Esc cancelar", curses.A_DIM)
            screen.refresh()
            key = read_key(screen)
            if key in ("q", "\x1b"):
                return current.config
            if height < 16 or width < 40:
                continue
            if key in ("j", curses.KEY_DOWN):
                selected = (selected+1) % len(fields)
            elif key in ("k", curses.KEY_UP):
                selected = (selected-1) % len(fields)
            elif key in ("h", "l", curses.KEY_LEFT, curses.KEY_RIGHT):
                field = fields[selected][0]
                choices = list(PRESETS if field == "theme" else COLORS)
                value = draft["theme"] if field == "theme" else draft["colors"][field]
                step = 1 if key in ("l", curses.KEY_RIGHT) else -1
                value = choices[(choices.index(value)+step) % len(choices)]
                if field == "theme":
                    draft = resolve({"theme": value})
                else:
                    draft["colors"][field] = value
                    if draft["theme"] == "mono":
                        draft["theme"] = "cyan"
                message = ""
            elif key in ("\n", "\r", curses.KEY_ENTER):
                try:
                    return save(draft) if persist else draft
                except OSError as error:
                    message = "No se pudo guardar: " + str(error)
    finally:
        current.apply()
