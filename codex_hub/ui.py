"""Original curses UI. No plugins, webviews, analytics, or network calls."""

import curses
from datetime import datetime
from pathlib import Path
import textwrap
import unicodedata

from .store import read_chats, visible


def clean(value):
    # Metadata must never become terminal escape sequences or injected lines.
    return "".join(c if not unicodedata.category(c).startswith("C") else " " for c in str(value))


class Hub:
    def __init__(self, screen, library, chats, home, demo=False):
        self.screen, self.library, self.chats = screen, library, chats
        self.home, self.demo = home, demo
        self.group = ("all", "")
        self.focus = 0
        self.nav = self.selected = 0
        self.query = ""
        self.archives = False
        self.message = "Todo local · Enter abre Codex · al salir vuelves aquí"
        self.colors = False
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        if curses.has_colors():
            curses.start_color()
            try:
                curses.use_default_colors()
                background = -1
            except curses.error:
                background = curses.COLOR_BLACK
            curses.init_pair(1, curses.COLOR_CYAN, background)
            curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)
            curses.init_pair(3, curses.COLOR_MAGENTA, background)
            self.colors = True
        self.screen.keypad(True)

    def color(self, pair):
        return curses.color_pair(pair) if self.colors else curses.A_NORMAL

    def put(self, y, x, text, attr=0, width=None):
        height, columns = self.screen.getmaxyx()
        if 0 <= y < height and 0 <= x < columns-1:
            try:
                self.screen.addnstr(y, x, clean(text), min(width or columns, columns-x-1), attr)
            except curses.error:
                pass

    def groups(self):
        result = [("Todos los chats", ("all", "")), ("★ Favoritos", ("pinned", ""))]
        result += [("§ " + name, ("section", name)) for name in self.library.data["sections"]]
        projects = sorted({c.cwd for c in self.chats if c.archived == self.archives})
        result += [("▸ " + (Path(p).name or p), ("project", p)) for p in projects]
        return result

    def current(self):
        return visible(self.chats, self.library, self.group, self.query, self.archives)

    def draw(self):
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        if height < 16 or width < 66:
            self.put(0, 0, "Amplía la terminal a 66 × 16. q para salir.")
            self.screen.refresh()
            return
        self.put(1, 2, "◈  CODEX HUB", curses.A_BOLD | self.color(1))
        self.put(1, 23, "tu espacio de conversaciones", curses.A_DIM)
        self.put(2, 2, "DEMO · datos ficticios" if self.demo else "LOCAL · sin telemetría", self.color(3))
        groups = self.groups()
        self.nav = min(self.nav, len(groups)-1)
        self.group = groups[self.nav][1]
        chats = self.current()
        self.selected = min(self.selected, max(0, len(chats)-1))
        side = max(22, min(36, width//3))
        self.put(4, 2, "ESPACIOS", curses.A_BOLD if self.focus == 0 else curses.A_DIM)
        self.put(4, side+3, f"{'ARCHIVADOS' if self.archives else 'CONVERSACIONES'}  {len(chats)}",
                 curses.A_BOLD if self.focus else curses.A_DIM)
        room = height-10
        start = max(0, self.nav-room+1)
        for row, (label, _) in enumerate(groups[start:start+room], 5):
            index = start+row-5
            attr = self.color(2) | curses.A_BOLD if index == self.nav else curses.A_NORMAL
            self.put(row, 2, " " + label.ljust(side-3), attr, side-2)
        for y in range(4, height-4):
            self.put(y, side, "│", self.color(1))
        list_rows = max(1, (height-12)//2)
        offset = max(0, self.selected-list_rows+1)
        for row, chat in enumerate(chats[offset:offset+list_rows]):
            index = offset+row
            meta = self.library.meta(chat)
            attr = self.color(2) | curses.A_BOLD if index == self.selected else curses.A_BOLD
            title = ("★ " if meta.get("pinned") else "  ") + (meta.get("title") or chat.title)
            self.put(6+row*2, side+3, title.ljust(width-side-5), attr)
            try:
                date = datetime.fromtimestamp(chat.updated).strftime("%d %b %H:%M")
            except (ValueError, OSError, OverflowError):
                date = "fecha desconocida"
            self.put(7+row*2, side+5, date + " · " + chat.cwd, curses.A_DIM)
        if not chats:
            self.put(7, side+3, "No hay chats en esta vista.", curses.A_DIM)
            self.put(9, side+3, "n crea uno · / busca · a archivados", curses.A_DIM)
        self.put(height-5, side+3, ("Buscar: " + self.query) if self.query else self.group[1], self.color(3))
        self.put(height-3, 2, self.message, self.color(1))
        self.put(height-2, 2, "h/l panel · j/k mover · Enter abrir · / buscar · n nuevo · q salir", curses.A_DIM)
        self.put(height-1, 2, "espacio ★ · s sección · m mover · r título · a archivados · R refrescar · ? ayuda", curses.A_DIM)
        self.screen.refresh()

    def prompt(self, label, initial=""):
        text = initial
        while True:
            height, width = self.screen.getmaxyx()
            self.screen.move(height-3, 0)
            self.screen.clrtoeol()
            self.put(height-3, 2, label + ": " + text, self.color(1), width-3)
            self.screen.refresh()
            key = self.screen.get_wch()
            if key in ("\n", "\r", curses.KEY_ENTER):
                return text.strip()
            if key == "\x1b":
                return None
            if key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                text = text[:-1]
            elif key == "\x15":
                text = ""
            elif isinstance(key, str) and key.isprintable():
                text += key

    def reload(self):
        if not self.demo:
            self.chats = read_chats(self.home)

    def open_chat(self, chat=None, cwd=None):
        if self.demo:
            self.message = "Modo demo: no inicia Codex ni guarda cambios."
            return
        from .cli import launch
        curses.def_prog_mode()
        curses.endwin()
        try:
            try:
                code = launch(chat, cwd)
            except KeyboardInterrupt:
                code = 130
            self.message = f"Codex terminó ({code}). Tu biblioteca sigue aquí."
        finally:
            curses.reset_prog_mode()
            self.screen.keypad(True)
            self.screen.clear()
        self.reload()

    def help(self):
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        lines = [
            "CODEX HUB · AYUDA",
            "h/l o Tab: cambia entre espacios y conversaciones. j/k o flechas: navega.",
            "Enter en espacios: pasa a chats. Enter en un chat: continúa en Codex.",
            "n: chat nuevo en una carpeta. Sal de Codex con /quit para volver al hub.",
            "/: buscar título o carpeta. Esc limpia la búsqueda. g/G: primero/último.",
            "Espacio: favorito. s: crear sección. m: asignar sección (vacío la quita).",
            "r: título local (vacío restaura el original). a: vista de archivados.",
            "R: refrescar. Los títulos, favoritos y secciones son propios del hub.",
            "No elimina chats ni modifica el índice de Codex. No lee credenciales.",
            "El hub no usa red. Codex conserva su propia configuración e integraciones.",
            "Actualización manual: codex-hub update (conecta solo con tu repo GitHub).",
            "Pulsa una tecla para volver.",
        ]
        row = 1
        for line in lines:
            for wrapped in textwrap.wrap(line, max(20, width-4)):
                if row < height-1:
                    self.put(row, 2, wrapped, self.color(1) if row == 1 else 0)
                    row += 1
            row += 1
        self.screen.refresh()
        self.screen.get_wch()

    def run(self):
        while True:
            self.draw()
            key = self.screen.get_wch()
            chats = self.current()
            chat = chats[self.selected] if chats else None
            try:
                if key in ("q", "\x04"):
                    return
                if key in ("h", curses.KEY_LEFT):
                    self.focus = 0
                elif key in ("l", curses.KEY_RIGHT, "\t"):
                    self.focus = 1-self.focus if key == "\t" else 1
                elif key in ("j", "k", curses.KEY_UP, curses.KEY_DOWN, "g", "G"):
                    count = len(self.groups()) if self.focus == 0 else len(chats)
                    index = self.nav if self.focus == 0 else self.selected
                    if key == "g":
                        index = 0
                    elif key == "G":
                        index = count-1
                    else:
                        index += 1 if key in ("j", curses.KEY_DOWN) else -1
                    index = max(0, min(index, count-1))
                    if self.focus == 0:
                        self.nav, self.selected = index, 0
                    else:
                        self.selected = index
                elif key in ("\n", "\r", curses.KEY_ENTER):
                    if self.focus == 0:
                        self.focus = 1
                    elif chat:
                        self.open_chat(chat)
                elif key == "/":
                    query = self.prompt("Buscar", self.query)
                    if query is not None:
                        self.query, self.selected = query, 0
                elif key == "\x1b":
                    self.query, self.selected = "", 0
                elif key == "a":
                    self.archives = not self.archives
                    self.selected = 0
                elif key == "R":
                    self.reload()
                    self.message = "Índice actualizado desde disco."
                elif key == "n":
                    default = self.group[1] if self.group[0] == "project" else (chat.cwd if chat else str(Path.cwd()))
                    cwd = self.prompt("Carpeta (Ctrl+U limpia)", default)
                    if cwd:
                        self.open_chat(cwd=cwd)
                elif key == "s":
                    name = self.prompt("Nueva sección")
                    if name:
                        self.library.add_section(name)
                        self.message = "Sección creada: " + name
                elif key == " " and chat and self.focus:
                    self.library.change(chat, pinned=not self.library.meta(chat).get("pinned"))
                elif key == "m" and chat and self.focus:
                    section = self.prompt("Sección (vacío quita)", self.library.meta(chat).get("section", ""))
                    if section is not None:
                        self.library.add_section(section)
                        self.library.change(chat, section=section)
                elif key == "r" and chat and self.focus:
                    title = self.prompt("Título local (vacío restaura)", self.library.meta(chat).get("title") or chat.title)
                    if title is not None:
                        self.library.change(chat, title=title)
                elif key == "?":
                    self.help()
            except (OSError, ValueError) as error:
                self.message = str(error)
