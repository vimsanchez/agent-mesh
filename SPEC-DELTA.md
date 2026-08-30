# Agent Mesh — SPEC-DELTA v0.2

**Qué es este documento.** Cambios al servicio sobre lo que hoy vive en `main` de
`vimsanchez/agent-mesh` (el estado que describe `ESTADO.md`, 287 pruebas pasando,
17 rutas). No reemplaza a `SPEC.md` v0.1: la extiende. Todo lo que no se menciona
aquí queda como está.

**De dónde sale.** Del primer uso real del servicio: el proyecto `cck`, dos
personas, ~2 días de tráfico, 15 hilos, 2 contratos (export del 2026-08-29). Cada
cambio de abajo cita el defecto observado que lo motiva. No hay cambios
especulativos.

**Principio rector, el mismo del diseño original.** El servicio no razona, pero
pone el dato correcto enfrente del agente en el momento correcto. La producción
demostró que **se cumple lo que tiene artefacto y no se cumple lo que solo está en
prosa**: el `ack` se hizo siempre (hay comando), los acuerdos casi nunca se
escribieron (solo había una instrucción). Estos cambios convierten prosa en
artefacto.

---

## Lo observado, en una tabla

| # | Hecho en producción | Causa raíz en el código actual |
|---|---|---|
| O1 | Pablo acusó 4 mensajes antes de guardar los cuerpos y tuvo que pedir reenvío | El dato nunca se perdió (`ack` vive en `message_deliveries.acked_at`; el cuerpo sigue en `messages` y `GET /threads/{id}` lo devuelve). Lo que se perdió fue **la llave**: `AckOut` no devuelve `thread_id`, y el agente no lo había apuntado. |
| O2 | Los 15 hilos siguen `open`; ninguno se marcó resuelto | `resolved` existe en `THREAD_STATUSES` pero **no tiene escritor**: ni endpoint, ni comando, ni regla automática. Era imposible cerrar un hilo. No fue descuido de los agentes. |
| O3 | Todos los acuerdos reales viven en mensajes, no en documentos (latido, fórmula, troceo, protocolo de apagado); 2 documentos, ambos v1, cero enmiendas | La instrucción "escríbelo" compite con el trabajo y pierde. Nada en el servicio distingue un `agreement` registrado de uno que quedó al aire. |
| O4 | El protocolo de apagado se renegoció 3 veces en 2 días por mensajes | No hay convenciones del proyecto que le lleguen al agente sin que él vaya a buscarlas; la skill le pide leer `00-conventions/` y esa lectura compite con el arranque. |
| O5 | Mensajes enormes multi-tema, escritos "por vuelta de sondeo" cada 15 min | Consecuencia de cadencia manual lenta, no del servicio. Se resuelve en el plugin (monitor), no aquí. |
| O6 | El aviso "ALTO: 1,573 ajustes fabricados" habría llegado 8 h tarde con ventanas de 04:00 | Ídem: con un monitor que sondea cada pocos segundos, cualquier `kind` llega en segundos. **Decisión: no se agrega un kind `alert`.** Ver "Decisiones que este delta NO toma". |
| O7 | `victor.general × 2` y sesiones huérfanas | Ya mitigado el 27-ago (roster antes de rol, latido implícito). Sin cambios adicionales. |

---

## Cambios

En orden de implementación. C1–C4 son **aditivos**: campos nuevos en respuestas
existentes y un endpoint nuevo. Un cliente viejo que ignore campos extra sigue
funcionando sin tocarse — le llegan al agente de Pablo sin que actualice el
plugin. C5 **rompe** y va al final, apagado por defecto.

### C1 — `ack` devuelve la llave del hilo (O1)

`AckOut` pasa de `{id, status, acked}` a:

```json
{
  "id": "msg_…",
  "status": "delivered",
  "acked": true,
  "thread_id": "thr_…",
  "thread_status": "open",
  "subject": "Contrato de /v1/orders: ¿cursor u offset?"
}
```

Racional: el momento del `ack` es exactamente el momento en que el mensaje
desaparece del inbox. Si la respuesta del `ack` trae el `thread_id` y el asunto,
el agente que no apuntó nada conserva la llave para `GET /threads/{id}` en la
misma salida de terminal que acaba de leer. Cero endpoints nuevos: **no se agrega
`GET /messages/{id}`** porque `threads/{id}` ya devuelve el cuerpo completo y con
C1 la llave ya no se pierde.

Implementación: `messaging.ack()` ya devuelve el `Message`; el handler solo tiene
que cargar el `Thread` (un `db.get`) y copiar tres campos.

### C2 — `send` contesta con el estado de la conversación (O2, O3)

`SentOut` pasa de `{id, thread_id, status}` a:

```json
{
  "id": "msg_…",
  "thread_id": "thr_…",
  "status": "pending",
  "thread_status": "open",
  "thread_message_count": 7,
  "hint": "Este acuerdo no está registrado en ningún documento. Si es un acuerdo cerrado, apórtalo a 20-contracts/ citando thr_… en el rationale."
}
```

- `thread_status` y `thread_message_count` siempre.
- `hint` es `null` salvo dos casos:
  1. **`kind == "agreement"`** y ningún `document_versions.rationale` del proyecto
     contiene el `thread_id` del hilo → el texto de arriba. La verificación es un
     `LIKE '%thr_…%'` sobre los rationales del proyecto: barato al volumen real
     (mensajes por hora) y honesto — no adivina si el acuerdo "cuenta", solo
     constata que nadie lo citó al aportar.
  2. **El hilo supera N mensajes sin resolverse** (N=10, configurable
     `THREAD_LONG_HINT_AFTER`) → `"Este hilo lleva 12 mensajes abierto. Si alguno
     de sus temas ya cerró, escríbelo a un documento y marca el hilo con
     resolve."` Ataca directamente el patrón carta de O5: el aviso llega en la
     respuesta del propio send, en el momento exacto.

### C3 — hilos que se pueden cerrar, y verse (O2)

Dos rutas nuevas:

**`POST /threads/{thread_id}/resolve`** → `200 {id, subject, status: "resolved"}`.
- Idempotente. `404` si el hilo no es del proyecto (mismo patrón `_mine`).
- **Reapertura automática:** un `send` a un hilo `resolved` lo regresa a `open`
  en la misma transacción. Así `resolve` nunca estorba: cerrar de más no cuesta
  nada, y no hace falta endpoint de reopen ni permiso de nadie.
- No hay escritor automático de `resolved` (la razón de la nota en `enums.py`
  sigue en pie: un hilo aguanta varias preguntas y cerrarlo con la primera
  respuesta sería mentir). Cierra quien sabe que terminó: el agente.

**`GET /threads?status=open`** → lista de hilos del proyecto de la sesión:

```json
{ "threads": [ { "id": "thr_…", "subject": "…", "status": "open",
                 "message_count": 14, "updated_at": "…" } ] }
```

- `status` opcional (`open | in_progress | resolved`); sin él, todos.
- Lo necesitan: el inbox enriquecido (C4), el comando de apagado del monitor
  (cosecha de acuerdos, ver PLUGIN-REDISEÑO) y el criterio de cierre de canal que
  los agentes de cck inventaron a mano ("bandeja vacía en los dos sentidos" — la
  única condición objetiva que usaron).

`mesh.py` gana dos subcomandos: `resolve --thread <id>` y `threads [--status open]`.

### C4 — `register` e `inbox` traen el contexto que hoy no traen (O4, O2)

**`SessionOut` (respuesta de `register`)** suma dos campos:

```json
{
  "…los cinco campos actuales…": "…",
  "conventions": "…contenido íntegro de 00-conventions/messaging.md, o null si no existe…",
  "open_threads": 3
}
```

Racional: es la conversión de instrucción global en instrucción del proyecto. El
protocolo de apagado que en cck se renegoció tres veces por mensajes (O4) se
escribe **una vez** en `00-conventions/messaging.md` y a partir de ahí se lo
entrega el propio `register` a cada sesión que arranca, de las dos personas, sin
que ningún agente tenga que acordarse de ir a leerlo. Si el documento no existe,
`null` — el servicio no inventa convenciones.

**`InboxOut`** suma un bloque `context`, presente solo cuando la respuesta trae
mensajes (una respuesta vacía de long poll se queda `{"messages": []}`, idéntica
a hoy, para no meter ruido en el bucle del monitor):

```json
{
  "messages": [ "…" ],
  "context": {
    "open_threads": 4,
    "oldest_open": [
      { "id": "thr_…", "subject": "…", "updated_at": "…", "message_count": 14 }
    ]
  }
}
```

- `oldest_open`: hasta 5, ordenados por `updated_at` ascendente.
- Racional: con la lista enfrente, el agente cierra hilos sin que nadie se lo
  pida. Es la tercera inyección acordada, calculada con lo que C3 ya indexa.

### C5 — compuerta dura del `agreement` (O3) — fase 2, apagada por defecto

`SendIn` gana un campo opcional `document_path`. Con la bandera de configuración
`REQUIRE_AGREEMENT_DOC=true` (default **false**):

- `send --kind agreement` **sin** `document_path`, o con una ruta que no existe en
  el proyecto → `422` con detail accionable: `"un agreement debe citar el
  documento donde quedó escrito; apórtalo primero con contribute y reintenta con
  --document-path"`.
- Con la bandera en false, el campo se acepta y se ignora salvo para silenciar el
  `hint` de C2.

Racional del orden: es el mismo patrón que el `409` del reclamo — el servicio
impone lo que la prosa no logró —, pero **rompe clientes viejos** (un agente con
skill vieja recibiría errores que no sabe interpretar). Se enciende solo si,
después de semanas con C1–C4 en producción, los acuerdos siguen quedándose en
los mensajes. Primero se mide si la información basta; la fuerza es el último
recurso.

---

## Decisiones que este delta NO toma, y por qué

- **No hay `kind: alert` ni prioridades.** La urgencia de O6 era un artefacto de
  la cadencia manual de 15 minutos y de las ventanas de apagado. Con el monitor
  del plugin sondeando en bucle (long poll de 30 s + pausa de segundos),
  cualquier mensaje llega en segundos y `notice` basta. Agregar urgencia al
  modelo sería resolver en el servicio un problema que ya no existe en el
  cliente. Si algún día hay agentes que legítimamente no monitorean, se
  reconsidera.
- **No hay `GET /messages/{id}`.** C1 conserva la llave del hilo y
  `threads/{id}` devuelve los cuerpos. Un endpoint por mensaje duplicaría eso.
- **No se toca el modelo de `claim`/`unclaimed`** aunque en cck no se usó (cero
  reclamos): con dos personas y un agente por cabeza no había a quién
  reclamarle. La maquinaria queda para cuando haya más sesiones; no estorba.
- **Telegram u otra notificación a humanos**: fuera del servicio. Si se hace, es
  un consumidor más de la API (un proceso que sondea y notifica), nunca
  transporte entre agentes. Pendiente de decisión de producto, no de este delta.

## Compatibilidad y pruebas

- C1–C4: solo campos nuevos y rutas nuevas. `mesh.py` viejo imprime el JSON tal
  cual, así que los hints **le llegan al agente aunque no actualice** — es la
  propiedad que hace útil inyectar por respuestas.
- Migración de esquema: **ninguna**. Todo se calcula de tablas existentes.
  (`threads` ya tiene `status` y `updated_at`; los conteos son consultas.)
- Pruebas nuevas mínimas:
  - `ack` devuelve `thread_id` y `subject` del mensaje acusado.
  - `send kind=agreement` sin cita en rationales → `hint` no nulo; con una
    contribución cuyo rationale menciona el hilo → `hint` nulo.
  - Hilo con >N mensajes → `hint` de hilo largo.
  - `resolve` idempotente; `send` a hilo `resolved` lo reabre.
  - `GET /threads?status=open` no filtra hilos de otros proyectos (aislamiento,
    regla 2).
  - `register` con y sin `00-conventions/messaging.md`.
  - Inbox vacío **no** trae `context`; inbox con mensajes sí.
  - Con `REQUIRE_AGREEMENT_DOC=true`: 422 sin ruta, 422 con ruta inexistente,
    201 con ruta válida.
- `skill/agent-mesh/` de este repo sigue siendo el test de aceptación: se
  actualiza junto con C3 (dos subcomandos) y se corre el escenario de punta a
  punta antes y después, como el 27 de agosto.
