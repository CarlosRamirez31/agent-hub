"""Folder selectors and counters, independent of the active chat list."""

from dataclasses import dataclass
from .store import visible


@dataclass(frozen=True)
class Row:
    kind: str
    label: str
    value: str = ""


def sidebar(chats, projects, library, archives=False, others=False):
    rows = []

    def project_rows(project):
        children = visible(chats, library, ("project", project.id), archives=archives, projects=projects)
        rows.append(Row("project", "▸ " + project.name + f" ({len(children)})", project.id))

    for project in projects:
        if project.source != "discovered":
            project_rows(project)
    rows.append(Row("add", "+ Agregar carpeta"))
    recent = visible(chats, library, ("recent", ""), archives=archives, projects=projects)
    rows.append(Row("recent", f"Recientes ({len(recent)})"))
    rows.append(Row("pinned", "★ Favoritos"))
    rows += [Row("section", "§ " + name, name) for name in library.data["sections"]]
    discovered = [p for p in projects if p.source == "discovered"]
    if discovered:
        rows.append(Row("others", ("▾ " if others else "▸ ") + f"Otras carpetas ({len(discovered)})"))
        if others:
            for project in discovered:
                project_rows(project)
    return rows
