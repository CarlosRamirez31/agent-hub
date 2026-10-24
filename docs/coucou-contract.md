# Contrato Coucou → Agent Hub, versión 1

## Identidad persistida

Coucou guarda una ruta por tarea/ejecución, asociada al agente que realmente la ejecutó. Una carpeta con varias tareas no tiene una única conversación implícita.

```json
{"version":1,"idCarpeta":"ID_OPACO_DEL_PROYECTO","idMessage":"ID_OPACO_DE_LA_CONVERSACION","agente":"codex"}
```

- `version`: `1`; el hub admite omitirlo por compatibilidad, pero Coucou debe guardarlo.
- `agente`: ID registrado, formato `[a-z][a-z0-9_-]{0,63}`.
- `idCarpeta`: string opaco no vacío, máximo 4096 caracteres. No es necesariamente una ruta física.
- `idMessage`: **ID de conversación**, no de mensaje; formato `[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}`. Puede ser nativo, `new-...` o `handoff-...`; no lo reemplaces por el título.
- Sin campos adicionales. Esquema: [route.schema.json](route.schema.json).

## Descubrimiento y asociación

Los comandos siguientes devuelven JSON en stdout (sin interfaz curses); los argumentos se pasan como elementos separados de argv. `--json` explicita la intención aunque estos subcomandos ya producen JSON.

```text
["agent-hub", "agents", "--json"]
["agent-hub", "projects", "--agent", AGENTE, "--json"]
["agent-hub", "conversations", "--agent", AGENTE, "--json"]
["agent-hub", "conversations", "--agent", AGENTE, "--folder", ID_CARPETA, "--json"]
```

`agents` devuelve un array con `id`, `name`, `installed`, `reader`, `home`, `container`. `projects` devuelve un array con `id`, `name`, `roots`, `source`, `agente`, `idCarpeta`. `conversations` devuelve un array con `id`, `title`, `cwd`, `updated`, `archived`, `project_id`, **`route`**. Persiste `route` completo. Estos comandos no consumen tokens ni empiezan turnos del modelo.

Si el runner de Coucou ya conoce el ID nativo exacto, encuentra la entrada por igualdad de ID y agente. No uses nombre, orden, fecha o coincidencia aproximada. También puedes validar/canonizar IDs conocidos:

```text
["agent-hub", "route", "--agent", AGENTE, "--folder", ID_CARPETA, "--conversation", ID_CONVERSACION]
```

La salida es directamente el objeto `route`. Un alias preparado conserva su identidad estable aunque posteriormente se enlace a un ID nativo. Si Coucou inició el agente por su propia vía, captura el ID de sesión de sus eventos/API documentados y guarda su asociación con la ejecución; **no uses `new` para simular que encontraste una sesión que ya existe**. Si todavía no se conoce el ID, muestra un estado pendiente o un selector explícito.

Para una tarea que aún no tiene conversación y cuyo usuario quiere crearla:

```text
["agent-hub", "new", "--agent", AGENTE, "--folder", ID_CARPETA, "--json"]
```

Devuelve un `route` con ID `new-...`; prepara el registro sin iniciar el modelo. Guarda la ruta antes de abrir. La primera apertura inicia la sesión; al salir del agente, el hub intenta enlazar el único ID nativo nuevo de esa carpeta. Si no puede identificarlo de forma única, una apertura posterior falla, evitando crear otra sesión. La recuperación explícita es:

```text
["agent-hub", "bind", "--agent", AGENTE, "--conversation", ID_NEW_O_HANDOFF, "--native-id", ID_NATIVO_VERIFICADO]
```

`bind` retorna éxito sin salida JSON. Su ID nativo debe existir en la misma carpeta. Coucou no debe adivinarlo ni ejecutarlo sin evidencia.

## Abrir terminal en la conversación actual

1. Resuelve la tarea/ejecución visible o seleccionada en Coucou y su `route`; no tomes la última tarea de la carpeta.
2. Escribe el objeto como JSON UTF-8 en el estado privado de Coucou, con directorio 0700, archivo 0600 y escritura atómica. Conserva el archivo hasta que el proceso hijo haya podido leerlo. Usa rutas absolutas.
3. Valida sin iniciar el agente:

```text
["agent-hub", "open", "--route-file", RUTA_ABSOLUTA_JSON, "--dry-run"]
```

La respuesta de éxito es `{"valid":true,"route":{...},"cwd":"/ruta/de/trabajo"}`. No garantiza que otra app no tenga la sesión bloqueada ni que una fuente en caché esté accesible al abrir.

4. Usa el lanzador/emulador de terminal ya configurado por Coucou. Su proceso hijo debe recibir exactamente:

```text
["agent-hub", "open", "--route-file", RUTA_ABSOLUTA_JSON]
```

Este comando **abre directamente el agente nativo en esa conversación y su cwd**, sin pasar por el selector del hub. Al salir, termina ese proceso de apertura; no promete volver al menú del hub. Si la tarea sigue activa en Coucou y el agente impide dos sesiones simultáneas, informa el bloqueo y ofrece detener/liberar la ejecución usando el flujo existente antes de reintentar. No mates procesos, fuerces locks ni hagas fork automáticamente.

No todos los emuladores aceptan `-e`. Usa sus APIs/flags reales y argv separados; no `sh -c`, interpolación, `eval` o JSON convertido en comando. Un doble clic no debe iniciar dos procesos de apertura ni dos sesiones nuevas.

## Errores y alcance

- Error de contrato, ruta ausente, agente no registrado, carpeta incorrecta, conversación borrada o ID ambiguo: código `1`, texto `agent-hub: ...` en stderr; no se abre otro chat como fallback.
- Interrupción de teclado: `130`. La apertura real devuelve el código de salida del CLI nativo; no todos sus errores siguen el formato del hub.
- `new --launch` y `transfer --launch` pueden escribir un descriptor y luego iniciar un CLI interactivo: no usarlos como una respuesta JSON única. Separar preparación y apertura.
- Los comandos que necesitan datos sincronizan índices al ejecutarse. Una fuente temporalmente inaccesible puede conservar caché; una ruta válida no garantiza acceso a la fuente en ese momento. `sync --json` informa errores por agente y devuelve `1` si los hay.
- `d` dentro de Agent Hub puede borrar historiales originales y carpetas físicas. Coucou debe volver a validar al abrir y mostrar el error si la asociación quedó obsoleta; nunca recrear sesiones por su cuenta. Esta integración no llama a operaciones de borrado.
- No leer SQLite privada, sesiones nativas, credenciales ni formatos internos desde Coucou. No añade servidores, terceros ni proveedores.
- Este contrato cubre agentes registrados en Agent Hub; no importa conversaciones de ChatGPT web ni borra remotos.

## Verificación de aceptación

Fixtures/stubs: Codex y Hermes válidos; carpeta con varias tareas/agentes; IDs opacos; `new` y `handoff` antes/después de enlazar; tarea activa/bloqueada; conversación/carpeta eliminada; binario ausente; fuente inaccesible; ID ambiguo; rutas con espacios, comillas, Unicode y metacaracteres; doble clic y cancelación. Verifica argv exactos y que nunca se abra una sesión distinta. Sin llamadas al modelo en tests.
