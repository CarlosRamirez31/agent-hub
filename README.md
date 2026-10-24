# ◈ Codex Hub

Tus conversaciones de Codex en una interfaz de terminal con proyectos, secciones y navegación tipo Vim. Proyecto independiente de los dotfiles de Carlos Ramirez. Código original, sin código copiado de otros gestores.

```text
 ◈ CODEX HUB         tu espacio de conversaciones
 LOCAL · sin telemetría

 PROYECTOS                         │ dotfiles · 2
   ▸ dotfiles (2)                  │ Mi configuración de Neovim
   ▸ codex-hub (0)                 │   23 oct 20:30 · ~/proyectos/dotfiles
   + Agregar carpeta               │
   Recientes (2)                   │ Ajustar los atajos
   ★ Favoritos                     │   23 oct 19:15 · ~/proyectos/dotfiles
   ▸ Otras carpetas (1)            │

 j/k mover · l entrar · h volver · Enter continuar · f copia · p carpeta
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
| `l`, derecha | Entrar a la carpeta seleccionada y enfocar sus conversaciones |
| `h`, izquierda | Volver a la lista de carpetas |
| `Tab` | Entrar a la carpeta seleccionada o volver al panel izquierdo |
| `j/k`, arriba/abajo | Navegar; en carpetas no cambia la lista derecha |
| `g/G` | Ir al principio/final |
| `Enter` | Entrar a una carpeta o continuar la conversación seleccionada |
| `f` | Continuar en una copia independiente del chat seleccionado |
| `p` | Agregar carpeta con un selector de directorios |
| `n` | Chat nuevo en el proyecto seleccionado: confirmar o escribir carpeta; `Ctrl+U` limpia |
| `t` | Saltar a recientes, ordenados por última actividad |
| `/`, `Esc` | Buscar en la lista abierta y limpiar búsqueda; sin búsqueda, `Esc` vuelve a carpetas |
| espacio | Marcar/desmarcar favorito |
| `s` | Crear sección |
| `m` | Mover chat a una sección; vacío quita la asignación |
| `r` | Cambiar título local; vacío restaura el título de Codex |
| `a` | Alternar vista normal/archivados |
| `R` | Revisar cambios del índice local mientras el hub está abierto; al iniciar es automático |
| `?`, `q` | Ayuda y salir |

El panel izquierdo muestra **los proyectos ya registrados en Codex**, sus nombres y la cantidad de conversaciones de cada uno. No duplica los chats debajo de las carpetas. Moverte con `j/k` solo cambia la selección izquierda: el contenido y la selección de la derecha permanecen iguales.

Sitúate en una carpeta, pulsa **`l`** y busca la conversación a la derecha con `j/k` o `/`. **`Enter` continúa la misma conversación** y `h` vuelve a las carpetas. `t` abre los recientes; `/` filtra la lista que tienes abierta, por lo que dentro de un proyecto busca solo sus conversaciones. Los contadores de las carpetas muestran el total, incluso mientras filtras.

Para agregar un proyecto sin conversaciones, pulsa `p` o selecciona **+ Agregar carpeta**. En el selector, `j/k` navega, `Enter/l` entra, `h` sube, `.` muestra carpetas ocultas y `/` permite escribir una ruta (`Ctrl+U` limpia). **Espacio agrega la carpeta abierta**; `Esc` cancela. No crea ni borra directorios. El proyecto se conserva al reiniciar el hub y `n` inicia su primera conversación en esa ruta.

El hub usa la asociación de proyecto de Codex cuando está disponible; en los demás casos asigna cada chat a la raíz de proyecto más específica que contiene su carpeta, incluidas subcarpetas. Admite proyectos con varias raíces. Las carpetas con chats que no pertenecen a un proyecto registrado se encuentran bajo **Otras carpetas**; sus conversaciones también están en recientes. Las carpetas registradas varias veces por la misma ruta o un enlace simbólico no se duplican en el hub.

Los proyectos agregados desde el hub, favoritos, títulos y secciones se guardan en su propia biblioteca local. No modifican la organización de la app de Codex. En proyectos con varias raíces, `n` propone la primera; puedes cambiar la ruta antes de iniciar Codex.

## Actualización de carpetas y conversaciones

**Al abrir el hub la lectura del índice local de Codex es automática, desde la primera apertura; no tienes que pulsar `R`.** Las carpetas existentes se reutilizan por ID y ruta. No se crean directorios, no se duplican proyectos y no se reescribe la biblioteca si no cambias su organización. El índice se lee para detectar proyectos nuevos, cambios y eliminaciones.

Las conversaciones o proyectos eliminados desde la app de Codex dejan de aparecer como elementos importados en la siguiente apertura, cuando Codex haya actualizado su índice. Si eliminas un proyecto pero conservas sus conversaciones, estas siguen en recientes y su ruta puede aparecer bajo «Otras carpetas». Las carpetas que agregaste solo en el hub se conservan en su biblioteca independiente.

Mientras el hub permanece abierto, `R` permite revisar cambios sin reiniciarlo. También revisa el índice al volver de una conversación de Codex. No hay sondeo continuo, sincronización de dos vías ni conexión con el historial de ChatGPT web.

Al abrir un chat, el hub cede la terminal al **Codex CLI real** usando su ID y carpeta. Al salir de Codex (`/quit`), vuelve al selector. El hub no mantiene el panel lateral visible mientras escribes en Codex ni gestiona varias terminales simultáneas.

Si Codex muestra **«This conversation is open in another app»**, cierra esa conversación en la otra app y pulsa `r` en esa pantalla para reintentar. Ese aviso es un bloqueo de la conversación, distinto de la revisión de proyectos con `R` en el hub. Si prefieres dejar abierta la original, usa `f` para continuar en una copia; puedes hacerlo desde esa pantalla o desde la lista de chats del hub. El hub no fuerza ni elimina bloqueos.

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
