"""Original curses UI. No plugins, webviews, analytics, or network calls."""

import curses
from datetime import datetime
from pathlib import Path
import textwrap
import unicodedata

from .store import normalize, project_catalog, read_chats, read_projects, visible
from .navigation import sidebar


def clean(value):
    # Metadata must never become terminal escape sequences or injected lines.
    return "".join(c if not unicodedata.category(c).startswith("C") else " " for c in str(value))


class Hub:
    def __init__(self, screen, library, chats, home, demo=False, projects=()):
        self.screen, self.library, self.chats = screen, library, chats
        self.home, self.demo = home, demo
        self.imported = list(projects)
        self.projects = project_catalog(chats, self.imported, library)
        self.expanded = {p.id for p in self.projects if p.source != "discovered"}
        self.limits = {}
        self.others = False
        self.group = ("recent", "")
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

    def rows(self):
        return sidebar(self.chats, self.projects, self.library, self.expanded,
                       self.limits, self.query, self.archives, self.others)

    def sync(self):
        rows = self.rows()
        self.nav = min(self.nav, len(rows)-1)
        row = rows[self.nav]
        if self.focus == 0:
            group = (("project", row.parent) if row.parent else ("recent", "")) if row.kind == "chat" else (row.kind, row.value)
            if group[0] in ("project", "recent", "pinned", "section"):
                if self.group != group:
                    self.selected = 0
                self.group = group
            if row.kind == "chat":
                self.selected = next((i for i, c in enumerate(self.current()) if c.id == row.value), 0)
        self.selected = min(self.selected, max(0, len(self.current())-1))
        return rows

    def current(self):
        return visible(self.chats, self.library, self.group, self.query, self.archives, self.projects)

    def draw(self):
        self.screen.erase()
        rows = self.sync()
        height, width = self.screen.getmaxyx()
        if height < 16 or width < 66:
            self.put(0, 0, "Amplía la terminal a 66 × 16. q para salir.")
            self.screen.refresh()
            return
        self.put(1, 2, "◈  CODEX HUB", curses.A_BOLD | self.color(1))
        self.put(1, 23, "tu espacio de conversaciones", curses.A_DIM)
        self.put(2, 2, "DEMO · datos ficticios" if self.demo else "LOCAL · sin telemetría", self.color(3))
        chats = self.current()
        self.selected = min(self.selected, max(0, len(chats)-1))
        side = max(28, min(60, width*45//100))
        self.put(4, 2, "PROYECTOS", curses.A_BOLD if self.focus == 0 else curses.A_DIM)
        self.put(4, side+3, f"{'ARCHIVADOS' if self.archives else 'CONVERSACIONES'}  {len(chats)}",
                 curses.A_BOLD if self.focus else curses.A_DIM)
        room = height-10
        start = max(0, self.nav-room+1)
        for row, item in enumerate(rows[start:start+room], 5):
            index = start+row-5
            attr = self.color(2) | curses.A_BOLD if index == self.nav else curses.A_NORMAL
            if item.kind == "recent" and index != self.nav:
                attr = curses.A_BOLD | self.color(3)
            self.put(row, 2, " " + item.label.ljust(side-3), attr, side-2)
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
        project = next((p for p in self.projects if p.id == self.group[1]), None)
        detail = " · ".join(project.roots) if project else "Recientes" if self.group[0] == "recent" else self.group[1]
        self.put(height-5, side+3, ("Buscar: " + self.query) if self.query else detail, self.color(3))
        self.put(height-3, 2, self.message, self.color(1))
        self.put(height-2, 2, "j/k mover · h/l árbol · Tab panel · Enter abrir/plegar · p carpeta · n chat · q salir", curses.A_DIM)
        self.put(height-1, 2, "/ buscar · t recientes · espacio ★ · s sección · m mover · r título · a archivados · ? ayuda", curses.A_DIM)
        self.screen.refresh()

    def prompt(self, label, initial=""):
        text = initial
        while True:
            height, width = self.screen.getmaxyx()
            if height < 4 or width < 20:
                return None
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
            self.imported = read_projects(self.home)
        previous = {p.id for p in self.projects}
        self.projects = project_catalog(self.chats, self.imported, self.library)
        self.expanded.update(p.id for p in self.projects if p.id not in previous and p.source != "discovered")

    def select_project(self, ident):
        self.nav = next((i for i, row in enumerate(self.rows()) if row.kind == "project" and row.value == ident), 0)
        self.focus, self.selected = 0, 0

    def add_folder(self):
        path = self.pick_folder()
        if path is None:
            return
        root = normalize(path)
        existing = next((p for p in self.projects if root in p.roots and p.source != "discovered"), None)
        ident = existing.id if existing else self.library.add_project(root)
        self.reload()
        self.expanded.add(ident)
        self.select_project(ident)
        self.message = "Carpeta agregada. n crea su primera conversación."

    def pick_folder(self):
        """Select an existing folder; never create or remove filesystem entries."""
        project = next((p for p in self.projects if p.id == self.group[1]), None)
        current = Path(project.roots[0]) if project and project.roots and Path(project.roots[0]).is_dir() else Path.cwd()
        selected, hidden = 0, False
        notice = ""
        while True:
            try:
                children = sorted((p for p in current.iterdir() if p.is_dir()
                                   and (hidden or not p.name.startswith("."))), key=lambda p: p.name.casefold())
                folders = [current.parent] + children
            except OSError as error:
                notice, folders = str(error), [current.parent]
            selected = min(selected, len(folders)-1)
            self.screen.erase()
            height, width = self.screen.getmaxyx()
            if height < 12 or width < 40:
                self.put(0, 0, "Amplía la terminal. Esc cancela.")
                self.screen.refresh()
                if self.screen.get_wch() in ("q", "\x1b"):
                    return None
                continue
            self.put(1, 2, "AGREGAR CARPETA", curses.A_BOLD | self.color(1))
            self.put(2, 2, str(current), self.color(3))
            room = max(1, height-8)
            offset = max(0, selected-room+1)
            for index, folder in enumerate(folders[offset:offset+room], offset):
                label = ".." if index == 0 else folder.name
                attr = self.color(2) if index == selected else 0
                self.put(4+index-offset, 2, "▸ " + label, attr, width-4)
            self.put(height-3, 2, notice or "Espacio agrega la carpeta abierta, aunque no tenga conversaciones.", self.color(1))
            self.put(height-2, 2, "j/k mover · Enter/l entrar · h subir · espacio agregar · / ruta · . ocultas · Esc cancelar", curses.A_DIM)
            self.screen.refresh()
            key = self.screen.get_wch()
            if key in ("q", "\x1b"):
                return None
            if key == " ":
                return str(current)
            if key in ("j", curses.KEY_DOWN, "k", curses.KEY_UP):
                selected = max(0, min(len(folders)-1, selected + (1 if key in ("j", curses.KEY_DOWN) else -1)))
            elif key in ("\n", "\r", curses.KEY_ENTER, "l", curses.KEY_RIGHT):
                current, selected, notice = folders[selected], 0, ""
            elif key in ("h", curses.KEY_LEFT):
                current, selected, notice = current.parent, 0, ""
            elif key == ".":
                hidden, selected = not hidden, 0
            elif key == "/":
                path = self.prompt("Ruta (Ctrl+U limpia)", str(current))
                if path:
                    candidate = Path(path).expanduser().resolve()
                    if candidate.is_dir():
                        current, selected, notice = candidate, 0, ""
                    else:
                        notice = "La carpeta no existe: " + str(candidate)

    def new_chat(self, project_id=""):
        project = next((p for p in self.projects if p.id == (project_id or self.group[1])), None)
        chats = self.current()
        chat = chats[self.selected] if chats else None
        default = project.roots[0] if project and project.roots else chat.cwd if chat else str(Path.cwd())
        cwd = self.prompt("Carpeta del nuevo chat (Ctrl+U limpia)", default)
        if cwd:
            self.open_chat(cwd=cwd)

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
            "j/k: navega. h/l: pliega/expande proyectos. Tab: cambia de panel.",
            "Enter en proyecto: pliega/expande. Enter en un chat: continúa en Codex.",
            "p o + Agregar carpeta: selector de carpetas. Espacio agrega la carpeta abierta.",
            "El selector admite / para escribir ruta y . para ver carpetas ocultas.",
            "Importa proyectos de Codex, incluso vacíos. Otras carpetas descubre los demás chats.",
            "t: ir a recientes. Ver más: mostrar más conversaciones del proyecto o recientes.",
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
            rows = self.rows()
            row = rows[self.nav]
            chats = self.current()
            chat = chats[self.selected] if chats else None
            try:
                if key in ("q", "\x04"):
                    return
                height, width = self.screen.getmaxyx()
                if height < 16 or width < 66:
                    continue
                if key in ("h", curses.KEY_LEFT):
                    if self.focus:
                        self.focus = 0
                    elif row.kind == "project":
                        self.expanded.discard(row.value)
                    elif row.parent:
                        self.select_project(row.parent)
                    elif row.kind in ("more", "empty") and row.value != "recent":
                        self.select_project(row.value)
                elif key == "\t":
                    self.focus = 1-self.focus
                elif key in ("l", curses.KEY_RIGHT):
                    if self.focus == 0 and row.kind == "project":
                        if row.value in self.expanded:
                            self.nav = min(self.nav+1, len(rows)-1)
                        else:
                            self.expanded.add(row.value)
                    else:
                        self.focus = 1
                elif key in ("j", "k", curses.KEY_UP, curses.KEY_DOWN, "g", "G"):
                    count = len(rows) if self.focus == 0 else len(chats)
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
                    if self.focus:
                        if chat:
                            self.open_chat(chat)
                    elif row.kind == "project":
                        if row.value in self.expanded:
                            self.expanded.remove(row.value)
                        else:
                            self.expanded.add(row.value)
                    elif row.kind == "chat":
                        selected = next((c for c in self.chats if c.id == row.value), None)
                        if selected:
                            self.open_chat(selected)
                    elif row.kind == "more":
                        self.limits[row.value] = self.limits.get(row.value, 10 if row.value == "recent" else 5)+20
                    elif row.kind == "add":
                        self.add_folder()
                    elif row.kind == "empty":
                        self.new_chat(row.value)
                    elif row.kind == "others":
                        self.others = not self.others
                    else:
                        self.focus = 1
                elif key == "/":
                    query = self.prompt("Buscar", self.query)
                    if query is not None:
                        self.query, self.selected = query, 0
                        self.group, self.focus = ("recent", ""), 1
                        self.nav = next(i for i, r in enumerate(self.rows()) if r.kind == "recent")
                elif key == "\x1b":
                    self.query, self.selected = "", 0
                elif key == "a":
                    self.archives = not self.archives
                    self.selected = 0
                elif key == "R":
                    identity = (row.kind, row.value, row.parent)
                    self.reload()
                    self.nav = next((i for i, r in enumerate(self.rows())
                                     if (r.kind, r.value, r.parent) == identity), 0)
                    self.message = "Índice actualizado desde disco."
                elif key == "p":
                    self.add_folder()
                elif key == "t":
                    self.nav = next(i for i, r in enumerate(rows) if r.kind == "recent")
                    self.focus, self.selected = 0, 0
                elif key == "n":
                    self.new_chat()
                elif key == "s":
                    name = self.prompt("Nueva sección")
                    if name:
                        self.library.add_section(name)
                        self.message = "Sección creada: " + name
                elif key == " " and chat and (self.focus or row.kind == "chat"):
                    self.library.change(chat, pinned=not self.library.meta(chat).get("pinned"))
                elif key == "m" and chat and (self.focus or row.kind == "chat"):
                    section = self.prompt("Sección (vacío quita)", self.library.meta(chat).get("section", ""))
                    if section is not None:
                        self.library.add_section(section)
                        self.library.change(chat, section=section)
                elif key == "r" and chat and (self.focus or row.kind == "chat"):
                    title = self.prompt("Título local (vacío restaura)", self.library.meta(chat).get("title") or chat.title)
                    if title is not None:
                        self.library.change(chat, title=title)
                elif key == "?":
                    self.help()
            except (OSError, ValueError) as error:
                self.message = str(error)
