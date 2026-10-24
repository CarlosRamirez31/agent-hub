# Arquitectura actual (antes del motor de tareas)

## Estructura y puntos de entrada

El proyecto es Python 3.10+ y biblioteca estándar. `bin/agent-hub` resuelve su
checkout y llama a `agent_hub.cli.main`; `bin/codex-hub` mantiene el alias de
compatibilidad. `install.sh` crea únicamente un enlace local. No hay servidor,
framework, proveedor LLM propio ni descarga de dependencias.

`cli.py` usa argparse y despacha consultas JSON, operaciones de rutas y curses.
`Manager` coordina registro, sincronización, biblioteca y transferencias. Las
consultas actuales sincronizan índices nativos; no inician turnos del modelo.
Los comandos de mantenimiento/estilo se despachan antes de esa sincronización.

## Persistencia

`Cache` gestiona `${XDG_STATE_HOME:-~/.local/state}/agent-hub/index.sqlite`, con
`user_version=1`, claves foráneas y archivos privados. Tablas actuales:

| Tabla | Identidad / función |
|---|---|
| agents | id; disponibilidad, último sync y error |
| agent_sources | agent; lector, home y contenedor |
| projects | (agent,id); nombre, raíces JSON y procedencia |
| conversations | (agent,id); título, cwd, fecha, archivo y proyecto |
| messages | (agent,conversation,ordinal); solo texto user/assistant |
| transfers | id; origen/destino, carpeta, contexto, native_id y estado |

Los snapshots completos exitosos reconcilian proyectos/conversaciones; fallos
conservan la caché anterior. Las bibliotecas JSON por agente guardan favoritos,
secciones, títulos y carpetas locales. `Library.save` usa reemplazo atómico.
La biblioteca antigua de Codex se copia una vez sin borrar el original.

## Adaptadores, sesiones y rutas

`agents.py` ya tiene un registro configurable y el modelo `Agent`: Codex,
Hermes, Claude, Gemini, OpenCode y exportaciones normalizadas. Los comandos son
arrays argv. Los contenedores usan Podman y traducción explícita de rutas.
`native.py` y `store.py` leen índices locales conocidos en modo solo lectura;
Codex exporta mensajes paginados mediante `rpc.py`. No se leen credenciales ni
razonamiento o resultados de herramientas para transferencias.

El descriptor v1 contiene agente/idCarpeta/idMessage. Manager valida la
combinación completa. `open` continúa exactamente esa sesión con el CLI nativo,
respetando bloqueos y permisos. `new` prepara un alias estable `new-…` antes de
crear una sesión nativa. No hay actualmente tarea, run, scheduler o runner de
trabajo autónomo.

## Transferencia y flujos manuales

`prepare_transfer` obtiene solo historial visible, limita caracteres, guarda
contexto JSON/Markdown privado y crea `handoff-…`. `open` inicia el destino y
busca la única sesión nueva compatible; una asociación ambigua exige `bind`
con ID verificado, sin repetir la creación. La TUI mantiene la transferencia
manual, apertura de CLI y exportación de ruta. El historial citado nunca se
presenta como instrucciones de sistema ni como un resumen inventado.

## TUI y comandos

`ui.py`, `navigation.py`, `style.py` y `terminal.py` separan navegación, render,
colores y teclado. Dos paneles: selección de carpeta y conversaciones. j/k
mueve; l/Enter entra; h vuelve; f fork; x transferencia; A agente; y ruta;
S colores; R sincroniza. Al abrir el CLI, curses libera la terminal y la
restaura al regresar. `deletion.py` protege borrado nativo y eliminación de
carpetas mediante confirmación escrita y revisión de alcance entre agentes.

Comandos existentes: agents, projects, conversations, route, open, new,
transfer, bind, sync, bridge, style, update y modo demo. No deben cambiar sus
contratos JSON ni sus atajos por agregar el motor.

## Extensiones y deuda relevante

- Reutilizar Cache/SQLite y agregar migraciones transaccionales: la inicialización
  actual fija user_version=1 y necesita evolucionar sin borrar tablas existentes.
- Separar tareas persistentes de conversaciones/índices reconciliables: eliminar
  una sesión de origen no debe eliminar el estado de trabajo.
- Mantener `Agent` para sesiones; agregar perfiles/capacidades de ejecución sin
  afirmar soporte headless, sandbox o review que un CLI no haya declarado.
- Despachar operaciones de tareas sin descubrir/sincronizar agentes: crear/listar
  trabajo local no debe requerir un CLI instalado ni un contenedor accesible.
- La asignación actual de proyectos está acotada por agente. Una referencia de
  tarea necesita conservar ese namespace, sin convertir un ID opaco en ruta.
- No hay aislamiento de workers, gates, budgets o contabilidad aún. Deben existir
  antes de habilitar ejecución paralela; un prompt no es un sandbox.
- Coucou es un cliente externo. Agent Hub debe publicar CLI/JSON; no copiar su
  interfaz ni su implementación dentro de este repositorio.
