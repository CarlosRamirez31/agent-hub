"""Original curses UI. No plugins, webviews, analytics, or network calls."""

import curses
import sqlite3
from datetime import datetime
from pathlib import Path
import textwrap
import unicodedata

from .store import normalize, project_catalog, read_chats, read_projects, visible
from .navigation import sidebar
from .style import Style, edit_style
from .terminal import prepare_input, read_key


def clean(value):
    # Metadata must never become terminal escape sequences or injected lines.
    return "".join(c if not unicodedata.category(c).startswith("C") else " " for c in str(value))


class Hub:
    def __init__(self, screen, library, chats, home, demo=False, projects=(), manager=None, adapter=None):
        self.screen, self.library, self.chats = screen, library, chats
        self.home, self.demo = home, demo
        self.manager, self.adapter, self.next_agent = manager, adapter, None
        self.imported = list(projects)
        self.projects = project_catalog(chats, self.imported, library)
        self.others = False
        self.group = ("recent", "")
        self.focus = 0
        self.nav = self.selected = 0
        self.query = ""
        self.archives = False
        self.message = "j/k elige carpeta · l entra · Enter continúa el chat · h vuelve"
        self.style = Style()
        prepare_input(self.screen)
        self.usage = None
        if adapter is not None and not demo:
            from .usage import for_agent
            self.usage = for_agent(adapter)

    def color(self, pair):
        return self.style.color(pair)

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
        self.nav = max(0, min(self.nav, len(rows)-1))
        self.selected = max(0, min(self.selected, max(0, len(self.current())-1)))
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
        self.put(1, 2, "◈  AGENT HUB", curses.A_BOLD | self.color(1))
        self.put(1, 23, self.adapter.name if self.adapter else "tu espacio de conversaciones", curses.A_DIM)
        self.put(2, 2, "DEMO · datos ficticios" if self.demo else "LOCAL · sin telemetría", self.color(3))
        self.put(3, 2, "[n Nueva conversación]  [o Abrir]  [u Actualizar cuota]", self.color(1))
        chats = self.current()
        self.selected = max(0, min(self.selected, max(0, len(chats)-1)))
        side = max(28, min(60, width*45//100))
        self.put(4, 2, "PROYECTOS", curses.A_BOLD if self.focus == 0 else curses.A_DIM)
        active_project = next((p for p in self.projects if self.group == ("project", p.id)), None)
        heading = active_project.name if active_project else {"recent": "Recientes", "pinned": "Favoritos"}.get(self.group[0], self.group[1])
        self.put(4, side+3, f"{heading} · {len(chats)}" + (" · Archivados" if self.archives else ""),
                 curses.A_BOLD if self.focus else curses.A_DIM)
        room = height-13
        start = max(0, self.nav-room+1)
        for row, item in enumerate(rows[start:start+room], 5):
            index = start+row-5
            attr = self.color(2) | curses.A_BOLD if index == self.nav and not self.focus else curses.A_NORMAL
            if (item.kind, item.value) == self.group and not (index == self.nav and not self.focus):
                attr = curses.A_BOLD | self.color(1)
            self.put(row, 2, " " + item.label.ljust(side-3), attr, side-2)
        for y in range(4, height-8):
            self.put(y, side, "│", self.color(1))
        list_rows = max(1, (height-15)//2)
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
        quota = self.usage.lines() if self.usage else ["CUOTA · demo sin consultas" if self.demo else "CUOTA · agente no configurado"]
        for index, line in enumerate(quota[:3]):
            self.put(height-8+index, 2, line, self.color(3) if index else curses.A_DIM)
        if len(quota) > 3:
            self.put(height-6, 2, "Más ventanas: U muestra todos los límites y reinicios", self.color(3))
        project = next((p for p in self.projects if p.id == self.group[1]), None)
        detail = " · ".join(project.roots) if project else "Recientes" if self.group[0] == "recent" else self.group[1]
        self.put(height-5, side+3, ("Buscar: " + self.query) if self.query else detail, self.color(3))
        self.put(height-3, 2, self.message, self.color(1))
        self.put(height-2, 2, "n nueva · o/Enter abrir · j/k mover · h volver · f copia · p carpeta · d eliminar · q salir", curses.A_DIM)
        self.put(height-1, 2, "/ buscar · t recientes · x pasar contexto · A agentes · y ruta JSON · R sincronizar · T tareas · ? ayuda", curses.A_DIM)
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
            key = read_key(self.screen)
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
            if self.manager:
                self.manager.sync([self.adapter.id])
                self.chats, self.imported = self.manager.snapshot(self.adapter.id)
                self.library = self.manager.library(self.adapter.id)
            else:
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
                if read_key(self.screen) in ("q", "\x1b"):
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
            key = read_key(self.screen)
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
                if self.manager:
                    if chat:
                        code = self.manager.open(self.manager.route(self.adapter.id, chat, self.projects), fork=fork)
                    else:
                        code = self.adapter.launch(cwd or str(Path.cwd()))
                else:
                    code = launch(chat, cwd, fork=fork)
            except KeyboardInterrupt:
                code = 130
            name = self.adapter.name if self.adapter else "Codex"
            self.message = f"{name} terminó ({code}). Tu biblioteca sigue aquí."
        finally:
            curses.reset_prog_mode()
            self.screen.keypad(True)
            self.screen.clear()
        self.reload()
        if self.usage:
            self.usage.refresh(force=True)

    def transfer_chat(self, chat):
        if not self.manager:
            self.message = "Abre agent-hub para transferir entre agentes reales."
            return
        from .cli import choose_agent
        targets = [a for a in self.manager.agents if a.id != self.adapter.id and a.available and a.prompt]
        if not targets:
            raise ValueError("No hay otro agente instalado con recepción de contexto configurada.")
        target = targets[0].id if len(targets) == 1 else choose_agent(self.screen, targets, "PASAR CONTEXTO · AGENTE DESTINO")
        if not target:
            return
        self.message = "Preparando contexto visible de la conversación seleccionada…"
        self.draw()
        route = self.manager.prepare_transfer(self.manager.route(self.adapter.id, chat, self.projects), target)
        curses.def_prog_mode()
        curses.endwin()
        try:
            self.manager.open(route)
        finally:
            curses.reset_prog_mode()
            self.screen.keypad(True)
            self.screen.clear()
        self.next_agent = target

    def confirm_delete(self, lines, phrase):
        offset = 0
        while True:
            self.screen.erase()
            height, width = self.screen.getmaxyx()
            self.put(1, 2, "ELIMINAR · CONFIRMACIÓN", self.color(1) | curses.A_BOLD)
            wrapped = [part for line in lines for part in [*textwrap.wrap(clean(line), max(20, width-4)), ""]]
            room = max(1, height-8)
            offset = min(offset, max(0, len(wrapped)-room))
            for y, line in enumerate(wrapped[offset:offset+room], 3):
                self.put(y, 2, line)
            self.put(height-2, 2, "j/k revisar · c confirmar · Esc/q cancelar", curses.A_DIM)
            self.screen.refresh()
            key = read_key(self.screen)
            if key in ("q", "\x1b"):
                return False
            if key in ("j", curses.KEY_DOWN):
                offset += 1
            elif key in ("k", curses.KEY_UP):
                offset = max(0, offset-1)
            elif key == "c" and height >= 12 and width >= 40:
                return self.prompt("Escribe " + phrase) == phrase

    def delete_selected(self, row, chat):
        from .deletion import delete_chat, delete_folder, folder_plan
        if self.focus and chat:
            title = self.library.meta(chat).get("title") or chat.title
            lines = ["Conversación: " + title, "ID: " + chat.id,
                     "Agente: " + (self.adapter.name if self.adapter else "Demo"),
                     "Se eliminará del historial original y de Agent Hub, con sus mensajes y subagentes que el agente elimine en cascada.",
                     "Los archivos del proyecto se conservan. No hay deshacer."]
            if self.confirm_delete(lines, "ELIMINAR"):
                if self.demo:
                    self.chats = [c for c in self.chats if c.id != chat.id]
                elif self.manager:
                    delete_chat(self.manager, self.adapter.id, chat, confirmed=True)
                else:
                    raise ValueError("La eliminación necesita un gestor de agentes.")
                self.reload()
                if not self.current():
                    self.focus = 0
                self.message = "Conversación eliminada." + (" Solo datos ficticios." if self.demo else "")
            else:
                self.message = "Eliminación cancelada."
        elif not self.focus and row.kind == "project":
            if self.demo:
                self.message = "Modo demo: no elimina carpetas físicas."
                return
            if not self.manager:
                raise ValueError("La eliminación necesita un gestor de agentes.")
            self.message = "Revisando carpetas y conversaciones de todos los agentes…"
            self.draw()
            plan = folder_plan(self.manager, self.adapter.id, row.value)
            lines = ["Carpeta: " + plan['name'],
                     "Se borrarán permanentemente los directorios siguientes, con TODOS sus archivos, incluidos ocultos y repositorios Git:",
                     *plan['roots'],
                     f"Conversaciones originales: {len(plan['conversations'])} (todos los agentes registrados; incluye archivadas y sesiones ocultas de Hermes).",
                     *[agent + " · " + chat.title + " · " + chat.id for agent, chat in plan['conversations']],
                     "Se quitarán los proyectos asociados del hub y los proyectos nativos de Codex afectados.",
                     "No se borran repositorios remotos, copias en otras rutas ni servicios externos. No hay deshacer."]
            if self.confirm_delete(lines, "ELIMINAR CARPETA"):
                try:
                    count = delete_folder(self.manager, plan, confirmed=True)
                finally:
                    self.reload()
                self.group, self.selected, self.focus = ("recent", ""), 0, 0
                self.message = f"Carpeta y archivos eliminados; {count} conversaciones eliminadas."
            else:
                self.message = "Eliminación cancelada."
        else:
            self.message = "d elimina el chat seleccionado o una carpeta de proyectos; no elimina Recientes ni secciones."

    def usage_details(self):
        offset = 0
        while True:
            self.screen.erase()
            height, width = self.screen.getmaxyx()
            lines = self.usage.lines() if self.usage else ["Cuota no disponible en demo."]
            wrapped = [part for line in lines for part in textwrap.wrap(clean(line), max(20, width-4))]
            room = max(1, height-5)
            offset = max(0, min(offset, max(0, len(wrapped)-room)))
            self.put(1, 2, "USO Y PRÓXIMOS REINICIOS", curses.A_BOLD | self.color(1))
            for y, line in enumerate(wrapped[offset:offset+room], 3):
                self.put(y, 2, line, self.color(3))
            self.put(height-1, 2, "j/k desplaza · u actualizar · Enter/Esc vuelve", curses.A_DIM)
            self.screen.refresh()
            timed = hasattr(self.screen, 'timeout')
            if timed:
                self.screen.timeout(1000)
            try:
                key = read_key(self.screen)
            except curses.error:
                continue
            finally:
                if timed:
                    self.screen.timeout(-1)
            if key in ("q", "\x1b", "\n", "\r", curses.KEY_ENTER):
                return
            if key in ("j", curses.KEY_DOWN):
                offset += 1
            elif key in ("k", curses.KEY_UP):
                offset -= 1
            elif key == "u" and self.usage:
                self.usage.refresh(force=True)

    def help(self):
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        lines = [
            "AGENT HUB · AYUDA",
            "d: eliminar chat original; en carpetas borra archivos y conversaciones de todos los agentes. Siempre pide confirmación escrita.",
            "Ctrl-C sale del hub. Las combinaciones Ctrl sin asignar se ignoran; no suspenden el menú.",
            "S: ajustes de colores con vista previa. Enter guarda; Esc cancela.",
            "Con un agente entras directamente; con varios eliges. A cambia de agente.",
            "x pasa contexto del chat seleccionado a otro agente; crea una continuación separada.",
            "El proyecto se llama 'Proyecto - From Origen' y conserva la carpeta de código.",
            "y guarda su ruta JSON; agent-hub open --route-file abre esa conversación exacta.",
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
            "n: nueva conversación en la carpeta elegida. o/Enter: abrir la seleccionada.",
            "u: actualizar cuota; U: ver todos los límites, reinicios y tiempo restante.",
            "Las cuotas son de la cuenta/proveedor, compartidas con sus otras apps. No se inventan periodos diarios o mensuales.",
            "/: buscar en la lista abierta. Esc limpia la búsqueda. g/G: primero/último.",
            "Espacio: favorito. s: crear sección. m: asignar sección (vacío la quita).",
            "r: título local (vacío restaura el original). a: vista de archivados.",
            "R: releer proyectos/chats y sus eliminaciones del índice local de Codex.",
            "Al abrir y al volver de Codex también refresca. No sincroniza ChatGPT web.",
            "Las carpetas creadas aquí son locales al hub; no hay sincronización de dos vías.",
            "Solo d confirmado elimina mediante el agente; nunca escribe directamente sus bases. No lee credenciales.",
            "Las cuotas se consultan mediante el cliente nativo, sin pedir respuestas al modelo ni leer sus credenciales.",
            "Actualización manual: agent-hub update (conecta solo con tu repo GitHub).",
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
            key = read_key(self.screen)
            if key in ("j", curses.KEY_DOWN):
                offset += 1
            elif key in ("k", curses.KEY_UP):
                offset = max(0, offset-1)
            elif key in ("\n", "\r", curses.KEY_ENTER, "\x1b", "q", "h"):
                return

    def run(self):
        while True:
            prepare_input(self.screen)
            if self.usage:
                self.usage.refresh()
            self.draw()
            timed = hasattr(self.screen, 'timeout')
            if timed:
                self.screen.timeout(1000)
            try:
                key = read_key(self.screen)
            except curses.error:
                continue
            finally:
                if timed:
                    self.screen.timeout(-1)
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
                if key == "S":
                    self.style = Style(edit_style(self.screen, self.style, persist=not self.demo))
                elif key == "u":
                    if self.usage:
                        started = self.usage.refresh(force=True)
                        self.message = "Consultando cuota en segundo plano…" if started else "Consulta en curso o reciente; espera unos segundos."
                elif key == "U":
                    self.usage_details()
                elif key == "A" and self.manager:
                    self.next_agent = "select"
                    return
                elif key == "T":
                    from .engine.tui import Dashboard
                    if self.manager:
                        Dashboard(self.screen, self.manager.cache, self.manager.state).run()
                    else:
                        from .cache import Cache
                        memory = Cache(':memory:')
                        try:
                            Dashboard(self.screen, memory, Path('.'), demo=True).run()
                        finally:
                            memory.close()
                    self.message = "Volviste a tus conversaciones. T abre tareas."
                elif key == "d":
                    self.delete_selected(row, chat)
                elif key == "x" and chat and self.focus:
                    self.transfer_chat(chat)
                    if self.next_agent:
                        return
                elif key == "y" and chat and self.focus and self.manager:
                    from .manager import private_json
                    path = self.manager.state/"last-route.json"
                    private_json(path, self.manager.route(self.adapter.id, chat, self.projects))
                    self.message = "Ruta guardada en " + str(path)
                elif key in ("h", curses.KEY_LEFT):
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
                elif key in ("o", "\n", "\r", curses.KEY_ENTER):
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
            except (OSError, ValueError, sqlite3.Error) as error:
                self.message = str(error)
