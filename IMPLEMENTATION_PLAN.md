# Plan incremental: motor local de trabajo

Se conserva la arquitectura actual y se extiende; no se reescriben adaptadores,
TUI, rutas v1, bibliotecas JSON ni transferencias manuales. El alcance solicitado
incluye todas las fases, implementadas y verificadas en orden. Las pruebas no
llaman modelos reales. Los cambios permanecen locales, sin push/PR.

| Fase | Extensión sobre lo existente | Verificación / compatibilidad |
|---|---|---|
| 1 Task Engine | Modelo/contrato, estados, DAG y persistencia en Cache; CLI task | migración v1, rollback, ciclos, transiciones y CLI sin agentes |
| 2 Registry | Perfiles y capacidades, especializaciones y disponibilidad explícita | IDs independientes del proveedor, no capacidades inventadas |
| 3 Fixed assignment | Contrato fixed inmutable para el router | falta de agente no permite reemplazo silencioso |
| 4 Isolation | Worktree propio por tarea, sin tocar checkout del usuario | cambios locales preservados, sin concurrencia en mismo workspace |
| 5 Verifier | Checks deterministas por argv, tiempo y evidencia | fallos/timeout impiden completar; no shell implícita |
| 6 Reviewer | Resultado estructurado, identidad independiente y gates | no autoaprobación del worker; evidencias ligadas a revisión de trabajo |
| 7 Skills | Registro local global/perfil/proyecto y composición acotada | no descargar ni ejecutar contenido por descubrirlo |
| 8 Policies | Permisos y aprobaciones explícitas | denegar capacidades que no se puedan hacer cumplir |
| 9 Classifier | Heurísticas explicables y override humano | cambios sensibles no se degradan por tamaño de diff |
| 10 Router | Reglas de capacidades/especialización/costo/disponibilidad | fixed prevalece; historial complementa las reglas |
| 11 Context | Estado del proyecto, packs acotados y handoff estructurado | preservar raw handoff; ciclo/profundidad/IDs verificados |
| 12 Orchestrator | Runs/DAG, scheduler y decisiones persistidas | sin trabajo autónomo antes de isolation/gates; sin autoaprobar |
| 13 Metrics | Métricas y eventos locales por perfil/tipo/complejidad | valores desconocidos no se inventan; sin telemetría |
| 14 Parallel | Workers en worktrees separados y dependencias listas | budgets, cancelación, fallos y exclusión de workspace |

## Decisiones y límites

El estado de tareas es propio del hub y no depende del índice de ningún agente.
Las migraciones son aditivas, transaccionales y rechazan versiones futuras. La
misma conexión puede servir a Manager y al motor; los comandos nuevos no
sincronizan historiales innecesariamente.

El contrato es JSON versionado, validado con Python estándar. YAML es un ejemplo
conceptual del diseño, no una nueva dependencia. Los contratos guardan objetivos,
aceptación, alcance, restricciones, asignación, permisos y presupuesto. Declarar
permisos no implica que un adaptador pueda imponerlos: la ejecución debe comprobar
el mecanismo de aislamiento o rechazar la operación, sin flags de bypass.

Los comandos nuevos usan un namespace separado. Los estados y resultados son
observables por CLI JSON para Coucou, que sigue siendo cliente/control plane.
La TUI actual no pierde atajos ni cambia el significado de abrir una conversación.
Cualquier vista nueva debe ser opt-in. La elección de modelos queda limitada a
los perfiles configurados explícitamente por el usuario; no se cambia su proveedor
o autenticación ni se lanzan modelos para probar la instalación.

## Criterios de cierre

Documentar comandos reales y limitaciones por fase. Probar migración con fixtures
v1, preservación de rutas/transferencias, determinismo, fallos y concurrencia con
stubs. Ejecutar toda la suite anterior, nuevas pruebas y `sh -n install.sh`.
No declarar fases completas si solo existe un esquema o una opción sin ejecución
real, control de errores y pruebas correspondientes.

## Implementación entregada por fase

| Fase | Código | Evidencia principal |
|---|---|---|
| 1 | engine/tasks.py, migrations.py | test_tasks: persistencia, DAG, revisión, migración/rollback, CLI sin agentes |
| 2 | engine/profiles.py, bootstrap.py, doctor.py | perfiles reales sin modelos y conservación de configuración |
| 3 | tasks.py, routing.py, execution.py | fixed no se sustituye ante cuota; override humano auditado |
| 4 | workspace.py, process.py, container.py | checkout sucio preservado, worktree propio y sandbox real |
| 5 | quality.py | checks offline, scope, fingerprint y evidencia obsoleta |
| 6 | quality.py, execution.py | reviewer distinto/read-only y gates críticos |
| 7 | skills.py, context.py | scope global/perfil/proyecto y minimización |
| 8 | policy.py, process.py | denegación inicial, aprobaciones ligadas a huella, no push |
| 9 | routing.classify | reglas explicables, sensibles escalan a critical |
| 10 | routing.Router | especialización/skills/costo declarado/historial y fixed |
| 11 | context.py, conversations.py | estado independiente, handoff, ciclos y ruta nativa exacta |
| 12 | runs.py, work_cli.py, tui.py | planes revisables, DAG, transiciones y humano |
| 13 | engine_events/task_events/agent_metrics | duración/éxito/reintentos/reviews, tokens/costo solo reportados |
| 14 | runs.py, process.py, container_process.py | paralelismo aislado, reservas, cancelación y ACK de contenedor |

La integración local de Coucou vive en dotfiles y solo consume CLI JSON. El Hub
no contiene el código ni el binario de Coucou. Los módulos de ejecución del Hub
no se copian a dotfiles. Se documentan en `docs/task-engine.md` los límites:
planificación determinista revisable, permisos de red explícitos (incluyen al
proveedor), excepciones reales de estado nativo, tokens/costo no inventados,
merge manual fast-forward y validación de nuevas versiones de CLI. Las pruebas
con procesos/containers son ficticias; no prueban la calidad de modelos reales.
