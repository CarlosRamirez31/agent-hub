> Documento objetivo suministrado por el usuario. El alcance posterior autorizó implementar todas las fases en orden. Para comandos y límites entregados, ver `task-engine.md` y `IMPLEMENTATION_PLAN.md`.

# Agent Hub / Coucou Multi-Agent Architecture

## 1. Objetivo del proyecto

Este proyecto busca evolucionar `agent-hub` y su integración con Coucou hacia una plataforma local de orquestación de agentes de IA.

El objetivo NO es crear simplemente una interfaz para abrir distintos agentes.

El objetivo es crear una infraestructura donde:

- múltiples agentes puedan trabajar sobre proyectos;
- cada agente pueda tener capacidades y especializaciones diferentes;
- un usuario pueda asignar manualmente una tarea a un agente específico;
- un agente orquestador pueda decidir qué agente debe realizar cada subtarea;
- tareas simples puedan usar modelos pequeños o baratos;
- tareas complejas puedan escalar a modelos más capaces;
- agentes especializados tengan prioridad cuando una tarea pertenezca a su dominio;
- exista revisión automática del código producido;
- diferentes agentes puedan trabajar sin destruirse mutuamente los cambios;
- el contexto pueda transferirse entre agentes;
- una conversación pueda continuar manualmente desde otro agente;
- el estado del proyecto sobreviva aunque cambie el modelo, proveedor o sesión;
- skills y políticas comunes hagan que todos los agentes trabajen de manera consistente;
- el usuario conserve control absoluto del sistema.

El sistema debe permanecer principalmente:

- local;
- terminal-first;
- compatible con navegación estilo Vim;
- basado en SQLite;
- modular;
- extensible;
- independiente del proveedor de IA.

---

# 2. Principio central

La arquitectura debe seguir este principio:

> Los agentes son reemplazables. El estado del trabajo no.

Codex, Gemini, Hermes, Claude, modelos locales u otros agentes futuros deben verse como workers.

El sistema debe conservar independientemente:

- proyectos;
- tareas;
- decisiones;
- conversaciones;
- contexto;
- resultados;
- archivos afectados;
- revisiones;
- verificaciones;
- métricas;
- handoffs;
- estado Git.

Cambiar de agente no debe implicar perder el trabajo realizado.

---

# 3. Arquitectura general

La arquitectura propuesta tiene tres grandes capas.

```text
                         USER
                          │
                          ▼
                Terminal / TUI / Vim
                          │
                          ▼
┌──────────────────────────────────────────────┐
│                  COUCOU                      │
│                                             │
│              CONTROL PLANE                  │
│                                             │
│ Planner                                     │
│ Router                                      │
│ Scheduler                                   │
│ Policies                                    │
│ Budgets                                     │
│ Orchestrator                                │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│                AGENT HUB                    │
│                                             │
│            EXECUTION / STATE PLANE          │
│                                             │
│ Projects                                    │
│ Tasks                                       │
│ Runs                                        │
│ Conversations                               │
│ Context                                     │
│ Handoffs                                    │
│ Skills                                      │
│ Worktrees                                   │
│ Events                                      │
│ Metrics                                     │
└──────────────────────┬───────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
        ▼              ▼              ▼
      Codex          Hermes         Gemini
        │              │              │
        └──────────────┼──────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│               QUALITY PLANE                 │
│                                             │
│ Verifier                                    │
│ Reviewer                                    │
│ Quality Gates                               │
│ Human Approval                              │
└──────────────────────────────────────────────┘
```

---

# 4. Responsabilidades

## Coucou

Coucou debe actuar como control plane.

Responsabilidades:

- recibir intención del usuario;
- decidir si una petición debe convertirse en una tarea;
- clasificar complejidad;
- seleccionar agente;
- crear subtareas;
- determinar dependencias;
- aplicar budgets;
- aplicar policies;
- decidir cuándo escalar a un humano;
- coordinar ejecución.

Coucou NO debe duplicar el almacenamiento ni la lógica interna de Agent Hub.

Debe utilizar Agent Hub como infraestructura persistente.

---

# 5. Agent Hub

Agent Hub debe ser la fuente de verdad del sistema.

Debe almacenar y manejar:

- proyectos;
- agentes;
- sesiones;
- conversaciones;
- tareas;
- runs;
- contexto;
- handoffs;
- workspaces;
- worktrees;
- skills;
- políticas;
- revisiones;
- verificaciones;
- artefactos;
- eventos;
- métricas.

Agent Hub no debe convertirse en un LLM.

Agent Hub administra agentes.

---

# 6. Mantener funcionalidades existentes

La implementación nueva NO debe destruir las capacidades existentes.

Se debe conservar:

- sesiones nativas;
- conversaciones existentes;
- SQLite local;
- comandos actuales;
- navegación TUI;
- shortcuts estilo Vim;
- transferencia manual de contexto;
- archivos JSON utilizados actualmente;
- capacidad de abrir una conversación existente;
- capacidad de continuar manualmente desde otro agente;
- capacidad de copiar contexto;
- handoffs manuales;
- ejecución mediante CLIs reales.

El sistema actual debe evolucionar incrementalmente.

No realizar un rewrite completo salvo que exista una razón técnica extremadamente fuerte.

---

# 7. Modos de asignación

Toda tarea debe soportar como mínimo dos modos.

## 7.1 Fixed Agent

El usuario selecciona explícitamente el agente.

Ejemplo:

```text
Usa Codex para implementar esta API.
```

Representación:

```yaml
assignment:
  mode: fixed
  agent: codex
```

El orquestador no puede sustituir este agente automáticamente.

Puede advertir problemas, pero debe respetar la decisión.

---

## 7.2 Orchestrated

El usuario permite al sistema seleccionar agentes.

```yaml
assignment:
  mode: orchestrated
```

El orquestador puede:

- seleccionar agente;
- dividir tarea;
- crear dependencias;
- usar varios agentes;
- pedir revisión;
- escalar modelo.

---

# 8. Agentes especializados

Los agentes NO deben modelarse únicamente según el proveedor.

Un agente puede estar especializado.

Ejemplo real:

```text
Hermes Academic
```

Este agente puede tener:

- skills académicas;
- búsqueda local;
- acceso a RAG;
- conocimiento del workflow universitario;
- reglas APA;
- humanización de trabajos;
- acceso a documentos académicos;
- instrucciones específicas del usuario.

Por lo tanto:

```text
tarea académica
```

debe poder preferir:

```text
Hermes Academic
```

aunque otro modelo genérico sea teóricamente más potente.

---

# 9. Agent Profiles

Cada agente debe declarar un perfil.

Ejemplo:

```yaml
agent:
  id: hermes-academic

  provider: hermes

  description:
    Agente especializado en tareas académicas.

  capabilities:
    - academic-writing
    - research
    - rag
    - apa
    - document-analysis
    - summarization

  specializations:
    - university-work
    - academic-research
    - academic-formatting

  skills:
    - academic-research
    - apa-format
    - humanize
    - source-validation

  tools:
    - local-rag
    - web-search
    - filesystem

  context:
    max: high

  cost:
    class: local

  priority_domains:
    - academic
```

Otro agente:

```yaml
agent:
  id: codex

  capabilities:
    - coding
    - debugging
    - refactoring
    - testing
    - architecture

  specializations:
    - backend
    - cli
    - automation

  cost:
    class: high
```

---

# 10. Selección basada en especialización

La selección no debe ser:

```text
modelo más potente
```

Debe considerar:

```text
capability match
specialization
skills disponibles
task complexity
cost
context capacity
availability
historical success
```

Ejemplo:

```text
Crear trabajo académico en APA
```

Puede producir:

```text
Hermes Academic: 96 puntos
Gemini: 82
Codex: 61
```

Hermes gana aunque no sea el modelo con mayor capacidad general.

---

# 11. Task Contract

Toda tarea ejecutable debe tener un contrato.

Ejemplo:

```yaml
task:
  id: TASK-0042

  title:
    Cambiar color del botón Save

  objective:
    Cambiar el botón Save para utilizar el color success.

  scope:
    files:
      - src/components/SaveButton.tsx

  constraints:
    - no modificar comportamiento
    - no instalar dependencias
    - no modificar otros componentes

  acceptance:
    - componente compila
    - lint pasa
    - botón usa token success

  complexity:
    trivial

  assignment:
    mode: orchestrated

  permissions:
    filesystem: write
    network: false
    dependencies: false
    git_commit: false

  review:
    required: false
```

Esto limita el scope del agente.

---

# 12. Clasificación de complejidad

Las tareas deben clasificarse:

```text
TRIVIAL
SMALL
MEDIUM
COMPLEX
CRITICAL
```

## TRIVIAL

Ejemplos:

- cambiar color;
- cambiar texto;
- rename;
- modificar constante;
- corregir typo.

Usar modelos pequeños/baratos.

---

## SMALL

Ejemplos:

- agregar campo;
- pequeño endpoint;
- pequeña validación;
- pequeño componente.

---

## MEDIUM

Ejemplos:

- feature aislada;
- integración moderada;
- cambios en varios archivos.

---

## COMPLEX

Ejemplos:

- arquitectura;
- refactor importante;
- subsistema;
- migración compleja.

---

## CRITICAL

Ejemplos:

- autenticación;
- autorización;
- seguridad;
- migraciones destructivas;
- producción;
- infraestructura sensible.

Requiere revisión adicional.

---

# 13. Clasificador híbrido

La complejidad no debe depender completamente de un LLM.

Primero usar heurísticas.

Ejemplo:

```text
1 archivo
< 30 líneas
sin DB
sin auth
sin dependencias
sin infraestructura

→ probable TRIVIAL
```

Después un modelo puede ajustar la clasificación.

---

# 14. Routing

Pipeline:

```text
Task
  │
  ▼
Analyze requirements
  │
  ▼
Detect domain
  │
  ▼
Detect required capabilities
  │
  ▼
Detect specialization
  │
  ▼
Complexity
  │
  ▼
Candidate agents
  │
  ▼
Cost / availability / metrics
  │
  ▼
Agent
```

Una fórmula futura podría considerar:

```text
score =
    capability_match
  + specialization_match
  + skill_match
  + historical_success
  + availability
  + context_fit
  + speed
  - cost
```

Inicialmente mantener reglas simples.

---

# 15. Skills

Las skills describen cómo realizar un tipo de trabajo.

Estructura sugerida:

```text
skills/

coding/
    implement-feature.md
    fix-bug.md
    refactor.md

testing/
    unit-tests.md
    integration-tests.md

review/
    code-review.md
    security-review.md
    architecture-review.md

academic/
    academic-research.md
    apa.md
    humanize.md
    source-validation.md

git/
    commit.md
    branch.md

project/
    conventions.md
```

---

# 16. Skills específicas por agente

Un agente puede tener skills privadas.

Ejemplo:

```text
agents/
  hermes-academic/
    skills/
      academic-rag.md
      unicaribe.md
      apa-workflow.md
```

Estas skills pueden darle capacidades que otros agentes no poseen.

El router debe conocerlas.

---

# 17. Skills globales

También deben existir skills compartidas.

```text
global skills
```

Ejemplo:

```text
coding-standard
git-conventions
testing-policy
response-format
security-baseline
```

Todos los agentes deben poder recibirlas.

---

# 18. Policies

Skills y policies son conceptos diferentes.

Skills:

```text
cómo hacer algo
```

Policies:

```text
qué se permite hacer
```

Ejemplo:

```yaml
policies:

  destructive_commands:
    approval_required: true

  dependencies:
    install:
      approval_required: true

  database:
    destructive_migration:
      approval_required: true

  filesystem:
    outside_workspace:
      allowed: false

  git:
    push:
      allowed: false
```

---

# 19. Permisos por agente

Los agentes deben tener permisos explícitos.

Ejemplo:

```yaml
permissions:
  filesystem:
    read: true
    write: true

  network:
    allowed: false

  git:
    commit: true
    push: false

  shell:
    allowed: true
```

---

# 20. Roles

Mantener pocos roles.

Primera versión:

```text
ORCHESTRATOR
WORKER
REVIEWER
VERIFIER
```

Opcional posteriormente:

```text
RESEARCHER
```

Evitar crear decenas de roles artificiales.

---

# 21. Orchestrator

Responsabilidades:

- entender objetivo;
- crear Task Contracts;
- dividir tareas;
- crear dependencias;
- seleccionar agentes;
- aplicar budgets;
- solicitar revisión;
- escalar decisiones.

NO debe:

- editar código directamente;
- saltarse quality gates;
- modificar policies;
- hacer push arbitrariamente;
- aprobar su propio trabajo.

---

# 22. Worker

Ejecuta una tarea.

Debe recibir:

```text
Task Contract
Context Pack
Skills
Policies
Workspace
Budget
```

Produce:

```text
Result
Files changed
Summary
Potential issues
Tests executed
Artifacts
```

---

# 23. Reviewer

El reviewer analiza el trabajo.

Idealmente debe ser read-only.

```yaml
role: reviewer

permissions:
  filesystem:
    read: true
    write: false

  git:
    diff: true

  tests:
    execute: true
```

Salida:

```json
{
  "verdict": "reject",
  "issues": [
    {
      "severity": "high",
      "file": "AuthService.cs",
      "line": 84,
      "message": "Refresh token stored in plaintext."
    }
  ]
}
```

---

# 24. Verifier

El verifier no opina.

Ejecuta controles deterministas.

Ejemplo:

```text
build
tests
lint
typecheck
security checks
```

Produce:

```text
PASS
FAIL
```

con evidencia.

---

# 25. Quality gates

Los gates dependen de la complejidad.

## Trivial

```text
Worker
 ↓
Verifier
 ↓
Done
```

## Small

```text
Worker
 ↓
Tests
 ↓
Done
```

## Medium

```text
Worker
 ↓
Verifier
 ↓
Reviewer
 ↓
Done
```

## Complex

```text
Planner
 ↓
Worker
 ↓
Verifier
 ↓
Reviewer
 ↓
Fix
 ↓
Review
 ↓
Merge
```

## Critical

```text
Planner
 ↓
Human approval
 ↓
Worker
 ↓
Verification
 ↓
Security review
 ↓
Code review
 ↓
Human approval
 ↓
Merge
```

---

# 26. Workspace isolation

Nunca permitir múltiples agentes modificando el mismo workspace simultáneamente sin coordinación.

Usar Git Worktrees.

Ejemplo:

```text
.agent-hub/

worktrees/
    TASK-001/
    TASK-002/
    TASK-003/
```

Cada worker trabaja en su propio worktree.

---

# 27. Flujo Git

Ejemplo:

```text
main

  ↓

worktree TASK-101

  ↓

agent changes

  ↓

verification

  ↓

review

  ↓

merge
```

El merge puede requerir aprobación humana según policy.

---

# 28. Task DAG

Las tareas deben soportar dependencias.

Ejemplo:

```text
           TASK-1
          /      \
      TASK-2    TASK-3
          \      /
           TASK-4
```

Representarlas como DAG.

Permitir paralelización cuando no haya dependencias.

---

# 29. Estados

Estados sugeridos:

```text
PENDING
READY
BLOCKED
RUNNING
VERIFYING
REVIEWING
CHANGES_REQUESTED
WAITING_HUMAN
FAILED
DONE
CANCELLED
```

---

# 30. Runs

Una petición compleja crea un Run.

Ejemplo:

```text
RUN-20261023-001
```

Contiene:

```text
TASK-001
TASK-002
TASK-003
TASK-004
```

Permite observar todo el flujo.

---

# 31. Contexto

No considerar conversación completa como única fuente de contexto.

Separar:

```text
Conversation History

Project State

Task State
```

---

# 32. Project State

Ejemplo:

```json
{
  "project": "HermesAcademico",

  "goal":
    "RAG académico local",

  "architecture": [
    "ChromaDB",
    "local-first"
  ],

  "decisions": [
    "buscar local primero",
    "fallback a internet"
  ],

  "current_tasks": [
    "integrar búsqueda web"
  ],

  "problems": [
    "ranking de fuentes"
  ]
}
```

---

# 33. Context Packs

Crear una entidad formal:

```text
ContextPack
```

Ejemplo:

```yaml
context_pack:

  project:
    architecture: true
    conventions: true

  task:
    contract: true

  history:
    recent_messages: 20

  files:
    relevant_only: true

  git:
    diff: true
    branch: true

  decisions:
    include: true
```

---

# 34. Context minimization

No enviar 100k tokens innecesariamente.

Una tarea trivial puede recibir:

```text
2 KB - 5 KB
```

Una tarea compleja:

```text
30 KB - 60 KB
```

El Context Builder debe seleccionar únicamente lo relevante.

---

# 35. Mantener Raw Handoff

IMPORTANTE:

La funcionalidad actual de copiar contexto debe permanecer.

Debe existir un modo:

```text
RAW HANDOFF
```

Esto permite al usuario:

```text
Codex
 ↓
copiar contexto
 ↓
Gemini
```

y continuar hablando manualmente.

No reemplazar esto por completo con resúmenes automáticos.

---

# 36. Structured Handoff

Añadir un segundo modo:

```text
STRUCTURED HANDOFF
```

Ejemplo:

```json
{
  "source_agent": "codex",

  "target_agent": "gemini",

  "task": "TASK-44",

  "reason": "quota_exhausted",

  "summary":
    "Implementación parcialmente completada.",

  "files_changed": [
    "AuthService.cs"
  ],

  "decisions": [
    "usar refresh token HttpOnly"
  ],

  "open_issues": [
    "tests fallando"
  ],

  "next_steps": [
    "corregir tests"
  ]
}
```

---

# 37. Transferencia por agotamiento de tokens

Debe existir soporte explícito para:

```text
quota exceeded
token limit
provider unavailable
CLI failure
```

Flujo:

```text
Agent A
 ↓
failure
 ↓
create structured handoff
 ↓
select compatible Agent B
 ↓
resume task
```

El usuario también debe poder hacerlo manualmente.

---

# 38. Budgets

Toda ejecución debe tener límites.

Ejemplo:

```yaml
budget:

  max_turns: 12

  max_retries: 2

  max_agents: 3

  max_handoff_depth: 3

  context:
    max_chars: 40000
```

---

# 39. Protección contra loops

Detectar:

```text
Agent A → Agent B → Agent A
```

Registrar cadena de handoff.

Si existe un ciclo:

```text
require orchestrator decision
```

o:

```text
WAITING_HUMAN
```

---

# 40. Agent Registry

Crear un registry central.

Ejemplo:

```text
AgentRegistry
```

Funciones:

```text
register()
unregister()
available()
capabilities()
skills()
specializations()
metrics()
```

---

# 41. Agent Adapter

Todos los proveedores deben implementar interfaz común.

Ejemplo conceptual:

```python
class AgentAdapter:

    def capabilities(self):
        pass

    def create_session(self, context):
        pass

    def resume_session(self, session_id):
        pass

    def execute_task(self, task, context):
        pass

    def export_history(self, session_id):
        pass

    def cancel(self):
        pass
```

---

# 42. Adapters iniciales

Mantener/adaptar:

```text
CodexAdapter
HermesAdapter
GeminiAdapter
```

Futuro:

```text
ClaudeAdapter
OpenCodeAdapter
LocalLLMAdapter
```

---

# 43. Métricas

Registrar desempeño.

Por:

```text
agent
model
task_type
domain
complexity
```

Métricas:

```text
success_rate
review_rejection_rate
average_retries
duration
tokens
cost
failure_rate
```

---

# 44. Aprendizaje del router

El router puede utilizar métricas históricas.

Ejemplo:

```text
academic-writing:

Hermes Academic
success = 97%

Gemini
success = 89%

Codex
success = 72%
```

Entonces Hermes recibe preferencia.

Esto debe complementar, no reemplazar, las reglas explícitas.

---

# 45. Event Log

Agregar event sourcing liviano.

Tabla:

```text
events
```

Ejemplos:

```text
run.created
task.created
task.assigned
task.started
agent.started
file.changed
verification.started
verification.failed
review.started
review.rejected
task.reassigned
handoff.created
human.approved
task.completed
run.completed
```

Esto permite auditoría.

---

# 46. SQLite

Expandir base de datos actual.

Tablas sugeridas:

```text
projects
agents
agent_capabilities
agent_skills

conversations
messages

runs

tasks
task_dependencies
task_assignments

skills
policies

workspaces

handoffs

reviews
verifications

events

agent_metrics
```

Utilizar migraciones incrementales.

NO borrar ni invalidar datos actuales.

---

# 47. Estructura sugerida de código

```text
agent_hub/

core/
    models.py
    events.py
    state.py
    exceptions.py

agents/
    base.py
    registry.py
    codex.py
    hermes.py
    gemini.py

tasks/
    model.py
    planner.py
    scheduler.py
    dependencies.py

orchestration/
    orchestrator.py
    router.py
    classifier.py
    budgets.py

context/
    builder.py
    pack.py
    handoff.py
    summarizer.py

execution/
    runner.py
    workspace.py
    worktree.py

review/
    reviewer.py
    verifier.py
    gates.py

skills/
    loader.py
    registry.py

policies/
    engine.py
    permissions.py

storage/
    sqlite.py
    repositories/
    migrations/

ui/
    tui.py
    views/

cli/
```

No imponer exactamente esta estructura si la arquitectura actual ofrece una separación mejor.

Priorizar cambios incrementales.

---

# 48. TUI

Mantener navegación rápida.

Secciones futuras:

```text
Projects
Agents
Runs
Tasks
Reviews
Handoffs
Skills
```

Shortcuts sugeridos:

```text
j/k navigate

h/l tabs

n new task

o orchestrate

a assign

x handoff

c context

r review

v verify
```

---

# 49. Visualización de tareas

Ejemplo:

```text
RUN-128

✓ TASK-1 Analyze authentication

✓ TASK-2 Implement token service

▶ TASK-3 Implement refresh endpoint
  Agent: Codex

○ TASK-4 Frontend
  Blocked by TASK-3

○ TASK-5 Tests

○ TASK-6 Review
```

---

# 50. Human-in-the-loop

El humano siempre debe poder intervenir.

Ejemplo:

```text
TASK-44 requires approval

Operation:
DROP COLUMN legacy_token

[a] approve
[r] reject
[v] view
```

---

# 51. Override manual

El usuario debe poder:

```text
reassign TASK-44 codex

reassign TASK-44 hermes

cancel TASK-44

retry TASK-44

force-review TASK-44

handoff TASK-44 gemini
```

El usuario tiene autoridad superior al orquestador.

---

# 52. Ejemplo: tarea académica

Usuario:

```text
Hazme el trabajo de filosofía siguiendo APA.
```

Pipeline:

```text
Intent
 ↓
domain = academic
 ↓
skills required:
academic-writing
research
APA
 ↓
Agent Registry
 ↓
Hermes Academic
 ↓
execute
```

No es necesario iniciar múltiples agentes.

---

# 53. Ejemplo: tarea trivial

Usuario:

```text
Cambia este botón de azul a verde.
```

Resultado:

```text
complexity = trivial

cheap coding agent
 ↓
change
 ↓
lint
 ↓
done
```

No utilizar modelo premium innecesariamente.

---

# 54. Ejemplo: feature compleja

Usuario:

```text
Implementa recuperación de contraseña.
```

Orchestrator:

```text
TASK-1 Analyze current auth

TASK-2 Backend token generation

TASK-3 Email integration

TASK-4 Frontend

TASK-5 Tests

TASK-6 Review
```

DAG:

```text
TASK-1
  │
 ┌┴────────┐
 ▼         ▼
TASK-2   TASK-3
  │         │
  └────┬────┘
       ▼
     TASK-4
       ▼
     TASK-5
       ▼
     TASK-6
```

---

# 55. Ejemplo: agente fijo

Usuario:

```text
Quiero que Codex haga solamente esta parte.
```

Task:

```yaml
assignment:

  mode: fixed

  agent: codex
```

El orchestrator respeta la asignación.

---

# 56. Ejemplo: review independiente

Worker:

```text
Codex
```

implementa.

Reviewer:

```text
Gemini
```

revisa.

El reviewer recibe:

```text
Task Contract
Diff
Relevant context
Tests
```

No necesita toda la conversación.

---

# 57. Contexto manual

Debe seguir existiendo:

```text
Open conversation

Copy context

Transfer conversation

Continue in external CLI
```

El sistema automatizado NO debe impedir el workflow manual.

---

# 58. Filosofía de UX

Agent Hub debe ser:

```text
powerful when needed
invisible when unnecessary
```

Una tarea sencilla no debe requerir:

```text
planner
orchestrator
3 workers
reviewer
security reviewer
committee meeting
sacrificio ritual
```

Debe simplemente ejecutarse.

---

# 59. Orden de implementación

NO implementar todo simultáneamente.

## Phase 1 - Task Engine

Crear:

```text
Task model
Task Contract
Task states
Task persistence
Task dependencies
```

---

## Phase 2 - Agent Registry

Crear:

```text
Agent Profile
Capabilities
Specializations
Skills
Availability
```

---

## Phase 3 - Fixed Assignment

Permitir:

```text
Task → specific agent
```

---

## Phase 4 - Worktree Isolation

Implementar:

```text
one task
one worktree
```

---

## Phase 5 - Verifier

Implementar:

```text
build
tests
lint
```

---

## Phase 6 - Reviewer

Agregar revisión estructurada.

---

## Phase 7 - Skills

Agregar:

```text
global skills
agent-specific skills
project skills
```

---

## Phase 8 - Policies

Agregar permission engine.

---

## Phase 9 - Complexity Classifier

Crear clasificación híbrida.

---

## Phase 10 - Router

Seleccionar agente automáticamente.

---

## Phase 11 - Structured Context

Agregar:

```text
Project State
Task State
Context Packs
Structured Handoff
```

Mantener Raw Handoff.

---

## Phase 12 - Orchestrator

Permitir:

```text
task decomposition
DAG generation
agent assignment
```

---

## Phase 13 - Metrics

Registrar desempeño.

---

## Phase 14 - Parallel Execution

Solo después de que isolation, verification y review sean estables.

---

# 60. Reglas de implementación para la IA

La IA encargada de implementar debe seguir estas reglas.

## Regla 1

Antes de modificar código:

```text
analizar arquitectura existente
```

No asumir que este README reemplaza lo que ya existe.

---

## Regla 2

No realizar un rewrite completo.

Preferir:

```text
incremental refactor
```

---

## Regla 3

Mantener compatibilidad hacia atrás.

Los comandos existentes deben continuar funcionando salvo razón justificada.

---

## Regla 4

No eliminar funcionalidades existentes sin autorización.

Especialmente:

```text
conversation browsing
manual context copy
manual handoffs
native session continuation
SQLite persistence
Vim shortcuts
```

---

## Regla 5

Cada fase debe incluir tests.

---

## Regla 6

No implementar orquestación multi-agent hasta estabilizar:

```text
Task Engine
Agent Registry
Isolation
Verifier
```

---

## Regla 7

No permitir múltiples agentes editando el mismo workspace.

---

## Regla 8

No otorgar al orchestrator permisos ilimitados.

---

## Regla 9

Las decisiones importantes deben quedar persistidas.

---

## Regla 10

Mantener arquitectura provider-agnostic.

Nunca diseñar el core exclusivamente alrededor de:

```text
Codex
Gemini
Hermes
```

Son adapters.

---

# 61. Primer trabajo que debe realizar la IA

La implementación debe comenzar analizando el repositorio actual.

Primero producir:

```text
CURRENT_ARCHITECTURE.md
```

Debe explicar:

- estructura actual;
- entry points;
- SQLite schema;
- adapters existentes;
- flujo actual de sesiones;
- flujo actual de context transfer;
- TUI;
- comandos;
- puntos de extensión;
- deuda técnica relevante.

Después producir:

```text
IMPLEMENTATION_PLAN.md
```

Mapeando:

```text
arquitectura actual
→
arquitectura objetivo
```

---

# 62. Primera implementación

Después del análisis, comenzar únicamente con:

```text
Phase 1
Task Engine
```

Debe incluir:

```text
Task model
Task persistence
Task states
Task Contract
Task dependencies
SQLite migrations
CLI mínimo
tests
```

NO implementar todavía:

```text
autonomous orchestrator
parallel execution
intelligent routing
automatic model selection
```

---

# 63. Criterios de aceptación de Phase 1

Debe ser posible ejecutar:

```bash
agent-hub task create
```

listar:

```bash
agent-hub task list
```

ver:

```bash
agent-hub task show TASK-001
```

y cambiar estado:

```bash
agent-hub task status TASK-001 ready
```

Las tareas deben persistir en SQLite.

Las funcionalidades anteriores deben seguir funcionando.

---

# 64. Principios no negociables

## 1

Human control first.

## 2

Provider independence.

## 3

Persistent state.

## 4

Deterministic controls before AI decisions.

## 5

Isolation before concurrency.

## 6

Verification before trust.

## 7

Specialization matters.

## 8

Cheap models for cheap problems.

## 9

Strong models only when justified.

## 10

Manual workflows must remain available.

---

# 65. Objetivo final

El resultado esperado debe permitir algo como:

```text
User
 ↓
"Implementa feature X"
 ↓
Coucou
 ↓
Analyze
 ↓
Plan
 ↓
Task DAG
 ↓
Agent Routing
 ↓
Workers
 ↓
Verifier
 ↓
Reviewer
 ↓
Human if required
 ↓
Merge
```

Pero también:

```text
User
 ↓
"Codex, arregla esto."
 ↓
Codex
 ↓
Done
```

Y:

```text
User
 ↓
"Haz este trabajo universitario."
 ↓
Router
 ↓
Hermes Academic
 ↓
Academic skills + RAG
 ↓
Result
```

Y:

```text
Codex quota exhausted
 ↓
Structured Handoff
 ↓
Gemini
 ↓
Continue task
```

Y manualmente:

```text
User
 ↓
Copy raw conversation context
 ↓
Open another agent
 ↓
Continue talking
```

---

# 66. Resultado deseado

Este proyecto no debe convertirse en:

```text
un enjambre de agentes hablando entre ellos sin control
```

Debe convertirse en:

```text
una plataforma controlada,
observable,
auditable,
modular
y predecible
para trabajar con múltiples agentes.
```

La inteligencia puede ser probabilística.

La infraestructura no debería serlo.

---

# Instructions for the implementation agent

Read the existing repository completely before making architectural changes.

Do not blindly implement this document.

Treat this document as the target architecture.

Compare it against the existing implementation.

Reuse everything that is already structurally sound.

Preserve existing workflows.

Create migration paths instead of rewrites.

Implement incrementally.

Start with Phase 1.

For every meaningful architectural decision:

1. explain the current behavior;
2. explain the problem;
3. propose the change;
4. identify compatibility risks;
5. implement;
6. add tests;
7. verify existing functionality still works.

Do not introduce unnecessary frameworks or dependencies.

Prefer simple Python abstractions and SQLite unless a stronger technical reason exists.

Do not add distributed infrastructure for a local-first application.

Do not turn every operation into an LLM call.

Prefer deterministic code whenever deterministic code can solve the problem.

The final system should feel like a serious developer tool, not an AI demo.