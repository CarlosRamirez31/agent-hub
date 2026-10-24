"""Project trees and recents, independent of terminal drawing."""

from dataclasses import dataclass
from .store import visible


@dataclass(frozen=True)
class Row:
    kind: str
    label: str
    value: str = ""
    parent: str = ""


def sidebar(chats, projects, library, expanded, limits, query="", archives=False, others=False):
    rows = []

    def project_rows(project):
        children = visible(chats, library, ("project", project.id), query, archives, projects)
        opened = project.id in expanded
        rows.append(Row("project", ("▾ " if opened else "▸ ") + project.name + f" ({len(children)})", project.id))
        if opened:
            limit = limits.get(project.id, 5)
            for chat in children[:limit]:
                title = library.meta(chat).get("title") or chat.title
                rows.append(Row("chat", "    " + title, chat.id, project.id))
            if len(children) > limit:
                rows.append(Row("more", f"    Ver más ({len(children)-limit})", project.id))
            elif not children:
                rows.append(Row("empty", "    + Nueva conversación", project.id))

    for project in projects:
        if project.source != "discovered":
            project_rows(project)
    rows.append(Row("add", "+ Agregar carpeta"))
    rows.append(Row("recent", "RECIENTES"))
    recent = visible(chats, library, ("recent", ""), query, archives, projects)
    limit = limits.get("recent", 10)
    for chat in recent[:limit]:
        title = library.meta(chat).get("title") or chat.title
        rows.append(Row("chat", "  " + title, chat.id))
    if len(recent) > limit:
        rows.append(Row("more", f"  Ver más ({len(recent)-limit})", "recent"))
    rows.append(Row("pinned", "★ Favoritos"))
    rows += [Row("section", "§ " + name, name) for name in library.data["sections"]]
    discovered = [p for p in projects if p.source == "discovered"]
    if discovered:
        rows.append(Row("others", ("▾ " if others else "▸ ") + f"Otras carpetas ({len(discovered)})"))
        if others:
            for project in discovered:
                project_rows(project)
    return rows
