# Motor local de trabajo — 0.5.0

El motor extiende el explorador existente. Una conversación nativa no es una
tarea: las tareas y runs tienen estado propio aunque su sesión desaparezca,
cambie de perfil o falle un proveedor. `task` y `work` emiten JSON con `--json`;
las operaciones `work` emiten JSON también por defecto. No se añade un proveedor,
servidor ni dependencia de Python. La ejecución aislada usa Git y bubblewrap.

## Inicio y prueba sin modelos

```sh
agent-hub work init
agent-hub work doctor
agent-hub work demo
agent-hub work tui
```

`init` registra perfiles worker/reviewer para adaptadores nativos detectados de
Codex, Hermes y Gemini; preserva perfiles existentes, providers, modelos, keys y
policies. No instala agentes ni inicia turnos. Otros adaptadores conservan el
flujo manual existente y pueden registrar un perfil de ejecución explícito.
`doctor` prueba `--help` y un `true` aislado, sin llamar modelos. Si el PATH de un
contenedor apunta a otra instalación de Hermes, configura en el perfil la ruta
absoluta de su lanzador existente (por ejemplo `/usr/local/bin/hermes`).

`demo` crea un repositorio, SQLite y perfiles ficticios desechables; ejecuta un
worker Python aislado, un check determinista y un reviewer Python de solo lectura.
Comprueba el flujo real sin usar modelos ni alterar el estado del usuario. Todo
se elimina al salir. No debe confundirse con una evaluación de calidad de un LLM.

En el explorador, **T** abre el panel de trabajo sin alterar la conversación
seleccionada. `j/k` navega, `h/l` cambia sección, Enter muestra detalles; `n` crea
una tarea, `o` prepara un plan y `a` fija un perfil. `v`, `r`, `e`, `c` y `x`
permiten verificar, revisar, ejecutar, construir contexto y hacer handoff.
Ejecutar requiere una acción/confirmación explícita. q/Esc vuelve al explorador.
Las teclas antiguas, la apertura nativa y raw handoff siguen funcionando.

## Tareas y contratos

```sh
agent-hub task create --title 'Cambiar color del botón' --agent codex --json
agent-hub task create --contract task.json --depends-on TASK-001 --json
agent-hub task list --status pending --json
agent-hub task show TASK-001 --json
agent-hub task status TASK-001 ready --expected-revision 1 --reason 'Revisado' --json
agent-hub task depend TASK-002 TASK-001 --json
agent-hub task depend TASK-002 TASK-001 --remove --json
agent-hub task events TASK-001 --json
agent-hub task update TASK-001 --contract revised-task.json --reason 'Cambio humano de alcance' --json
```

Sin campos, `task create` pide un título en una terminal; sin terminal falla sin
quedar esperando stdin. `--contract -` lee JSON UTF-8 de stdin, con límite de 1 MiB.
Se rechazan campos desconocidos, IDs no canónicos y tipos erróneos. Se asignan
IDs `TASK-001`, monotónicos y únicos con escritores concurrentes. No se deducen
IDs nativos ni proyectos de un título o carpeta. Las tareas generales no requieren
un proyecto ni un CLI instalado.

Ejemplo completo de contrato (los valores son configuración, no código):

```json
{
  "version": 1,
  "title": "Ajustar el botón Save",
  "objective": "Usar el token success sin cambiar su comportamiento",
  "scope": {"files": ["src/SaveButton.tsx"]},
  "constraints": ["No añadir dependencias"],
  "acceptance": ["El componente compila", "Los tests pasan"],
  "complexity": "small",
  "assignment": {"mode": "fixed", "agent": "codex"},
  "permissions": {
    "filesystem": "write", "network": false, "dependencies": false,
    "git_commit": false, "git_push": false, "shell": false
  },
  "review": {"required": false},
  "budget": {
    "max_turns": 12, "max_retries": 2, "max_agents": 3,
    "max_handoff_depth": 3, "max_chars": 40000, "timeout_seconds": 300
  }
}
```

Opcionales: `project: {"agent":"codex","id":"ID_OPACO"}`, `domain`,
`capabilities`, `specializations`, `skills` y `policy` (nombre de una policy; por defecto default). El núcleo no los limita a un
proveedor. Para selección automática usa `assignment: {"mode":"orchestrated"}`.
Un perfil fixed no se sustituye por indisponibilidad o cuota; un humano puede
reemplazar el contrato o autorizar un handoff con override explícito.

La asignación de un perfil no concede permisos. El ejemplo anterior **no da red
ni shell** a Codex; una ejecución que necesite esas capacidades se rechaza hasta
que contrato, policy y aprobaciones lo permitan. La red incluye llamadas al
proveedor, no solo herramientas: no hay una excepción implícita para modelos
remotos. El chat/conversaciones manuales anteriores conservan su comportamiento.

Estados: pending, ready, blocked, running, verifying, reviewing,
changes_requested, waiting_human, failed, done, cancelled. Los cambios se auditan;
las transiciones imposibles y las revisiones obsoletas fallan. Solo se ejecuta
ready sin dependencias pendientes. No hay dependencias consigo misma ni ciclos;
un fallo al crear un DAG revierte toda la operación.

## Perfiles, especialización y modelos

```sh
agent-hub work profile list
agent-hub work profile show codex
agent-hub work profile register --file hermes-academic.json
agent-hub work profile disable old-worker
agent-hub work classify TASK-001
agent-hub work route TASK-001
```

Un perfil declara id, provider, roles, command (argv), resume_command opcional,
format, model opcional, capabilities, specializations, skills, tools,
priority_domains, context_max_chars, cost_class, enabled y límites `permissions` por perfil. Estos límites son un techo, no una concesión: contrato y policy siguen siendo obligatorios. Un perfil especializado
como `hermes-academic` requiere declarar sus capacidades y registrar sus skills
reales; no se supone que un Hermes genérico tenga APA, RAG o reglas universitarias.

La selección usa compatibilidad de capacidades, dominio, especializaciones,
skills, capacidad de contexto, clase de costo declarada y éxito histórico con
suficientes muestras. Los resultados incluyen puntuación y explicación. La regla
fixed tiene precedencia. Un indicio sensible (auth, contraseñas, seguridad,
producción, cambio destructivo) no se degrada por ser un diff corto. La clasificación
es heurística y el plan se puede revisar; no se vende como comprensión infalible.

Los perfiles baratos o locales solo participan si están configurados y disponibles.
No se inventan precios ni se cambia el modelo del CLI silenciosamente. Si declaras
`model` en Codex/Hermes/Gemini se pasa `--model` a ese CLI; un proveedor genérico debe
usar `{model}` en su command. Con model null se conserva la configuración nativa.

Formatos de salida: `json` (resultado normalizado), `text`, `codex-jsonl`,
`hermes-jsonl`, `gemini-jsonl`. Los parsers nativos conservan el ID exacto emitido
por el CLI y solo exportan respuesta visible/métricas conocidas; no guardan la
traza cruda de herramientas o razonamiento. Un resultado genérico JSON acepta
text, native_id, tokens/cost reportados, verdict/issues, files_changed, summary,
tests y artifacts (files_changed/artifacts son listas de rutas relativas). Los campos desconocidos y métricas no válidas fallan.

La disponibilidad normal indica binario/Podman y perfil habilitado. No garantiza
cuota, credenciales vigentes o conectividad del proveedor. `doctor` añade pruebas
explícitas de instalación y sandbox. No hay health checks de red automáticos.

## Workspaces, ejecución y aislamiento

```sh
agent-hub work workspace create TASK-001 --repo /ruta/repo --ref HEAD
agent-hub work workspace show TASK-001
agent-hub work workspace fingerprint TASK-001
agent-hub work execute TASK-001
agent-hub work cancel TASK-001
```

Cada tarea tiene una rama `agent-hub/task-001` y un worktree propio dentro del
estado del Hub. Nunca se ejecuta reset/clean ni se copian cambios sin commit del
checkout del usuario. Si quieres incluirlos, prepara explícitamente la revisión
Git adecuada antes de crear el workspace. La asociación tarea/workspace es única.

El runner bubblewrap mantiene el sistema y el directorio común de Git de solo
lectura, concede escritura solo al worktree según contrato y usa scratch privado.
Sin permiso de red crea un namespace sin red. PID/IPC/UTS también están aislados para no compartir procesos de otros agentes. Oculta `/run`, el `/tmp` del host y
el IPC de Codex para no usar accidentalmente procesos de control externos.
Un reviewer recibe el código de solo lectura. No usa flags yolo ni bypass de hooks,
aprobaciones o sandbox del CLI nativo.

Los CLIs pueden necesitar escribir su propio estado de sesiones. Las excepciones
se declaran explícitamente en `runtime_write_paths`, por perfil. No pueden incluir
el workspace, sus antecesores o el directorio común de Git. Son concesiones reales
a esas rutas y deben ser acotadas: el Hub no afirma que el estado nativo sea
inmutable si lo autorizaste como writable. No se extraen ni se copian credenciales.
Los servicios opcionales/configuración de cada CLI siguen bajo su control nativo.

En perfiles de contenedor, `container` tiene name, host_root y runtime_root. El
Hub ejecuta el **runner dentro del contenedor**, que aplica su bubblewrap a la
ruta montada; no supone que aislar el cliente Podman aísle el proceso remoto.
En contenedores sin permiso para montar procfs, enlaza `/proc` existente en solo
lectura y conserva un namespace PID nuevo: el proceso puede ver ese índice,
pero no señalar procesos externos a su ejecución. No requiere un contenedor privilegiado.
El contenedor debe existir, estar iniciado, tener Python y bubblewrap, y montar
el checkout del Hub/estado/repositorios bajo el mapeo declarado. No se usan SSH,
instalaciones automáticas ni contenedores privilegiados.

Los prompts van por stdin y los comandos son argv. Se limita tiempo/salida y se
registra PID+identidad de los procesos propios. Cancelación/budget actúan solo
sobre procesos iniciados por esta ejecución. Dentro del contenedor se usa un
marcador privado y un ACK del runner interior; matar solo el cliente Podman no se
considera cancelación confirmada. Un cierre ambiguo exige recuperación humana.
Nunca se fuerzan locks de sesiones abiertas en otras apps.

## Policies, aprobaciones y calidad

```sh
agent-hub work policy show
agent-hub work policy set --file policy.json
agent-hub work approve TASK-001 critical-start --yes --reason 'Contrato revisado'
agent-hub work approve TASK-001 network --yes --reason 'Proveedor y herramientas autorizados'
agent-hub work approve TASK-001 dependencies --reject --reason 'No es necesario'
agent-hub work verify TASK-001 --checks checks.json
agent-hub work execute TASK-001 --profile codex-reviewer --role reviewer
agent-hub work review TASK-001 --profile codex-reviewer --report review.json
```

Ejemplo de checks: `[["python3","-B","-m","unittest","discover","-s","tests"]]`.
No hay strings de shell. Los checks son explícitos y se ejecutan offline con el
código de solo lectura; sus salidas temporales deben escribirse al scratch `/tmp`.
Si un build necesita otro directorio writable, adapta su argv para generar allí.
Un check fallido/timeout, cambio fuera de scope, permiso de escritura no concedido,
manifest de dependencias no autorizado o symlink externo impide pasar el gate.
Se incluyen archivos ignorados nuevos al comprobar scope/huella.

Las policies predeterminadas deniegan red, dependencias, commits y shell. Un JSON
puede habilitar esas capacidades y especificar excepciones de estado por perfil:

```json
{
  "network": true,
  "shell": true,
  "dependencies": false,
  "git_commit": false,
  "runtime_write_paths": {
    "codex": ["/ruta/al/estado/.codex"],
    "codex-reviewer": ["/ruta/al/estado/.codex"],
    "hermes": ["/opt/hermes/.hermes"],
    "hermes-reviewer": ["/opt/hermes/.hermes"]
  }
}
```

Es un **ejemplo que amplía permisos**, no una configuración aplicada al instalar.
Contrato y policy deben permitir una capacidad; red/dependencias y operaciones
sensibles requieren además aprobación humana ligada a la huella del trabajo.
La policy no es un intérprete semántico universal de cada comando que invente un
modelo: el sandbox impone límites de sistema, el CLI conserva sus aprobaciones,
y los gates detectan violaciones de alcance/manifests antes de aceptar resultados.
No se promete impedir toda instalación temporal dentro de un worktree writable.

El reviewer debe ser un perfil distinto del worker. Devuelve
`{"verdict":"approve|reject","issues":[...]}`; high/critical no pueden aprobarse.
Se valida tipo, ruta, línea y severidad. El reporte se liga a la misma huella que
el check; cambiar contrato o bytes invalida evidencia anterior. En críticas se
exigen code review, security review y aprobación humana final. Un perfil de
seguridad necesita `security-review`. El worker no puede aprobar su propio trabajo.

```sh
agent-hub work approve TASK-001 git-commit --yes --reason 'Diff y checks revisados'
agent-hub work workspace commit TASK-001 --message 'Implementación verificada'
agent-hub work approve TASK-001 merge --yes --reason 'Integración revisada'
agent-hub work workspace merge TASK-001
```

Commit requiere permiso en contrato y policy. La huella usa contenido/permisos,
por lo que un commit humano de esos mismos bytes conserva la evidencia. El merge
requiere tarea done, gates vigentes, aprobación y checkouts limpios; solo hace
fast-forward explícito. Divergencias/conflictos quedan para el humano, sin reset,
abort ni resolución automática. Los hooks Git no se ejecutan implícitamente en
estas operaciones del motor; los checks exigidos deben declararse en el plan.
No existe operación de push del motor.

## Skills, estado y contexto

```sh
agent-hub work skill register testing-policy --file testing-policy.md
agent-hub work skill register academic-apa --file apa.md --scope agent --owner hermes-academic
agent-hub work skill list
agent-hub work project-state set PROJECT_ID --agent hermes --file project-state.json
agent-hub work context TASK-001 --profile hermes-academic
```

Las skills son contenido local, no código ejecutado por descubrimiento. Pueden
ser globales, de perfil o proyecto; el scope/owner se valida y una skill privada
no se inyecta a otro perfil. `project-state --agent` conserva la identidad de
proyecto dentro de su namespace. El estado acepta objetivos, decisiones,
problemas y arquitectura sin depender de una conversación nativa.

Los context packs incluyen contrato, skills, estado de proyecto, branch/base,
archivos de scope, feedback de verificaciones/reviews y diff acotado. Opcionalmente
`--history` permite un JSON de texto visible user/assistant, hasta veinte entradas;
system/tool no se exportan. El límite de caracteres se calcula sobre JSON
serializado y se indican omisiones. No se inventa un resumen de un historial que
no se leyó. La preparación de contexto no llama modelos.

## Handoffs y continuación exacta

El raw handoff previo (`x` y `agent-hub transfer`) se conserva. El handoff de
trabajo estructurado es un segundo flujo:

```sh
agent-hub work handoff TASK-001 --from codex --to hermes --reason quota_exhausted --file handoff.json
agent-hub work handoff TASK-001 --from codex --to hermes --reason manual --file handoff.json --override-fixed
```

El reporte contiene summary y opcionalmente files_changed, decisions, open_issues
y next_steps. Se valida compatibilidad, skills, cadena/profundidad y presupuesto.
Un ciclo A→B→A requiere humano. El override fixed cambia el contrato de forma
explícita y auditada; la ruta de la conversación original no se reescribe.

El scheduler permite failover por cuota/token/proveedor en modo orchestrated,
con contexto y workspace conservados, sin repetir agentes de la cadena. Un fixed
se detiene. Reintentos y cambios solicitados consumen presupuesto. Los errores
nativos conservan un ID capturado aunque el turno falle. Un inicio sin ID
verificado no se vuelve a crear automáticamente desde ese perfil.

```sh
agent-hub work execution list --task TASK-001
agent-hub work execution show EXEC-001
agent-hub work execution route EXEC-001
agent-hub work execution open EXEC-001 --dry-run
agent-hub work execution open EXEC-001
agent-hub work execution bind EXEC-001 --native-id ID_VERIFICADO
# Solo si eliges empezar otra conversación explícitamente:
agent-hub work execute TASK-001 --new-session
```

Cada ejecución conserva una instantánea del perfil/adaptador real. Cambiar luego
el perfil no reinterpreta una conversación anterior. La ruta se obtiene por el
ID nativo exacto en el índice público del adaptador; se guarda completa y sus IDs
no se transforman. Una ruta guardada eliminada/inválida no se sustituye por otra.
`bind` requiere un ID nativo existente, no título/cwd/fecha. La apertura nativa
respeta locks; no usa la conversación más reciente ni crea un reemplazo.

## Runs, planificación, DAG y paralelismo

```sh
agent-hub work run plan --intent 'Implementar feature' --repo /ruta/repo --file src/file.py
agent-hub work run create --file run.json
agent-hub work run show RUN-001
agent-hub work run configure RUN-001 --file settings.json
agent-hub work run prepare RUN-001
agent-hub work run execute RUN-001 --parallel 2
agent-hub work run cancel RUN-001
agent-hub work run recover RUN-001
```

Un run tiene título, lista de contratos con keys y depends_on, repositorios,
checks y perfiles reviewer/security_reviewer opcionales. El presupuesto global
acepta max_parallel, max_agents, max_turns y timeout_seconds. El scheduler solo
inicia dependencias listas, usa una conexión SQLite y un worktree por pipeline,
y reserva presupuesto de ejecuciones de forma transaccional. El mismo run/tarea
no puede abrirse dos veces por doble clic. No paraleliza sobre un checkout común.

`plan` es deliberadamente determinista: tareas simples producen un contrato;
una petición compleja/crítica produce análisis→implementación con restricciones
conservadoras. Es un borrador revisable que requiere scope, permisos, repo y
checks antes de ejecutar, no un plan autónomo validado por un modelo. Un planner
externo puede entregar un DAG más detallado por `run create`. El orquestador
coordina y registra decisiones; no se inicia como worker con permisos ilimitados.

`settings.json` es un objeto por TASK-ID con repo, ref, checks, reviewer y/o
security_reviewer. `prepare` crea los worktrees que no tienen blockers, para
inspeccionar/aprobar antes de ejecutar. Una tarea downstream que requiere cambios
de otra espera su commit/integración explícitos antes de tomar el nuevo HEAD.
No se finge que dependencias declaradas equivalen a código ya fusionado. El
checkout original permanece intacto mientras no autorices una integración.

El estado sobrevive al proceso. `recover` solo recupera leases huérfanos cuando
no quedan procesos propios activos; un contenedor sin ACK sigue ambiguo y no
se fuerza. Un timeout o cancelación no actúa sobre otros agentes del escritorio.
La salida de consulta tiene código 0 aunque el run espere al humano; ejecutar
con fallos/gates pendientes devuelve código 1 y evidencia JSON. Errores de
validación emiten explicación en stderr. Ctrl+C mantiene la salida habitual 130.

## Métricas, auditoría y límites

```sh
agent-hub work events --run RUN-001 --after 0 --limit 100
agent-hub work events --task TASK-001
agent-hub work metrics --profile codex
```

Se guardan eventos de tareas, asignación, estado, workspaces, agentes, handoffs,
verificaciones, reviews, decisiones humanas y runs. Las métricas incluyen perfil,
modelo declarado, dominio, complejidad, éxito/fallo, duración, reintentos y rechazos
de review. Tokens/costo solo se guardan si el CLI los reporta; null significa
no disponible, no cero. No son una factura ni un estimador de precios.

max_turns cuenta invocaciones/turnos del Hub, no garantiza limitar cada llamada
interna de un proveedor. Hermes también recibe su flag nativo de max-turns. El
límite duro común es tiempo, salida, concurrencia y número de dispatches; no se
promete un límite de dinero/tokens que el CLI no exponga. Sin perfiles de costo
bajo configurados no se inventa un modelo económico alternativo.

El motor no envía telemetría ni añade red propia. Una ejecución con red autorizada
conserva el comportamiento del CLI y sus integraciones: el Hub no afirma que los
proveedores/modelos carezcan de tráfico o telemetría propia. No se añadió Git
push, actualización automática, servicios externos ni sincronización de dos vías.

SQLite usa migraciones transaccionales v1→v2→v3: v2 agrega tareas/dependencias/eventos;
v3 agrega perfiles, skills, policies, workspaces, ejecuciones, verificaciones,
reviews, aprobaciones, project state, packs, handoffs, runs, eventos y métricas.
Las tablas originales no se recrean ni borran; un esquema futuro se rechaza.
Las bibliotecas y el contrato de rutas v1 siguen vigentes. Directorios/JSON/SQLite
se mantienen privados y las conversaciones no se incluyen en Git.

## Integración de clientes

Cualquier cliente usa este CLI/JSON; no debe leer SQLite ni duplicar el motor.
Un cliente puede planear, consultar, solicitar ejecución/cancelación y abrir una
ruta de ejecución exacta. Aprobar y hacer merge siguen siendo decisiones humanas.
La personalización local de Coucou usa ese contrato mediante `/tarea`, `/estado`,
`/ejecutar`, `/cancelar`, `/tareas` y `/abrir EXEC-ID`; no forma parte del binario
o código upstream de Coucou. No cambia el chat normal ni obliga a convertir cada
mensaje del usuario en una tarea.

## Pruebas

```sh
python3 -B -m unittest discover -s tests -v
AGENT_HUB_TEST_CONTAINER=dev-podman python3 -B -m unittest discover -s tests -p test_engine_container.py -v
sh -n install.sh
agent-hub work demo
```

Las pruebas del contenedor son opt-in y requieren un contenedor/montaje existente;
solo ejecutan Python ficticio. La suite normal cubre migraciones/rollback/DAG,
concurrencia, fixed routing, especialización, scopes, sandbox real, revisión,
aprobaciones, commits/merges en fixtures, cancelación, límites y continuación
exacta. Las pruebas no consumen tokens de modelos reales. Gemini tiene fixtures
basados en su [protocolo headless](https://geminicli.com/docs/cli/headless/), pero
requiere validar la versión instalada antes de confiar en un proveedor nuevo.
