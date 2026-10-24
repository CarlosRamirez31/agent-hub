# ◈ Agent Hub

Tus agentes, carpetas y conversaciones en una terminal. Un solo agente entra directamente; con varios aparece un selector. Código original, Python estándar y mantenimiento independiente de los dotfiles. Proyecto comunitario de Carlos Ramirez, sin afiliación con los fabricantes de agentes.

```text
 ◈ AGENT HUB         Hermes
 LOCAL · sin telemetría

 PROYECTOS                         │ PPE - From Codex · 1
   ▸ PPE (2)                       │ Preparar métricas · From Codex
   ▸ PPE - From Codex (1)          │   23 oct 20:30 · ~/proyectos/ppe
   + Agregar carpeta               │
   Recientes (3)                   │
   ★ Favoritos                     │

 j/k mover · l entrar · h volver · Enter continuar · f copia · p carpeta
 / buscar · t recientes · x pasar contexto · A agentes · y ruta JSON
```

## Instalar

Linux/macOS, Python 3.10+ con `curses` y `sqlite3`, Git y al menos un agente instalado. No hay dependencias de Python externas, Node, Rust, servidor web ni servicio remoto propio.

```sh
git clone https://github.com/CarlosRamirez31/agent-hub.git "$HOME/.local/share/agent-hub"
cd "$HOME/.local/share/agent-hub"
./install.sh
agent-hub
```

El instalador solo crea `~/.local/bin/agent-hub`, un enlace a este checkout. No descarga dependencias, no usa sudo y no reemplaza otro comando existente. Incluye `~/.local/bin` en tu `PATH` y conserva el checkout. Elimina el enlace anterior `codex-hub` únicamente si pertenece a este mismo proyecto. La biblioteca antigua de Codex se copia al formato nuevo una sola vez, conservando el archivo original y tu organización.

```sh
agent-hub --demo          # datos ficticios, sin ejecutar agentes ni guardar estado
agent-hub agents --json   # agentes detectados, ubicaciones e instalación
agent-hub --agent hermes  # entrar a un agente concreto sin selector
agent-hub --count         # recuentos, sin mostrar textos de conversaciones
```

El registro incluye lectores para Codex, Hermes, Claude Code, Gemini CLI y el formato SQLite conocido de OpenCode. **No existe un formato universal de historial.** Otros agentes se incorporan mediante un adaptador configurable y un índice JSON normalizado: [registro y formatos](docs/adapters.md). No se instala ningún agente ni se cambian sus proveedores, credenciales o herramientas.

## Colores y estilo

Pulsa **`S` dentro de la app**, tanto en el selector de agentes como en el menú principal, para abrir los **ajustes de colores con vista previa en vivo**. Usa `j/k` para elegir entre tema, títulos, detalles y texto/fondo de selección; `h/l` cambia el valor. `Enter` guarda y aplica inmediatamente; `Esc` cancela y restaura los colores anteriores. En `--demo` puedes probarlos sin guardar.

El selector de agentes, el menú principal y el selector de destino comparten la misma paleta. El tema predeterminado conserva el cian y magenta del menú original; el fondo general lo proporciona tu terminal.

```sh
agent-hub style --preset cyan    # estilo original
agent-hub style --preset violet  # violeta
agent-hub style --preset green   # verde
agent-hub style --preset blue    # azul
agent-hub style --preset mono    # sin colores, selección invertida
agent-hub style                  # consultar colores y ubicación del archivo
```

Los cambios hechos desde el CLI se aplican al volver a abrir `agent-hub`; los ajustes dentro de la app se aplican al guardar. Para personalizar los colores, guarda un tema y edita `${XDG_CONFIG_HOME:-~/.config}/agent-hub/style.json`:

```json
{
  "theme": "cyan",
  "colors": {
    "accent": "cyan",
    "secondary": "magenta",
    "selection_fg": "black",
    "selection_bg": "cyan"
  }
}
```

`accent` controla títulos, divisores y avisos; `secondary`, los detalles; `selection_fg` y `selection_bg`, el texto y fondo de la fila seleccionada. Colores disponibles: `black`, `red`, `green`, `yellow`, `blue`, `magenta`, `cyan`, `white` y `default` (color del terminal). Puedes omitir `colors` o cualquiera de sus campos para heredar del tema. En terminales sin color la selección permanece visible por inversión.

## Navegación

| Tecla | Acción |
|---|---|
| `j/k`, arriba/abajo | Navegar; en carpetas no cambia el panel derecho |
| `l`, derecha, `Enter` en carpeta | Entrar a sus conversaciones |
| `h`, izquierda | Volver a carpetas |
| `Tab` | Entrar al espacio seleccionado o volver al panel izquierdo |
| `Enter` en un chat | Continuar la misma conversación nativa |
| `f` | Fork nativo, cuando el agente lo admite |
| `x` | Pasar el contexto seleccionado a otro agente y abrir la continuación |
| `A` | Cambiar de agente |
| `T` | Panel de tareas y runs, sin cambiar la selección de conversación |
| `d` | Eliminar chat original; en una carpeta, eliminar sus archivos y conversaciones, con confirmación escrita |
| `S` | Ajustes de colores con vista previa, guardar o cancelar |
| `y` | Guardar la ruta JSON del chat en el estado local |
| `p` | Agregar una carpeta, aunque no tenga chats |
| `n` | Nueva conversación en la carpeta seleccionada |
| `/`, `Esc` | Filtrar la lista abierta y limpiar la búsqueda; sin filtro, volver a carpetas |
| `t`, `g/G` | Recientes y principio/final de una lista |
| espacio | Favorito |
| `s`, `m`, `r` | Crear sección, asignar sección y cambiar título local |
| `a`, `R` | Alternar archivados y revisar cambios del índice |
| `?`, `q` | Ayuda y salir |
| `Ctrl+C` | Salir del hub restaurando la terminal |

En el selector de carpetas, `j/k` navega, `Enter/l` entra, `h` sube, `.` muestra ocultas y `/` permite escribir la ruta. **Espacio agrega la carpeta abierta** y `Esc` cancela. No crea ni borra directorios de código.

Dentro de los menús, las combinaciones `Ctrl` sin asignar (como `Ctrl+X`) se ignoran; `Ctrl+S` y `Ctrl+Z` no pausan ni suspenden la interfaz. Tras eliminar el último chat de una vista, el foco vuelve a las carpetas para seguir navegando con `j/k`. Los comandos internos de consulta y borrado no reciben el teclado del menú.

Al abrir un chat, el hub cede la terminal al agente real. Sal del CLI con su comando de salida (por ejemplo `/quit` en Codex y Hermes) para volver al menú. No mantiene un panel lateral visible mientras estás escribiendo dentro del agente. Los bloqueos de una conversación abierta en otra app los gestiona su agente: cierra la sesión allí y reintenta; el hub no fuerza bloqueos.

## Eliminar conversaciones y carpetas

Con el foco en las conversaciones, `d` muestra el título, ID y agente. Pulsa `c` y escribe **`ELIMINAR`** para borrar la conversación y sus mensajes del agente original y del índice local. `Esc` cancela. El agente puede eliminar también subagentes dependientes según sus propias reglas. Los archivos de código se conservan al borrar un chat.

Con el foco en una carpeta de proyectos, `d` revisa todos los agentes registrados y muestra las rutas físicas y conversaciones afectadas, incluidas las archivadas, las sesiones ocultas de Hermes y las de subcarpetas. Usa `j/k` para revisar el alcance, pulsa `c` y escribe **`ELIMINAR CARPETA`**. Esto borra los historiales originales afectados, quita los proyectos correspondientes y elimina **todos los archivos de esos directorios, incluidos ocultos y `.git`**. No borra repositorios remotos ni copias situadas en otras rutas. No hay deshacer. Si el alcance cambia después de mostrarlo, pide una nueva revisión.

La eliminación nativa está implementada para **Codex** (`thread/delete` y `project/delete` mediante su app-server local) y **Hermes** (`hermes sessions delete ID --yes`, tras la confirmación del hub). Otros agentes necesitan un comando `delete` explícito en su adaptador; sin él la operación se rechaza, sin sustituirla por ocultar el chat. Los bloqueos y errores del agente se respetan. Si no se pueden revisar todos los agentes, no se ofrece el borrado completo de la carpeta. Un fallo a mitad de ejecución puede dejar conversaciones ya eliminadas: se informa del avance y los archivos se conservan mientras falle el borrado nativo. Los errores durante el borrado de archivos también pueden dejar un resultado parcial.

Por protección del propio programa, no se permite borrar `/`, directorios base del sistema como `/usr` o `/etc`, el home completo, los historiales de agentes, Agent Hub ni carpetas con otros sistemas de archivos montados. El modo demo solo elimina chats ficticios en memoria; nunca borra directorios físicos.

## Sincronización y base local

Al iniciar, el hub revisa **todos los agentes registrados**, sus fuentes locales y los cambios de carpetas/conversaciones. La base privada `${XDG_STATE_HOME:-~/.local/state}/agent-hub/index.sqlite` guarda agentes, fuentes, proyectos, conversaciones, mensajes importados y continuaciones. Los IDs están separados por agente. Los registros sin cambios no se duplican ni se reimportan; los borrados se reflejan después de una lectura completa y correcta de la fuente.

Si una fuente o contenedor deja de estar accesible, se conserva su caché y se informa del error. La ausencia temporal de una fuente no se interpreta como borrar todo. Las carpetas locales, favoritos, secciones y títulos propios viven en `libraries/ID_AGENTE.json`, separados para evitar colisiones entre agentes. Si borras un proyecto nativo pero conservas sus conversaciones, estas siguen disponibles por su carpeta o en recientes. Las carpetas que agregaste solo al hub se conservan.

El arranque normal importa el **índice**, no analiza todos los mensajes ni consume tokens para resumirlos. El texto visible de una conversación se importa a la base al transferirla. También puedes importar el historial visible de un agente explícitamente:

```sh
agent-hub sync --json
agent-hub sync --agent hermes --include-messages --json
```

La importación de mensajes de Codex usa su app-server local con lecturas paginadas, sin iniciar turnos del modelo. No se exportan razonamientos internos, prompts de sistema ni resultados de herramientas. La sincronización con la app de Codex usa su índice local, no el historial de ChatGPT web. Mientras el hub está abierto puedes pulsar `R`; al volver del agente también actualiza. No hay sondeo continuo ni sincronización de dos vías.

## Pasar contexto a otro agente

Entra al chat, pulsa `x` y elige destino (si solo hay otro disponible, entra directamente). Se exporta el texto visible del usuario y asistente, se prepara una conversación independiente y se abre el agente de destino. El proyecto lógico se llama **`PPE - From Codex`**, por ejemplo, y conserva la carpeta de trabajo original: **no copia ni renombra el repositorio de código**.

El contexto y la procedencia se guardan con permisos privados en `handoffs/`. Por defecto se conservan hasta 120.000 caracteres recientes y se indica expresamente si se omitió o truncó contenido. No se inventa un resumen mediante un modelo ni se transfiere la cuenta o el saldo de tokens; el destino usa su autenticación y presupuesto propios. El historial se presenta como contenido citado, no como instrucciones de sistema.

También se puede preparar desde el CLI:

```sh
agent-hub transfer --route-file /ruta/origen.json --to hermes --json
```

Devuelve una ruta estable de destino y no llama al modelo hasta abrirla. Añade `--launch` si quieres abrir inmediatamente. Después de la primera ejecución, enlaza la única sesión nativa nueva en esa carpeta. Si no puede determinarla sin ambigüedad, **no vuelve a crear copias**: debes enlazar el ID verificado con:

```sh
agent-hub bind --agent hermes --conversation handoff-ID --native-id ID_NATIVO
```

Ese mecanismo también preserva las rutas de conversaciones nuevas preparadas por `agent-hub new`. Un fallo al iniciar no garantiza que el agente nativo haya creado una sesión: revisa el estado y su ID antes de enlazar. Los agentes pueden variar sus flags o formatos; consulta sus lectores y configuración antes de incorporarlos.

## Contrato de apertura para otras apps

```json
{"version":1,"idCarpeta":"ID_CARPETA","idMessage":"ID_CONVERSACION","agente":"codex"}
```

`idMessage` identifica una **conversación/sesión**, no un turno individual. Los IDs son opacos; un ID preparado `handoff-...` o `new-...` sigue resolviendo a la misma sesión nativa una vez enlazado. `version` puede omitirse para la versión 1. No inventes IDs a partir de títulos o nombres de carpetas.

```sh
agent-hub projects --agent codex --json
agent-hub conversations --agent codex --json
agent-hub route --agent codex --folder ID_CARPETA --conversation ID_CONVERSACION
agent-hub open --route-file /ruta/conversacion.json --dry-run
agent-hub open --route-file /ruta/conversacion.json
```

Cada conversación listada incluye su objeto `route`. Se valida la combinación exacta agente/carpeta/conversación. Una ruta inexistente falla con código distinto de cero; nunca abre otro chat como fallback. Los subcomandos de consulta emiten JSON limpio; `open` cede la terminal al CLI real.

Para preparar una conversación nueva y obtener su ruta antes de abrirla:

```sh
agent-hub new --agent hermes --folder ID_CARPETA --json
```

Usa `--launch` para abrirla inmediatamente, o guarda su JSON y llama luego a `open`. El hub crea la sesión nativa al abrir por primera vez y enlaza el ID al salir. Si la sesión sigue abierta, no intentes abrirla de nuevo simultáneamente desde otra app.

[Esquema JSON de las rutas](docs/route.schema.json).

## Motor de tareas y ejecución local

La versión 0.5.0 añade un motor independiente de las conversaciones nativas:
contratos, DAGs, runs, perfiles, skills, policies, worktrees, checks, reviews,
aprobaciones, contexto estructurado, handoffs, budgets, métricas y ejecución
paralela acotada. La base se migra de forma aditiva y transaccional; no se borran
las conversaciones, transferencias ni bibliotecas anteriores.

```sh
agent-hub task create --title "Revisar componente" --agent codex --json
agent-hub task list --json
agent-hub task show TASK-001 --json
agent-hub task status TASK-001 ready --json
agent-hub work init                 # perfiles nativos; no inicia modelos
agent-hub work doctor               # binarios y sandbox, sin modelos
agent-hub work tui                  # panel Vim; también T en el explorador
agent-hub work demo                 # flujo ficticio completo y desechable
```

Las tareas se pueden crear y consultar sin agentes instalados. La ejecución
automática necesita Git y **bubblewrap en Linux**; si no está disponible no se
sustituye por ejecución sin sandbox. La navegación y apertura manual de CLIs
continúan disponibles en las plataformas anteriores.

`work init` preserva perfiles existentes, modelos, providers, autenticación y
policies. El registro describe capacidades; no inventa skills académicas ni
modelos baratos que no hayas configurado. El ruteo fixed no sustituye el agente.
Los controles de red incluyen las llamadas del proveedor: para modelos remotos
se requiere permiso/policy y aprobación explícita de red; no hay bypass oculto.

Los planes se pueden revisar antes de ejecutar. Faltas de repositorio, checks,
capacidad, aprobación o aislamiento quedan visibles en `waiting_human`. El
orquestador usa reglas deterministas y DAGs explícitos, no llama a un LLM para
cada decisión. El estado de trabajo permanece al cambiar de worker. Integrar
código y hacer commits requieren aprobación; el motor no hace push.

[Guía de comandos, perfiles y límites del motor](docs/task-engine.md) ·
[Arquitectura inicial](CURRENT_ARCHITECTURE.md) ·
[Plan incremental](IMPLEMENTATION_PLAN.md).

## Privacidad, mantenimiento y pruebas

- SQLite y archivos de contexto/biblioteca usan permisos 0600; los directorios de estado se crean privados.
- No se leen credenciales ni se escriben bases o sesiones nativas. Los agentes crean sus sesiones mediante sus CLIs reales.
- El hub no tiene telemetría, webviews, servidor remoto, proveedor de IA propio ni dependencias descargadas.
- Ejecutar un agente conserva sus conexiones, configuración, permisos y sandbox existentes. El hub no bloquea su red ni altera sus herramientas.
- Los comandos se ejecutan mediante arrays argv, sin shell. Los adaptadores de contenedor usan el motor local, no SSH ni un servicio externo.
- La única conexión de mantenimiento es la actualización **manual** desde este repositorio de GitHub.

```sh
agent-hub update
```

Requiere checkout limpio, rama `main` y avance directo (`--ff-only`). Las instalaciones anteriores reconocen el remoto antiguo del mismo propietario y lo migran a `agent-hub`; no aceptan repositorios de terceros. Para migrar el nombre del comando desde una versión antigua, ejecuta también `./install.sh` desde el checkout actualizado.

```sh
python3 -B -m unittest discover -s tests -v
sh -n install.sh
./bin/agent-hub --demo
```

Las pruebas automáticas son locales y no usan modelos ni servicios de IA. En esta versión se comprobaron además Codex app-server y Hermes reales, incluida una continuación de contexto ficticio hacia Hermes, su sesión nativa y su ruta de apertura.

Para desinstalar, elimina el enlace `~/.local/bin/agent-hub`; la base y las conversaciones se conservan. MIT · Carlos Ramirez.
