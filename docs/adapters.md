# Registro de agentes y lectores

Agent Hub detecta comandos e historiales locales conocidos. No hay un formato de sesiones universal: un agente desconocido necesita un adaptador o un exportador a nuestro formato normalizado. No se ejecutan plugins descargados, descubrimientos por red ni scripts remotos.

Configura `${XDG_CONFIG_HOME:-~/.config}/agent-hub/agents.json`:

```json
{
  "version": 1,
  "agents": [
    {
      "id": "mi-agente",
      "name": "Mi agente",
      "kind": "normalized",
      "home": "/ruta/absoluta/exportaciones/mi-agente",
      "command": ["mi-agente"],
      "new": [],
      "resume": ["--resume", "{session}"],
      "prompt": ["--prompt", "{prompt}"]
    }
  ]
}
```

Todos los comandos son arrays argv, nunca strings de shell. Adapta los flags a la documentación y versión real del agente. Los placeholders permitidos son `{cwd}`, `{session}`, `{prompt_file}` y `{prompt}`. Este último es una instrucción breve para leer el archivo de contexto, no todo el historial pasado por argv. Si el agente admite un archivo de prompt inicial, usa `"prompt": ["--query-file", "{prompt_file}"]`. Un agente sin `resume` no puede abrir conversaciones existentes: el hub falla, sin iniciar otra.

Para modificar un adaptador conocido basta incluir su ID y los campos a reemplazar. `{"id":"gemini","enabled":false}` lo excluye. Los IDs deben ser únicos y coincidir con `[a-z][a-z0-9_-]{0,63}`. El binario necesita estar instalado para ejecutar sesiones; se puede indexar un historial local existente aunque el binario ya no esté instalado.

## Fuentes conocidas

| ID | Fuente local | Continuación |
|---|---|---|
| `codex` | `$CODEX_HOME` o `~/.codex/state_*.sqlite` | `codex -C DIR resume ID`; mensajes seleccionados mediante app-server local de solo lectura |
| `hermes` | `$HERMES_HOME` o `~/.hermes/state.db` | `hermes chat --in DIR --resume ID`; contexto con `--query-file` |
| `claude` | `$CLAUDE_CONFIG_DIR` o `~/.claude/history.jsonl`, `projects/*/sessions-index.json`, JSONL de sesiones | `claude --resume ID` |
| `gemini` | `~/.gemini/tmp/*/chats/session-*.json`, `.project_root` o `projects.json` para resolver la carpeta | `gemini --resume ID` |
| `opencode` | `~/.local/share/opencode/opencode.db`, tablas `session/message/part` | `opencode --session ID` |

Los formatos internos pueden variar entre versiones. Si el lector no entiende un esquema, conserva el índice anterior y muestra error. Gemini omite sesiones cuya carpeta no se pueda determinar; no inventa una ruta. OpenCode con otro formato puede registrarse mediante `kind: normalized`. Los agentes distintos de Codex no necesariamente tienen un concepto nativo de proyecto: el hub agrupa sus sesiones por carpeta.

Lectura/flags consultados en las fuentes primarias: [Codex app-server](https://learn.chatgpt.com/docs/app-server), [Hermes CLI](https://hermes-agent.nousresearch.com/docs/user-guide/cli), [Claude CLI](https://code.claude.com/docs/en/cli-reference), [Gemini sesiones](https://geminicli.com/docs/cli/session-management/). Las pruebas locales de esta versión verifican Codex y la instalación real de Hermes del usuario. Los demás lectores tienen compatibilidad de formato, no una garantía sobre toda versión futura.

## Formato normalizado

El adaptador lee únicamente `HOME_DEL_ADAPTADOR/index.json`. Un exportador del agente puede actualizarlo atómicamente por su cuenta. Agent Hub lo relee al abrir o sincronizar; no ejecuta automáticamente el exportador.

```json
{
  "version": 1,
  "projects": [{"id":"ppe","name":"PPE","roots":["/proyectos/ppe"]}],
  "conversations": [{
    "id":"session-123",
    "title":"Preparar métricas",
    "cwd":"/proyectos/ppe",
    "updated":1800000000,
    "archived":false,
    "project_id":"ppe",
    "messages":[
      {"role":"user","text":"Necesito revisar las métricas"},
      {"role":"assistant","text":"Queda pendiente revisar el panel"}
    ]
  }]
}
```

`updated` admite Unix en segundos/milisegundos o fecha ISO. Los IDs de conversación deben coincidir con `[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}`; son IDs, no opciones ni rutas de archivos. Solo se importan mensajes `user` y `assistant`; no entregues credenciales, razonamientos internos, prompts de sistema ni resultados de herramientas.

## Hermes en un contenedor local

Ejemplo para un contenedor ya preparado y con el home del host montado:

```json
{
  "version":1,
  "agents":[{
    "id":"hermes",
    "container":"dev-podman",
    "home":"/opt/hermes/.hermes",
    "host_root":"/home/usuario",
    "runtime_root":"/host-home"
  }]
}
```

El comando `hermes` del host debe ser el lanzador existente hacia ese contenedor. El lector usa `podman exec` y el propio módulo `bridge` de este checkout, accesible por el montaje indicado; necesita Python 3 dentro del contenedor. Traduce las carpetas y los archivos de contexto entre ambos espacios. No arranca contenedores ni cambia la instalación del agente al explorar. Si está detenido, conserva la caché y muestra un error. No uses este ejemplo si tu montaje o lanzador tienen otra estructura.

## Eliminación nativa confirmada

Codex usa `thread/delete` / `project/delete` del app-server instalado; Hermes usa `sessions delete ID --yes` con `HERMES_HOME` del adaptador. El hub solo los llama después de su confirmación escrita y verifica que el índice nativo ya no devuelva el ID. Un error no se transforma en una eliminación local silenciosa.

Para otro agente puedes configurar, solo si su CLI lo admite realmente:

```json
{"id":"mi-agente","delete":["sessions","delete","{session}","--yes"]}
```

`delete` se añade a `command` como argv, sin shell, y requiere el placeholder `{session}`; también admite `{cwd}`. Debe eliminar únicamente esa sesión y sus dependencias nativas, terminar sin pedir interacción adicional y devolver un código distinto de cero si falla. El índice/exportador del adaptador debe reflejar el borrado antes de terminar. No configures comandos globales de purga. Un adaptador sin eliminación no puede participar en el borrado completo de una carpeta que contenga sus conversaciones. En contenedores, los adaptadores nativos Codex/Hermes ejecutan la eliminación dentro del contenedor mediante el bridge local. Un `delete` personalizado se ejecuta con el `command` del host, igual que el lanzador existente.
