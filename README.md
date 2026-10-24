# ◈ Codex Hub

Tus conversaciones de Codex en una interfaz de terminal con proyectos, secciones y navegación tipo Vim. Proyecto independiente de los dotfiles de Carlos Ramirez. Código original, sin código copiado de otros gestores.

```text
 ◈ CODEX HUB         tu espacio de conversaciones
 LOCAL · sin telemetría

 PROYECTOS                         │ CONVERSACIONES
   ▾ dotfiles (2)                  │ Mi configuración de Neovim
       Mi configuración de Neovim  │   23 oct 20:30 · ~/proyectos/dotfiles
       Ajustar los atajos          │
   ▾ codex-hub (0)                 │ Ajustar los atajos
       + Nueva conversación        │   23 oct 19:15 · ~/proyectos/dotfiles
   + Agregar carpeta               │
   RECIENTES                       │
     Mi configuración de Neovim     │
     Ajustar los atajos             │
   ★ Favoritos                     │
   ▸ Otras carpetas (1)            │

 j/k mover · h/l árbol · Tab panel · Enter abrir/plegar · p carpeta · n chat
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
| `h/l`, izquierda/derecha | Plegar/expandir proyecto; `h` vuelve desde un chat al proyecto |
| `Tab` | Cambiar entre árbol y lista de conversaciones |
| `j/k`, arriba/abajo | Navegar |
| `g/G` | Ir al principio/final |
| `Enter` | Plegar/expandir proyecto, abrir chat, activar «Ver más» o «Agregar carpeta» |
| `p` | Agregar carpeta con un selector de directorios |
| `n` | Chat nuevo en el proyecto seleccionado: confirmar o escribir carpeta; `Ctrl+U` limpia |
| `t` | Saltar a recientes, ordenados por última actividad |
| `/`, `Esc` | Buscar globalmente por título/carpeta y limpiar búsqueda |
| espacio | Marcar/desmarcar favorito |
| `s` | Crear sección |
| `m` | Mover chat a una sección; vacío quita la asignación |
| `r` | Cambiar título local; vacío restaura el título de Codex |
| `a` | Alternar vista normal/archivados |
| `R` | Refrescar el índice |
| `?`, `q` | Ayuda y salir |

El panel importa **los proyectos ya registrados en Codex**, con sus nombres, orden y carpetas. Muestra debajo sus conversaciones; cinco inicialmente y luego «Ver más». Los recientes aparecen también en una lista independiente. Los proyectos se pueden plegar y expandir.

Para agregar un proyecto sin conversaciones, pulsa `p` o selecciona **+ Agregar carpeta**. En el selector, `j/k` navega, `Enter/l` entra, `h` sube, `.` muestra carpetas ocultas y `/` permite escribir una ruta (`Ctrl+U` limpia). **Espacio agrega la carpeta abierta**; `Esc` cancela. No crea ni borra directorios. El proyecto se conserva al reiniciar el hub y `n` inicia su primera conversación en esa ruta.

El hub usa la asociación de proyecto de Codex cuando está disponible; en los demás casos asigna cada chat a la raíz de proyecto más específica que contiene su carpeta, incluidas subcarpetas. Admite proyectos con varias raíces. Las carpetas con chats que no pertenecen a un proyecto registrado se encuentran bajo **Otras carpetas**; sus conversaciones también están en recientes. Las carpetas registradas varias veces por la misma ruta o un enlace simbólico no se duplican en el hub.

Los proyectos agregados desde el hub, favoritos, títulos y secciones se guardan en su propia biblioteca local. No modifican la organización de la app de Codex. `R` vuelve a importar los proyectos y chats desde disco. En proyectos con varias raíces, `n` propone la primera; puedes cambiar la ruta antes de iniciar Codex.

Al abrir un chat, el hub cede la terminal al **Codex CLI real** usando su ID y carpeta. Al salir de Codex (`/quit`), vuelve al selector. La primera versión no mantiene el panel lateral visible mientras escribes en Codex ni gestiona varias terminales simultáneas. Evita abrir en dos sitios una conversación que ya esté en uso.

## Privacidad y conexiones

- El hub no hace conexiones de red al explorar, buscar u organizar. No hay telemetría, anuncios, rastreadores, servidor web, comprobaciones automáticas de actualización ni dependencias de terceros.
- Lee solo metadatos del índice SQLite local de Codex: ID, título, carpeta, fecha, estado de archivado y asociación de proyecto; además de nombres, orden y rutas de los proyectos. Abre la base en **solo lectura**. No lee credenciales, transcripciones ni resultados de herramientas.
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

`--count` muestra la cantidad de conversaciones y proyectos importados sin revelar títulos ni carpetas. Si no existe todavía una base de Codex, el hub muestra la biblioteca local y permite agregar carpetas vacías.

Para desinstalar el comando, elimina únicamente el enlace `~/.local/bin/codex-hub`. Tus chats de Codex y la organización local se conservan.

MIT · Carlos Ramirez · proyecto comunitario, sin afiliación con OpenAI.
