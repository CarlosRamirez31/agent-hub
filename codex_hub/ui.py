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
        self.others = False
        self.group = ("recent", "")
        self.focus = 0
        self.nav = self.selected = 0
        self.query = ""
        self.archives = False
        self.message = "j/k elige carpeta · l entra · Enter continúa el chat · h vuelve"
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
        return sidebar(self.chats, self.projects, self.library, self.archives, self.others)

    def sync(self):
        rows = self.rows()
        self.nav = min(self.nav, len(rows)-1)
        self.selected = min(self.selected, max(0, len(self.current())-1))
        return rows

    def enter_space(self, row):
        """Commit a folder only on l/Enter/Tab, never while hovering over it."""
        if row.kind in ("project", "recent", "pinned", "section"):
            group = (row.kind, row.value)
            if group != self.group:
                self.query, self.selected = "", 0
            self.group, self.focus = group, 1
            self.message = "j/k elige chat · Enter continúa · f crea copia · h vuelve a carpetas"
        elif row.kind == "add":
            self.add_folder()
        elif row.kind == "others":
            self.others = not self.others

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
        active_project = next((p for p in self.projects if self.group == ("project", p.id)), None)
        heading = active_project.name if active_project else {"recent": "Recientes", "pinned": "Favoritos"}.get(self.group[0], self.group[1])
        self.put(4, side+3, f"{heading} · {len(chats)}" + (" · Archivados" if self.archives else ""),
                 curses.A_BOLD if self.focus else curses.A_DIM)
        room = height-10
        start = max(0, self.nav-room+1)
        for row, item in enumerate(rows[start:start+room], 5):
            index = start+row-5
            attr = self.color(2) | curses.A_BOLD if index == self.nav and not self.focus else curses.A_NORMAL
            if (item.kind, item.value) == self.group and not (index == self.nav and not self.focus):
                attr = curses.A_BOLD | self.color(1)
            self.put(row, 2, " " + item.label.ljust(side-3), attr, side-2)
        for y in range(4, height-4):
            self.put(y, side, "│", self.color(1))
        list_rows = max(1, (height-12)//2)
        offset = max(0, self.selected-list_rows+1)
        for row, chat in enumerate(chats[offset:offset+list_rows]):
            index = offset+row
            meta = self.library.meta(chat)
            attr = (self.color(2) if self.focus else self.color(1)) | curses.A_BOLD if index == self.selected else curses.A_BOLD
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
        self.put(height-2, 2, "j/k mover · l entrar · h volver · Enter continuar · f copia · p carpeta · n chat · q salir", curses.A_DIM)
        self.put(height-1, 2, "/ buscar aquí · t recientes · espacio ★ · s sección · m mover · r título · R sincronizar · ? ayuda", curses.A_DIM)
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
        self.projects = project_catalog(self.chats, self.imported, self.library)
        if self.group[0] == "project" and not any(p.id == self.group[1] for p in self.projects):
            self.group, self.query, self.selected = ("recent", ""), "", 0

    def select_project(self, ident):
        self.nav = next((i for i, row in enumerate(self.rows()) if row.kind == "project" and row.value == ident), 0)
        self.focus = 0

    def add_folder(self):
        path = self.pick_folder()
        if path is None:
            return
        root = normalize(path)
        existing = next((p for p in self.projects if root in p.roots and p.source != "discovered"), None)
        ident = existing.id if existing else self.library.add_project(root)
        self.reload()
        self.select_project(ident)
        self.message = "Carpeta agregada. n crea su primera conversación."

    def pick_folder(self):
        """Select an existing folder; never create or remove filesystem entries."""
        hovered = self.rows()[self.nav]
        ident = hovered.value if not self.focus and hovered.kind == "project" else self.group[1]
        project = next((p for p in self.projects if p.id == ident), None)
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
        hovered = self.rows()[self.nav]
        ident = project_id or (hovered.value if not self.focus and hovered.kind == "project" else self.group[1])
        project = next((p for p in self.projects if p.id == ident), None)
        chats = self.current()
        chat = chats[self.selected] if chats else None
        default = project.roots[0] if project and project.roots else chat.cwd if chat else str(Path.cwd())
        cwd = self.prompt("Carpeta del nuevo chat (Ctrl+U limpia)", default)
        if cwd:
            self.open_chat(cwd=cwd)

    def open_chat(self, chat=None, cwd=None, fork=False):
        if self.demo:
            self.message = "Modo demo: no inicia Codex ni guarda cambios."
            return
        from .cli import launch
        curses.def_prog_mode()
        curses.endwin()
        try:
            try:
                code = launch(chat, cwd, fork=fork)
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
            "j/k en carpetas solo cambia la selección; la lista derecha permanece igual.",
            "l, Enter o Tab en carpeta: entra a sus conversaciones. h: vuelve a carpetas.",
            "j/k en conversaciones: elige chat. Enter: continúa la MISMA conversación.",
            "f en conversaciones: continúa en una copia independiente (Codex fork).",
            "Si Codex dice 'open in another app': cierra ese chat allí y pulsa r para reintentar.",
            "También puedes usar f en esa pantalla para crear una copia; no fuerza el desbloqueo.",
            "p o + Agregar carpeta: selector de carpetas. Espacio agrega la carpeta abierta.",
            "El selector admite / para escribir ruta y . para ver carpetas ocultas.",
            "Importa proyectos de Codex, incluso vacíos. Otras carpetas descubre los demás chats.",
            "t: abrir recientes. Los números junto a las carpetas cuentan conversaciones.",
            "n: chat nuevo en una carpeta. Sal de Codex con /quit para volver al hub.",
            "/: buscar en la lista abierta. Esc limpia la búsqueda. g/G: primero/último.",
            "Espacio: favorito. s: crear sección. m: asignar sección (vacío la quita).",
            "r: título local (vacío restaura el original). a: vista de archivados.",
            "R: releer proyectos/chats y sus eliminaciones del índice local de Codex.",
            "Al abrir y al volver de Codex también refresca. No sincroniza ChatGPT web.",
            "Las carpetas creadas aquí son locales al hub; no hay sincronización de dos vías.",
            "No elimina chats ni modifica el índice de Codex. No lee credenciales.",
            "El hub no usa red. Codex conserva su propia configuración e integraciones.",
            "Actualización manual: codex-hub update (conecta solo con tu repo GitHub).",
            "j/k desplaza esta ayuda; Enter o Esc vuelve.",
        ]
        offset = 0
        while True:
            self.screen.erase()
            height, width = self.screen.getmaxyx()
            wrapped = [part for line in lines for part in [*textwrap.wrap(line, max(20, width-4)), ""]]
            room = max(1, height-3)
            offset = min(offset, max(0, len(wrapped)-room))
            for row, line in enumerate(wrapped[offset:offset+room], 1):
                self.put(row, 2, line)
            self.put(height-1, 2, "j/k desplaza · Enter/Esc vuelve", self.color(1))
            self.screen.refresh()
            key = self.screen.get_wch()
            if key in ("j", curses.KEY_DOWN):
                offset += 1
            elif key in ("k", curses.KEY_UP):
                offset = max(0, offset-1)
            else:
                return

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
                    self.focus = 0
                elif key == "\t":
                    if self.focus:
                        self.focus = 0
                    else:
                        self.enter_space(row)
                elif key in ("l", curses.KEY_RIGHT):
                    if self.focus == 0:
                        self.enter_space(row)
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
                        self.nav = index
                    else:
                        self.selected = index
                elif key in ("\n", "\r", curses.KEY_ENTER):
                    if self.focus:
                        if chat:
                            self.open_chat(chat)
                    else:
                        self.enter_space(row)
                elif key == "f" and self.focus and chat:
                    self.open_chat(chat, fork=True)
                elif key == "/":
                    self.focus = 1
                    query = self.prompt("Buscar", self.query)
                    if query is not None:
                        self.query, self.selected = query, 0
                elif key == "\x1b":
                    if self.query:
                        self.query, self.selected = "", 0
                    else:
                        self.focus = 0
                elif key == "a":
                    self.archives = not self.archives
                    self.selected = 0
                elif key == "R":
                    identity = (row.kind, row.value)
                    self.reload()
                    self.nav = next((i for i, r in enumerate(self.rows())
                                     if (r.kind, r.value) == identity), 0)
                    self.message = "Índice actualizado desde disco."
                elif key == "p":
                    self.add_folder()
                elif key == "t":
                    self.nav = next(i for i, r in enumerate(rows) if r.kind == "recent")
                    self.enter_space(rows[self.nav])
                elif key == "n":
                    self.new_chat()
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
