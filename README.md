# ◈ Codex Hub

Tus conversaciones de Codex en una interfaz de terminal con proyectos, secciones y navegación tipo Vim. Proyecto independiente de los dotfiles de Carlos Ramirez. Código original, sin código copiado de otros gestores.

```text
 ◈ CODEX HUB         tu espacio de conversaciones
 LOCAL · sin telemetría

 ESPACIOS                 │ CONVERSACIONES
   Todos los chats        │ ★ Mi configuración de Neovim
   ★ Favoritos            │   23 oct 20:30 · ~/proyectos/dotfiles
   § Personal             │
   ▸ codex-hub            │   Panel de chats y proyectos
   ▸ dotfiles             │   23 oct 19:15 · ~/proyectos/codex-hub

 h/l panel · j/k mover · Enter abrir · / buscar · n nuevo · q salir
```

## Instalar tu versión

Necesitas Linux/macOS, Python 3.10+ con `curses` y `sqlite3`, Git y el [Codex CLI oficial](https://learn.chatgpt.com/docs/cli) instalado y autenticado. No necesitas paquetes de Python, Node ni Rust para el hub.

```sh
git clone https://github.com/CarlosRamirez31/codex-hub.git "$HOME/.local/share/codex-hub"
cd "$HOME/.local/share/codex-hub"
./install.sh
codex-hub
```

El instalador crea únicamente `~/.local/bin/codex-hub`, un enlace al checkout. No sobrescribe comandos existentes, descarga dependencias ni pide sudo. Incluye `~/.local/bin` en tu `PATH`. Conserva el checkout: el enlace lo utiliza.

Para probar sin instalar ni abrir chats reales:

```sh
./bin/codex-hub --demo
```

## Uso

| Tecla | Acción |
|---|---|
| `h/l`, izquierda/derecha, `Tab` | Cambiar panel |
| `j/k`, arriba/abajo | Navegar |
| `g/G` | Ir al principio/final |
| `Enter` | Entrar al panel o continuar el chat seleccionado |
| `/`, `Esc` | Buscar por título/carpeta y limpiar búsqueda |
| `n` | Chat nuevo: confirmar o escribir carpeta; `Ctrl+U` limpia |
| espacio | Marcar/desmarcar favorito |
| `s` | Crear sección |
| `m` | Mover chat a una sección; vacío quita la asignación |
| `r` | Cambiar título local; vacío restaura el título de Codex |
| `a` | Alternar vista normal/archivados |
| `R` | Refrescar el índice |
| `?`, `q` | Ayuda y salir |

Los favoritos, títulos y secciones pertenecen al hub y no cambian la organización de la app de Codex. Las carpetas de proyecto se descubren desde los chats existentes; `n` permite usar una carpeta nueva.

Al abrir un chat, el hub cede la terminal al **Codex CLI real** usando su ID y carpeta. Al salir de Codex (`/quit`), vuelve al selector. La primera versión no mantiene el panel lateral visible mientras escribes en Codex ni gestiona varias terminales simultáneas. Evita abrir en dos sitios una conversación que ya esté en uso.

## Privacidad y conexiones

- El hub no hace conexiones de red al explorar, buscar u organizar. No hay telemetría, anuncios, rastreadores, servidor web, comprobaciones automáticas de actualización ni dependencias de terceros.
- Lee solo cinco columnas del índice SQLite local de Codex: ID, título, carpeta, fecha y estado de archivado. Abre la base en **solo lectura**. No lee credenciales, transcripciones ni resultados de herramientas.
- Guarda su organización en `${XDG_STATE_HOME:-~/.local/state}/codex-hub/library.json`, con permisos `0600` al escribir. No incluye ese estado en el repositorio.
- El modo `--demo` usa datos ficticios y memoria: no lee el índice ni escribe la biblioteca.
- **Codex sigue conectándose a OpenAI y conserva su configuración**, incluidas integraciones, MCP y plugins que tú ya hayas configurado. El hub no instala ni activa servicios adicionales y no bloquea el tráfico de Codex ni de sus herramientas. No es un sandbox de red.
- Las únicas conexiones que realiza el mantenimiento del hub son las que solicitas al clonar el repositorio o ejecutar `codex-hub update`, mediante Git hacia este repositorio de GitHub. Nunca consulta el proyecto del que surgió la idea ni otro registro de paquetes.
- Los comandos se ejecutan con argumentos separados, sin shell, y no desactivan las aprobaciones ni el sandbox de Codex.

El índice SQLite es un formato interno de Codex y puede cambiar. Se usa para admitir también chats con historial paginado sin analizar conversaciones enteras. Si una versión cambia las columnas necesarias, el hub muestra un error y conserva los datos. No hay sincronización con la nube ni importación del historial de ChatGPT web.

## Actualizar y mantener

```sh
codex-hub update
```

La actualización es **manual**. Acepta únicamente `origin=https://github.com/CarlosRamirez31/codex-hub.git`, rama `main`, checkout limpio y avance directo (`git pull --ff-only`). No instala nada después de descargar. Reinicia el hub para usar los cambios.

Para desarrollar, clona el mismo repositorio en tu carpeta de proyectos y ejecuta desde allí. Puedes instalar ese checkout con `./install.sh` si aún no existe el comando. Cada clon es independiente de los dotfiles.

```sh
python3 -B -m unittest discover -s tests -v
./bin/codex-hub --count
./bin/codex-hub --demo
```

`--count` verifica acceso al índice sin mostrar títulos ni carpetas. Si no existe todavía una base de Codex, el hub muestra una biblioteca vacía.

Para desinstalar el comando, elimina únicamente el enlace `~/.local/bin/codex-hub`. Tus chats de Codex y la organización local se conservan.

MIT · Carlos Ramirez · proyecto comunitario, sin afiliación con OpenAI.
