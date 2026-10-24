# Prompt para integrar «Abrir en terminal» en Coucou

Trabaja únicamente en Coucou y en su integración de apertura. Agent Hub ya está implementado en el repositorio https://github.com/CarlosRamirez31/agent-hub. No modifiques Agent Hub para reemplazar su contrato, ni cambies otras funcionalidades de Coucou. Primero identifica el repositorio y sus instrucciones, y conserva los cambios existentes del usuario.

Contrato completo y normativo para esta integración: https://github.com/CarlosRamirez31/agent-hub/blob/main/docs/coucou-contract.md ; esquema JSON: https://github.com/CarlosRamirez31/agent-hub/blob/main/docs/route.schema.json . Léelos y comprueba el binario instalado antes de implementar.

Necesito adaptar la opción existente «Abrir terminal» (o agregarla si no existe) en una carpeta/tarea/conversación de Coucou. Debe tomar la tarea o ejecución que el usuario está viendo/seleccionando en ese instante, y su agente y sesión reales. Conserva la apertura normal de terminal para carpetas sin asociación si ya existe, como opción explícita separada; no la presentes como si continuara una conversación. Debe abrir la conversación exacta, en el agente que la ejecutó, mediante el comando instalado `agent-hub`. No debe abrir siempre Codex, elegir la conversación más reciente, buscar por título ni crear otra conversación como fallback.

El descriptor estable que Coucou debe guardar en los metadatos de la tarea es:

```json
{"version":1,"idCarpeta":"ID_REAL_CARPETA","idMessage":"ID_REAL_CONVERSACION","agente":"codex"}
```

`agente` es el ID del adaptador (`codex`, `hermes`, `claude`, `gemini`, `opencode` o uno registrado por el usuario). `idCarpeta` e `idMessage` son IDs opacos: no los inventes ni los deduzcas del nombre. Pese a su nombre, **`idMessage` identifica la conversación/sesión, no un mensaje individual**. Puede ser un ID nativo o un identificador estable preparado por el hub, como `handoff-...` o `new-...`. Coucou debe conservarlo sin transformarlo; Agent Hub resuelve el ID nativo internamente.

Consulta primero los comandos públicos del binario instalado:

```sh
agent-hub --help
agent-hub agents --json
agent-hub projects --agent codex --json
agent-hub conversations --agent codex --json
```

Cada conversación listada incluye su objeto `route` completo. Ese es el descriptor que debe persistir Coucou. Para obtenerlo a partir de IDs ya conocidos:

```sh
agent-hub route --agent codex --folder ID_REAL_CARPETA --conversation ID_REAL_CONVERSACION
```

Captura y persiste el ID nativo exacto desde los eventos/API documentados del runner que ejecuta cada tarea; no infieras la sesión a partir del cwd. Si la carpeta tiene varias tareas, respeta la seleccionada o pide elegir explícitamente. Si una ejecución sigue activa y bloquea el acceso, explica el bloqueo y usa el flujo existente de detener/liberar antes de reintentar; no fuerces locks ni mates procesos automáticamente. Evita aperturas duplicadas por doble clic.

Si Coucou necesita iniciar una conversación nueva asociada a una tarea:

```sh
agent-hub new --agent hermes --folder ID_REAL_CARPETA --json
```

Ese comando prepara una conversación en la base local y devuelve inmediatamente el descriptor, sin hacer una petición al modelo. Guarda el descriptor antes de abrir la terminal. Al abrirlo por primera vez, el hub crea la sesión nativa y enlaza su ID; las siguientes aperturas resuelven esa misma sesión. Para conversaciones que Coucou ya ejecuta por otra vía, identifica de forma verificable el ID nativo y obtén su `route`; no dupliques la ejecución con `new`.

Para abrir, escribe el JSON de la ruta en un archivo privado estable dentro del estado de Coucou (permisos 0600 y directorio 0700). Valida la ruta sin iniciar el agente:

```sh
agent-hub open --route-file /ruta/absoluta/ruta-de-la-tarea.json --dry-run
```

Después abre el emulador de terminal que Coucou ya use/configure y pasa como argumentos separados:

```text
["agent-hub", "open", "--route-file", "/ruta/absoluta/ruta-de-la-tarea.json"]
```

Inspecciona la API del lanzador de terminal real antes de implementar sus flags. No asumas que todos aceptan `-e`. Evita `sh -c`, interpolación de shell, `eval`, concatenar comandos o incluir el JSON en una cadena ejecutable. Conserva el archivo al menos mientras la terminal pueda necesitarlo; no uses un archivo temporal que se borre antes de que el proceso hijo lo abra.

Si la carpeta de Coucou no tiene una conversación asociada, ofrece seleccionar una ruta real o preparar una nueva explícitamente. Si falla una validación, el agente no está disponible, la conversación se eliminó o hay más de una posible asociación, muestra un error útil. Nunca redirijas silenciosamente a otra conversación ni intentes forzar un bloqueo de sesión abierta en otra app.

La apertura directa ejecuta el CLI nativo y termina al salir de él; no necesita mostrar el menú de Agent Hub. Si una conversación o carpeta fue eliminada con `d` en el hub, muestra la ruta obsoleta y no la recrees automáticamente.

Agent Hub indexa sus fuentes al iniciar, usa su propia base SQLite y puede tener caché de fuentes temporalmente inaccesibles. No leas sus tablas privadas ni los archivos nativos de agentes desde Coucou: usa el contrato CLI/JSON. Tampoco añadas otro servidor, servicio remoto o mecanismo de autenticación. No hace falta registrar un esquema de URL para esta integración.

Prueba al menos: ruta Codex válida, ruta Hermes válida, conversación nueva preparada, apertura posterior de una continuación `handoff-...`, IDs equivocados, agente ausente, conversación borrada, nombres/rutas con espacios y metacaracteres, y cancelación del usuario. Confirma que un fallo nunca abre un chat distinto y que las opciones actuales de Coucou siguen funcionando. Los tests deben usar fixtures/stubs y no gastar tokens de agentes reales salvo autorización del usuario.

Documenta los metadatos y la migración compatible de tareas antiguas sin route, añade pruebas de argv sin shell y comprueba con stubs que se conserva la conversación entre aperturas. No gastes tokens de modelos reales.

Al terminar, describe qué cambió en Coucou, cómo se guarda la ruta, qué comando exacto ejecuta el lanzador y cómo lo verificaste.
