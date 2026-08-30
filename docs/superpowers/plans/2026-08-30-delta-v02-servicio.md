# SPEC-DELTA v0.2 (servicio) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar los cambios C1–C5 de `SPEC-DELTA.md` sobre el servicio: `ack` devuelve la llave del hilo, `send` devuelve estado y hints, hilos que se cierran y se listan, `register`/`inbox` con contexto, y la compuerta opcional del `agreement`.

**Architecture:** Todos los cambios son campos nuevos en respuestas existentes más dos rutas nuevas (`POST /threads/{id}/resolve`, `GET /threads`). Cero migraciones de esquema: todo se calcula de tablas existentes. La lógica vive en `app/services/` (regla de CLAUDE.md); los handlers solo cargan, llaman y serializan.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x ORM, pytest. Comandos: `uv run pytest -q`, `uv run ruff check . && uv run ruff format --check .`, `uv run mypy`.

**Spec:** `SPEC-DELTA.md` (raíz del repo). Contexto adicional: `SPEC.md` v0.1, `CLAUDE.md`, `ESTADO.md`.

## Global Constraints

- **Nunca SQL específico de SQLite** — todo por el ORM (CLAUDE.md regla 3). `rationale LIKE` se expresa con `.contains()`, jamás con SQL crudo.
- **El proyecto es frontera dura** (regla 2): toda ruta nueva filtra por `project_id` de la sesión y se prueba el aislamiento explícitamente.
- **mypy strict sobre `app/`**, ruff limpio, y `pytest` verde antes de cada commit.
- **Un commit por cambio C1–C5**, con sus pruebas incluidas. Mensajes de commit en español, estilo del historial (`git log --oneline`).
- **Ninguna migración Alembic** — si una tarea parece necesitar una, algo se leyó mal: detente y revisa el delta.
- Los textos de los hints y errores se copian **verbatim** de `SPEC-DELTA.md` (están reproducidos abajo en cada tarea).
- Orden de implementación: C1 → C2 → C3 → C4 → C5 → cliente (`mesh.py` + `api.md`). No saltar.
- Rama sugerida: `delta-v02-servicio` desde `main`; PR único al final.

## Decisiones tomadas al planear (para no reabrirlas a mitad de tarea)

1. **"Hilo abierto" para conteos = `status != "resolved"`** (incluye `in_progress`, que hoy nada escribe pero existe en el enum). `GET /threads?status=X` en cambio filtra por igualdad exacta, porque ahí el agente pide un estado literal.
2. **Prioridad de hints en C2:** si aplican los dos (agreement sin cita **y** hilo largo), gana el del agreement — es el más específico. Hay un solo campo `hint`.
3. **`GET /inbox` se declara con `response_model_exclude_none=True`** para que la respuesta vacía siga siendo `{"messages": []}` sin `"context": null` (lo exige el delta para el bucle del monitor). Efecto colateral aceptado: `in_reply_to`/`to` nulos desaparecen de las respuestas del inbox — `api.md` nunca los mostró en su ejemplo y todos los clientes leen con `.get()`.
4. **C4 `conventions`:** documento existente pero con contenido vacío (versión 0 o texto vacío) → `null`, igual que inexistente. El servicio no entrega convenciones vacías.
5. **`resolve` lo puede llamar cualquier sesión del proyecto** (mismo patrón `_mine`: fuera del proyecto → 404). Reabrir es automático vía `send`, así que cerrar de más no cuesta nada.
6. **`SentOut.thread_message_count` incluye el mensaje recién enviado** (se cuenta tras el `flush`).

---

### Task 1: Incorporar los specs al repo

**Files:**
- Create: `SPEC-DELTA.md` (raíz — ya copiado al planear; verificar)
- Create: `PLUGIN-REDISENO.md` (raíz — ya copiado al planear; verificar)

**Interfaces:** Ninguna — es documentación. Las tareas siguientes citan `SPEC-DELTA.md` por sección.

- [ ] **Step 1: Verificar que ambos archivos están en la raíz**

Run: `ls SPEC-DELTA.md PLUGIN-REDISENO.md`
Expected: ambos listados. Si faltan, están en `/home/proyectos/hdd2/victorm/.claude/uploads/70ea264a-cdbc-4565-8b27-9b954cbc061a/` (`b78ef12d-SPECDELTA.md` y `f2e2c281-PLUGINREDISENO.md`); copiarlos con esos nombres destino.

- [ ] **Step 2: Commit**

```bash
git checkout -b delta-v02-servicio
git add SPEC-DELTA.md PLUGIN-REDISENO.md
git commit -m "Specs v0.2: delta del servicio y rediseño del plugin"
```

---

### Task 2: C1 — `ack` devuelve la llave del hilo

**Files:**
- Modify: `app/api/v1/schemas.py` (clase `AckOut`, líneas 128–131)
- Modify: `app/api/v1/messages.py` (handler `ack`, líneas 141–147)
- Test: `tests/test_api_messages.py` (añadir al final)

**Interfaces:**
- Consumes: `messaging.ack()` ya devuelve el `Message` confirmado (sin cambios).
- Produces: `AckOut` con campos nuevos `thread_id: str`, `thread_status: str`, `subject: str`. El plugin (plan hermano) y `monitor.py` los leen tal cual.

- [ ] **Step 1: Escribir la prueba que falla**

En `tests/test_api_messages.py`, al final (usa las fixtures `client` y `mundo` de `conftest.py`; si el archivo ya define un helper de registro, úsalo en lugar de `_registra`):

```python
def _registra(client, mundo, persona: str, rol: str) -> dict[str, str]:
    """Registra una sesión en proyecto-pablo y devuelve las cabeceras de sesión."""
    respuesta = client.post(
        "/api/v1/sessions",
        json={"project": "proyecto-pablo", "role": rol},
        headers=mundo.auth(persona),
    )
    assert respuesta.status_code == 201
    return mundo.sesion(persona, respuesta.json()["session_key"])


def test_ack_devuelve_la_llave_del_hilo(client, mundo):
    """C1: la respuesta del ack trae thread_id, thread_status y subject (SPEC-DELTA)."""
    victor = _registra(client, mundo, "victor", "db")
    pablo = _registra(client, mundo, "pablo", "general")

    enviado = client.post(
        "/api/v1/messages",
        json={"to": "pablo.general", "subject": "¿cursor u offset?", "body": "…"},
        headers=victor,
    ).json()

    inbox = client.get("/api/v1/inbox", headers=pablo).json()
    msg_id = inbox["messages"][0]["id"]

    salida = client.post(f"/api/v1/messages/{msg_id}/ack", headers=pablo)
    assert salida.status_code == 200
    cuerpo = salida.json()
    assert cuerpo["acked"] is True
    assert cuerpo["thread_id"] == enviado["thread_id"]
    assert cuerpo["thread_status"] == "open"
    assert cuerpo["subject"] == "¿cursor u offset?"
```

- [ ] **Step 2: Verificar que falla**

Run: `uv run pytest tests/test_api_messages.py::test_ack_devuelve_la_llave_del_hilo -q`
Expected: FAIL con `KeyError: 'thread_id'` (la respuesta actual solo trae `id`, `status`, `acked`).

- [ ] **Step 3: Implementar**

En `app/api/v1/schemas.py`, reemplazar `AckOut`:

```python
class AckOut(BaseModel):
    """C1 de SPEC-DELTA: el momento del ack es cuando el mensaje desaparece del
    inbox; la respuesta conserva la llave del hilo para `GET /threads/{id}`."""

    id: str
    status: str
    acked: bool
    thread_id: str
    thread_status: str
    subject: str
```

En `app/api/v1/messages.py`, el handler `ack` (importar `Thread` junto a los modelos ya importados: `from app.db.models import AgentSession, Message, Thread`):

```python
@router.post("/messages/{message_id}/ack", response_model=AckOut)
def ack(db: Db, agent_session: CurrentSession, message_id: str) -> AckOut:
    """Confirma recepción. Sin esto, si la sesión muere el mensaje reaparece.

    Devuelve la llave del hilo (C1): el agente que no apuntó nada conserva
    `thread_id` y asunto en la misma salida que acaba de leer.
    """
    message = messaging.ack(db, agent_session=agent_session, message_id=message_id)
    hilo = db.get(Thread, message.thread_id)
    if hilo is None:  # pragma: no cover - lo impide la FK
        raise NotFoundError(f"no existe el hilo '{message.thread_id}' en este proyecto")
    salida = AckOut(
        id=message.id,
        status=message.status,
        acked=True,
        thread_id=hilo.id,
        thread_status=hilo.status,
        subject=message.subject,
    )
    db.commit()
    return salida
```

(Importar `NotFoundError` desde `app.services.errors` en `messages.py`.)

- [ ] **Step 4: Verificar que pasa, con toda la suite**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy`
Expected: todo verde (287 previas + 1 nueva).

- [ ] **Step 5: Commit**

```bash
git add app/api/v1/schemas.py app/api/v1/messages.py tests/test_api_messages.py
git commit -m "C1: el ack devuelve thread_id, estado del hilo y asunto"
```

---

### Task 3: C2 — `send` contesta con el estado de la conversación

**Files:**
- Modify: `app/config.py` (nuevo setting `thread_long_hint_after`)
- Modify: `app/api/v1/schemas.py` (clase `SentOut`)
- Modify: `app/services/messaging.py` (nuevo dataclass `SendFeedback`, funciones `feedback_for` y `agreement_cited`)
- Modify: `app/api/v1/messages.py` (handler `send`)
- Test: `tests/test_api_messages.py`

**Interfaces:**
- Consumes: `messaging.send()` → `Sent(message, thread)` (sin cambios en esta tarea); `Document`/`DocumentVersion` de `app.db.models`.
- Produces: `messaging.feedback_for(db, settings, *, sent: Sent) -> SendFeedback` con `SendFeedback(thread_status: str, thread_message_count: int, hint: str | None)`; `messaging.agreement_cited(db, *, project_id: str, thread_id: str) -> bool`. La Task 6 (C5) extenderá `feedback_for` con `document_path`.

- [ ] **Step 1: Escribir las pruebas que fallan**

En `tests/test_api_messages.py`:

```python
def test_send_devuelve_estado_del_hilo_y_conteo(client, mundo):
    """C2: SentOut trae thread_status y thread_message_count siempre."""
    victor = _registra(client, mundo, "victor", "db")

    primero = client.post(
        "/api/v1/messages",
        json={"to": "pablo.general", "subject": "tema uno", "body": "…"},
        headers=victor,
    ).json()
    assert primero["thread_status"] == "open"
    assert primero["thread_message_count"] == 1
    assert primero["hint"] is None

    segundo = client.post(
        "/api/v1/messages",
        json={
            "to": "pablo.general",
            "subject": "tema uno",
            "body": "…",
            "thread_id": primero["thread_id"],
        },
        headers=victor,
    ).json()
    assert segundo["thread_message_count"] == 2


def test_agreement_sin_cita_en_rationales_trae_hint(client, mundo):
    """C2 caso 1: agreement cuyo hilo nadie citó al aportar -> hint no nulo."""
    victor = _registra(client, mundo, "victor", "db")

    salida = client.post(
        "/api/v1/messages",
        json={"to": "pablo.general", "kind": "agreement", "subject": "cerramos cursor", "body": "…"},
        headers=victor,
    ).json()
    assert salida["hint"] is not None
    assert salida["thread_id"] in salida["hint"]
    assert "20-contracts/" in salida["hint"]


def test_agreement_ya_citado_no_trae_hint(client, mundo):
    """C2 caso 1, negativo: una contribución cuyo rationale menciona el hilo silencia el hint."""
    victor = _registra(client, mundo, "victor", "db")

    primero = client.post(
        "/api/v1/messages",
        json={"to": "pablo.general", "kind": "agreement", "subject": "cerramos cursor", "body": "…"},
        headers=victor,
    ).json()

    aporte = client.post(
        "/api/v1/docs/contributions",
        json={
            "document_path": "20-contracts/paginacion.md",
            "base_version": 0,
            "intent": "create",
            "content": "Cursor, no offset.",
            "rationale": f"Acordado en {primero['thread_id']}",
        },
        headers=victor,
    )
    assert aporte.status_code == 200

    segundo = client.post(
        "/api/v1/messages",
        json={
            "to": "pablo.general",
            "kind": "agreement",
            "subject": "cerramos cursor",
            "body": "…",
            "thread_id": primero["thread_id"],
        },
        headers=victor,
    ).json()
    assert segundo["hint"] is None


def test_hilo_largo_trae_hint(client, mundo):
    """C2 caso 2: más de THREAD_LONG_HINT_AFTER mensajes sin resolver -> hint de hilo largo."""
    victor = _registra(client, mundo, "victor", "db")

    primero = client.post(
        "/api/v1/messages",
        json={"to": "pablo.general", "subject": "tema eterno", "body": "…"},
        headers=victor,
    ).json()
    ultimo = primero
    for _ in range(10):  # con el default 10, el mensaje 11 supera el umbral
        ultimo = client.post(
            "/api/v1/messages",
            json={
                "to": "pablo.general",
                "subject": "tema eterno",
                "body": "…",
                "thread_id": primero["thread_id"],
            },
            headers=victor,
        ).json()
    assert ultimo["thread_message_count"] == 11
    assert ultimo["hint"] is not None
    assert "resolve" in ultimo["hint"]
```

- [ ] **Step 2: Verificar que fallan**

Run: `uv run pytest tests/test_api_messages.py -q -k "estado_del_hilo or hint"`
Expected: FAIL con `KeyError: 'thread_status'` / `KeyError: 'hint'`.

- [ ] **Step 3: Implementar**

`app/config.py`, junto a `longpoll_max_seconds`:

```python
    # C2 de SPEC-DELTA: a partir de cuántos mensajes un hilo sin resolver
    # provoca el hint de "escríbelo y marca resolve" en la respuesta del send.
    thread_long_hint_after: int = 10
```

`app/api/v1/schemas.py`, reemplazar `SentOut`:

```python
class SentOut(BaseModel):
    """C2 de SPEC-DELTA: el send contesta con el estado de la conversación.

    `hint` es null salvo dos casos: un agreement cuyo hilo nadie citó al aportar,
    o un hilo que superó THREAD_LONG_HINT_AFTER mensajes sin resolverse.
    """

    id: str
    thread_id: str
    status: str
    thread_status: str
    thread_message_count: int
    hint: str | None = None
```

`app/services/messaging.py` — añadir `func` al import de sqlalchemy y `Document, DocumentVersion` al import de modelos; después de la sección "envío":

```python
@dataclass(frozen=True)
class SendFeedback:
    """Lo que el send devuelve sobre la conversación (C2 de SPEC-DELTA)."""

    thread_status: str
    thread_message_count: int
    hint: str | None


def feedback_for(db: Session, settings: Settings, *, sent: Sent) -> SendFeedback:
    """Estado del hilo tras enviar, y el hint que convierte prosa en artefacto.

    Prioridad cuando aplican ambos: gana el del agreement, que es el específico.
    """
    total = int(
        db.scalar(
            select(func.count()).select_from(Message).where(Message.thread_id == sent.thread.id)
        )
        or 0
    )
    hint: str | None = None
    if sent.message.kind == "agreement" and not agreement_cited(
        db, project_id=sent.thread.project_id, thread_id=sent.thread.id
    ):
        hint = (
            f"Este acuerdo no está registrado en ningún documento. Si es un "
            f"acuerdo cerrado, apórtalo a 20-contracts/ citando {sent.thread.id} "
            f"en el rationale."
        )
    elif total > settings.thread_long_hint_after and sent.thread.status != "resolved":
        hint = (
            f"Este hilo lleva {total} mensajes abierto. Si alguno de sus temas ya "
            f"cerró, escríbelo a un documento y marca el hilo con resolve."
        )
    return SendFeedback(thread_status=sent.thread.status, thread_message_count=total, hint=hint)


def agreement_cited(db: Session, *, project_id: str, thread_id: str) -> bool:
    """¿Algún rationale del proyecto menciona este hilo?

    No adivina si el acuerdo "cuenta": solo constata que alguien lo citó al
    aportar. `.contains()` genera el LIKE portable (regla 3: nada específico
    del motor).
    """
    return bool(
        db.scalar(
            select(
                exists().where(
                    DocumentVersion.document_id == Document.id,
                    Document.project_id == project_id,
                    DocumentVersion.rationale.contains(thread_id),
                )
            )
        )
    )
```

`app/api/v1/messages.py`, handler `send` (nota: gana el parámetro `settings: Config`):

```python
@router.post("/messages", response_model=SentOut, status_code=201)
def send(db: Db, agent_session: CurrentSession, settings: Config, body: SendIn) -> SentOut:
    """Envía un mensaje.

    Un `to` que apunta a un rol que nadie ha levantado no falla: el mensaje
    espera. Y un `kind: answer` con `in_reply_to` cierra el mensaje original.
    La respuesta trae el estado de la conversación (C2 de SPEC-DELTA).
    """
    enviado = messaging.send(
        db,
        sender=agent_session,
        to=body.to,
        kind=body.kind,
        subject=body.subject,
        body=body.body,
        in_reply_to=body.in_reply_to,
        thread_id=body.thread_id,
    )
    feedback = messaging.feedback_for(db, settings, sent=enviado)
    salida = SentOut(
        id=enviado.message.id,
        thread_id=enviado.thread.id,
        status=enviado.message.status,
        thread_status=feedback.thread_status,
        thread_message_count=feedback.thread_message_count,
        hint=feedback.hint,
    )
    db.commit()
    return salida
```

- [ ] **Step 4: Verificar**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy`
Expected: verde. Ojo: si alguna prueba existente asertaba la forma exacta de `SentOut` (solo tres llaves), actualizarla — los campos nuevos son aditivos y eso es exactamente lo que promete el delta.

- [ ] **Step 5: Commit**

```bash
git add app/config.py app/api/v1/schemas.py app/services/messaging.py app/api/v1/messages.py tests/test_api_messages.py
git commit -m "C2: el send contesta con estado del hilo, conteo y hints"
```

---

### Task 4: C3 — hilos que se pueden cerrar, y verse

**Files:**
- Modify: `app/services/messaging.py` (funciones `resolve_thread`, `threads_overview`, `oldest_open_threads`, `open_thread_count`; reapertura en `_resolve_thread`)
- Modify: `app/api/v1/schemas.py` (clases `ThreadSummary`, `ThreadsOut`, `ThreadResolvedOut`)
- Modify: `app/api/v1/messages.py` (rutas `GET /threads` y `POST /threads/{id}/resolve`)
- Test: `tests/test_api_threads.py` (nuevo)

**Interfaces:**
- Consumes: `Thread`, `Message` de `app.db.models`; patrón `_mine` (404 fuera del proyecto).
- Produces:
  - `messaging.resolve_thread(db, *, agent_session: AgentSession, thread_id: str) -> Thread` — idempotente, 404 vía `NotFoundError` si el hilo no es del proyecto.
  - `messaging.threads_overview(db, *, project_id: str, status: str | None = None) -> list[tuple[Thread, int]]` — orden `updated_at` descendente; el `int` es el conteo de mensajes.
  - `messaging.oldest_open_threads(db, *, project_id: str, limit: int = 5) -> list[tuple[Thread, int]]` — `status != "resolved"`, `updated_at` ascendente (lo usa C4).
  - `messaging.open_thread_count(db, *, project_id: str) -> int` — `status != "resolved"` (lo usa C4).
  - Rutas: `POST /threads/{thread_id}/resolve` → `{id, subject, status}`; `GET /threads?status=` → `{threads: [{id, subject, status, message_count, updated_at}]}`.

- [ ] **Step 1: Escribir las pruebas que fallan**

Crear `tests/test_api_threads.py`:

```python
"""C3 de SPEC-DELTA: resolver hilos, listarlos, y reapertura automática."""


def _registra(client, mundo, persona: str, rol: str, proyecto: str = "proyecto-pablo") -> dict[str, str]:
    respuesta = client.post(
        "/api/v1/sessions",
        json={"project": proyecto, "role": rol},
        headers=mundo.auth(persona),
    )
    assert respuesta.status_code == 201
    return mundo.sesion(persona, respuesta.json()["session_key"])


def _envia(client, headers, subject: str = "un tema", **extra) -> dict:
    cuerpo = {"to": "pablo.general", "subject": subject, "body": "…", **extra}
    respuesta = client.post("/api/v1/messages", json=cuerpo, headers=headers)
    assert respuesta.status_code == 201
    return respuesta.json()


def test_resolve_cierra_y_es_idempotente(client, mundo):
    victor = _registra(client, mundo, "victor", "db")
    enviado = _envia(client, victor)

    primera = client.post(f"/api/v1/threads/{enviado['thread_id']}/resolve", headers=victor)
    assert primera.status_code == 200
    assert primera.json() == {
        "id": enviado["thread_id"],
        "subject": "un tema",
        "status": "resolved",
    }

    segunda = client.post(f"/api/v1/threads/{enviado['thread_id']}/resolve", headers=victor)
    assert segunda.status_code == 200
    assert segunda.json()["status"] == "resolved"


def test_send_a_hilo_resuelto_lo_reabre(client, mundo):
    victor = _registra(client, mundo, "victor", "db")
    enviado = _envia(client, victor)
    client.post(f"/api/v1/threads/{enviado['thread_id']}/resolve", headers=victor)

    reabierto = _envia(client, victor, thread_id=enviado["thread_id"])
    assert reabierto["thread_status"] == "open"

    hilo = client.get(f"/api/v1/threads/{enviado['thread_id']}", headers=victor).json()
    assert hilo["status"] == "open"


def test_threads_lista_con_conteo_y_filtro(client, mundo):
    victor = _registra(client, mundo, "victor", "db")
    abierto = _envia(client, victor, subject="sigue abierto")
    resuelto = _envia(client, victor, subject="ya cerró")
    client.post(f"/api/v1/threads/{resuelto['thread_id']}/resolve", headers=victor)

    todos = client.get("/api/v1/threads", headers=victor).json()["threads"]
    assert {t["id"] for t in todos} == {abierto["thread_id"], resuelto["thread_id"]}
    assert all({"id", "subject", "status", "message_count", "updated_at"} <= t.keys() for t in todos)

    abiertos = client.get("/api/v1/threads", params={"status": "open"}, headers=victor).json()["threads"]
    assert [t["id"] for t in abiertos] == [abierto["thread_id"]]
    assert abiertos[0]["message_count"] == 1


def test_threads_no_filtra_hilos_de_otros_proyectos(client, mundo):
    """Aislamiento (regla 2): ni listar ni resolver cruza la frontera del proyecto."""
    victor = _registra(client, mundo, "victor", "db")
    luis = _registra(client, mundo, "luis", "general", proyecto="proyecto-luis")

    ajeno = client.post(
        "/api/v1/messages",
        json={"to": "victor.general", "subject": "tema de luis", "body": "…"},
        headers=luis,
    ).json()

    visibles = client.get("/api/v1/threads", headers=victor).json()["threads"]
    assert ajeno["thread_id"] not in {t["id"] for t in visibles}

    intruso = client.post(f"/api/v1/threads/{ajeno['thread_id']}/resolve", headers=victor)
    assert intruso.status_code == 404
```

- [ ] **Step 2: Verificar que fallan**

Run: `uv run pytest tests/test_api_threads.py -q`
Expected: FAIL — `405`/`404` en `resolve` (la ruta no existe) y `GET /threads` devuelve 404 o similar.

- [ ] **Step 3: Implementar**

`app/api/v1/schemas.py`, junto a `ThreadOut`:

```python
class ThreadResolvedOut(BaseModel):
    id: str
    subject: str
    status: str


class ThreadSummary(BaseModel):
    id: str
    subject: str
    status: str
    message_count: int
    updated_at: datetime


class ThreadsOut(BaseModel):
    """Respuesta de `GET /threads` (C3). El criterio objetivo de cierre de canal
    que los agentes inventaron a mano: bandeja vacía en los dos sentidos."""

    threads: list[ThreadSummary]
```

`app/services/messaging.py`, en la sección "hilos":

```python
def resolve_thread(db: Session, *, agent_session: AgentSession, thread_id: str) -> Thread:
    """Marca un hilo como resuelto. Idempotente; 404 fuera del proyecto.

    No hay escritor automático de `resolved` (la nota de enums.py sigue en pie):
    cierra quien sabe que terminó, el agente. Reabrir tampoco necesita permiso:
    un send al hilo resuelto lo regresa a `open` (ver `_resolve_thread`).
    """
    thread = db.get(Thread, thread_id)
    if thread is None or thread.project_id != agent_session.project_id:
        raise NotFoundError(f"no existe el hilo '{thread_id}' en este proyecto")
    if thread.status != "resolved":
        thread.status = "resolved"
        thread.updated_at = utcnow()
        db.flush()
    return thread


def _message_counts() -> Any:
    """Subconsulta de conteo de mensajes por hilo, para las vistas de hilos."""
    return (
        select(Message.thread_id, func.count().label("total"))
        .group_by(Message.thread_id)
        .subquery()
    )


def threads_overview(
    db: Session, *, project_id: str, status: str | None = None
) -> list[tuple[Thread, int]]:
    """Hilos del proyecto con su conteo, los más recientes primero."""
    conteo = _message_counts()
    query = (
        select(Thread, func.coalesce(conteo.c.total, 0))
        .outerjoin(conteo, conteo.c.thread_id == Thread.id)
        .where(Thread.project_id == project_id)
        .order_by(Thread.updated_at.desc(), Thread.id)
    )
    if status is not None:
        query = query.where(Thread.status == status)
    return [(hilo, int(total)) for hilo, total in db.execute(query)]


def oldest_open_threads(
    db: Session, *, project_id: str, limit: int = 5
) -> list[tuple[Thread, int]]:
    """Los hilos sin resolver más viejos. C4 los inyecta en el inbox."""
    conteo = _message_counts()
    query = (
        select(Thread, func.coalesce(conteo.c.total, 0))
        .outerjoin(conteo, conteo.c.thread_id == Thread.id)
        .where(Thread.project_id == project_id, Thread.status != "resolved")
        .order_by(Thread.updated_at.asc(), Thread.id)
        .limit(limit)
    )
    return [(hilo, int(total)) for hilo, total in db.execute(query)]


def open_thread_count(db: Session, *, project_id: str) -> int:
    """Hilos "abiertos" = no resueltos (incluye in_progress)."""
    return int(
        db.scalar(
            select(func.count())
            .select_from(Thread)
            .where(Thread.project_id == project_id, Thread.status != "resolved")
        )
        or 0
    )
```

En `_resolve_thread` (la privada que ya existe, líneas 105–128), reabrir al tocar un hilo resuelto — tras cada rama que devuelve un hilo existente:

```python
def _resolve_thread(
    db: Session,
    *,
    project_id: str,
    subject: str,
    thread_id: str | None,
    in_reply_to: Message | None,
) -> Thread:
    """`thread_id` explícito -> heredado de `in_reply_to` -> hilo nuevo (api.md).

    Un send a un hilo `resolved` lo reabre en la misma transacción (C3): así
    resolver nunca estorba y no hace falta endpoint de reopen.
    """
    thread: Thread | None = None
    if thread_id is not None:
        thread = db.get(Thread, thread_id)
        if thread is None or thread.project_id != project_id:
            raise NotFoundError(f"no existe el hilo '{thread_id}' en este proyecto")
    elif in_reply_to is not None:
        thread = db.get(Thread, in_reply_to.thread_id)
    if thread is not None:
        if thread.status == "resolved":
            thread.status = "open"
        return thread
    thread = Thread(project_id=project_id, subject=subject)
    db.add(thread)
    db.flush()
    return thread
```

(Nota: la semántica de "mismo mensaje exista o no en otro proyecto" del comentario original se conserva — el 404 no distingue.)

`app/api/v1/messages.py` — importar `Query` ya está; añadir `ThreadResolvedOut, ThreadsOut, ThreadSummary` al import de schemas y `ThreadStatus` de `app.db.enums`:

```python
@router.get("/threads", response_model=ThreadsOut)
def threads(
    db: Db,
    agent_session: CurrentSession,
    status: ThreadStatus | None = Query(default=None),
) -> ThreadsOut:
    """Hilos del proyecto de la sesión, con conteo de mensajes (C3)."""
    filas = messaging.threads_overview(
        db, project_id=agent_session.project_id, status=status
    )
    return ThreadsOut(
        threads=[
            ThreadSummary(
                id=hilo.id,
                subject=hilo.subject,
                status=hilo.status,
                message_count=total,
                updated_at=hilo.updated_at,
            )
            for hilo, total in filas
        ]
    )


@router.post("/threads/{thread_id}/resolve", response_model=ThreadResolvedOut)
def resolve(db: Db, agent_session: CurrentSession, thread_id: str) -> ThreadResolvedOut:
    """Cierra un hilo. Idempotente; un send posterior lo reabre solo (C3)."""
    hilo = messaging.resolve_thread(db, agent_session=agent_session, thread_id=thread_id)
    salida = ThreadResolvedOut(id=hilo.id, subject=hilo.subject, status=hilo.status)
    db.commit()
    return salida
```

- [ ] **Step 4: Verificar**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy`
Expected: verde. Cuenta de rutas pasa de 17 a 19; si `tests/test_despliegue.py` u otra prueba fija ese número, actualizarla con el motivo en el assert.

- [ ] **Step 5: Commit**

```bash
git add app/services/messaging.py app/api/v1/schemas.py app/api/v1/messages.py tests/test_api_threads.py
git commit -m "C3: resolve idempotente, reapertura al escribir y listado de hilos"
```

---

### Task 5: C4 — `register` e `inbox` traen el contexto que hoy no traen

**Files:**
- Modify: `app/services/knowledge.py` (constante `CONVENTIONS_PATH`, función `content_if_exists`)
- Modify: `app/api/v1/schemas.py` (`SessionOut` + clases `OpenThreadRef`, `InboxContext`; campo `context` en `InboxOut`)
- Modify: `app/api/v1/sessions.py` (handler `register`)
- Modify: `app/api/v1/messages.py` (`_poll_once` y handler `inbox`)
- Test: `tests/test_api_sessions.py` y `tests/test_api_messages.py`

**Interfaces:**
- Consumes: `messaging.open_thread_count` y `messaging.oldest_open_threads` (Task 4); `knowledge.current_content` (existente).
- Produces: `knowledge.content_if_exists(db, *, project_id: str, path: str) -> str | None`; `knowledge.CONVENTIONS_PATH = "00-conventions/messaging.md"`; `SessionOut.conventions: str | None`, `SessionOut.open_threads: int`; `InboxOut.context: InboxContext | None`.

- [ ] **Step 1: Escribir las pruebas que fallan**

En `tests/test_api_sessions.py`:

```python
def test_register_sin_convenciones_devuelve_null(client, mundo):
    """C4: si 00-conventions/messaging.md no existe, conventions es null."""
    salida = client.post(
        "/api/v1/sessions",
        json={"project": "proyecto-pablo", "role": "db"},
        headers=mundo.auth("victor"),
    )
    assert salida.status_code == 201
    cuerpo = salida.json()
    assert cuerpo["conventions"] is None
    assert cuerpo["open_threads"] == 0


def test_register_entrega_las_convenciones_del_proyecto(client, mundo):
    """C4: el register entrega 00-conventions/messaging.md íntegro."""
    primera = client.post(
        "/api/v1/sessions",
        json={"project": "proyecto-pablo", "role": "db"},
        headers=mundo.auth("victor"),
    ).json()
    sesion = mundo.sesion("victor", primera["session_key"])

    client.post(
        "/api/v1/docs/contributions",
        json={
            "document_path": "00-conventions/messaging.md",
            "base_version": 0,
            "intent": "create",
            "content": "# Mensajería\nUn tema por mensaje.",
            "rationale": "convenciones iniciales",
        },
        headers=sesion,
    )
    client.post(
        "/api/v1/messages",
        json={"to": "pablo.general", "subject": "hilo abierto", "body": "…"},
        headers=sesion,
    )

    segunda = client.post(
        "/api/v1/sessions",
        json={"project": "proyecto-pablo", "role": "backend"},
        headers=mundo.auth("victor"),
    ).json()
    assert "Un tema por mensaje" in segunda["conventions"]
    assert segunda["open_threads"] == 1
```

En `tests/test_api_messages.py`:

```python
def test_inbox_vacio_no_trae_context(client, mundo):
    """C4: la respuesta vacía del long poll queda idéntica a hoy."""
    victor = _registra(client, mundo, "victor", "db")
    cuerpo = client.get("/api/v1/inbox", headers=victor).json()
    assert cuerpo == {"messages": []}


def test_inbox_con_mensajes_trae_context(client, mundo):
    """C4: con mensajes llega el bloque context con los hilos abiertos más viejos."""
    victor = _registra(client, mundo, "victor", "db")
    pablo = _registra(client, mundo, "pablo", "general")

    enviado = client.post(
        "/api/v1/messages",
        json={"to": "pablo.general", "subject": "¿cursor u offset?", "body": "…"},
        headers=victor,
    ).json()

    cuerpo = client.get("/api/v1/inbox", headers=pablo).json()
    assert cuerpo["messages"]
    contexto = cuerpo["context"]
    assert contexto["open_threads"] == 1
    assert contexto["oldest_open"][0]["id"] == enviado["thread_id"]
    assert contexto["oldest_open"][0]["message_count"] == 1
```

- [ ] **Step 2: Verificar que fallan**

Run: `uv run pytest tests/test_api_sessions.py tests/test_api_messages.py -q -k "convenciones or context or conventions"`
Expected: FAIL con `KeyError: 'conventions'` / `KeyError: 'context'`.

- [ ] **Step 3: Implementar**

`app/services/knowledge.py`, junto a `OBSOLETE_HEADING`:

```python
# C4 de SPEC-DELTA: el register entrega este documento a cada sesión que
# arranca. Es la conversión de instrucción global en instrucción del proyecto.
CONVENTIONS_PATH = "00-conventions/messaging.md"
```

y en la sección de lectura:

```python
def content_if_exists(db: Session, *, project_id: str, path: str) -> str | None:
    """Contenido vigente de un documento, o None si no existe o está vacío.

    El servicio no inventa convenciones: documento ausente y documento vacío
    dan lo mismo, null.
    """
    document = db.scalar(
        select(Document).where(Document.project_id == project_id, Document.path == path.strip())
    )
    if document is None:
        return None
    return current_content(db, document) or None
```

`app/api/v1/schemas.py` — `SessionOut` gana dos campos al final:

```python
    conventions: str | None = Field(
        default=None,
        description="Contenido íntegro de 00-conventions/messaging.md, o null si "
        "no existe. Léelas y cúmplelas: son las reglas de este proyecto.",
    )
    open_threads: int = 0
```

y junto a `InboxOut`:

```python
class OpenThreadRef(BaseModel):
    id: str
    subject: str
    updated_at: datetime
    message_count: int


class InboxContext(BaseModel):
    """Solo presente cuando la respuesta trae mensajes: una respuesta vacía de
    long poll se queda `{"messages": []}` para no meter ruido en el monitor."""

    open_threads: int
    oldest_open: list[OpenThreadRef]
```

`InboxOut` gana el campo:

```python
    context: InboxContext | None = None
```

`app/api/v1/sessions.py`, handler `register` — importar `knowledge` junto a `messaging, sessions`:

```python
    conventions = knowledge.content_if_exists(
        db, project_id=agent_session.project_id, path=knowledge.CONVENTIONS_PATH
    )
    abiertos = messaging.open_thread_count(db, project_id=agent_session.project_id)
    db.commit()
    return SessionOut(
        session_key=agent_session.session_key,
        address=address,
        session_address=session_address,
        project=body.project.strip().lower(),
        registered_at=agent_session.registered_at,
        conventions=conventions,
        open_threads=abiertos,
    )
```

`app/api/v1/messages.py` — `_poll_once` pasa a devolver tupla e importa `InboxContext, OpenThreadRef` de schemas:

```python
def _poll_once(
    session_key: str, settings: Settings
) -> tuple[list[MessageOut], InboxContext | None]:
    """Una pasada del inbox, con su propia sesión de base de datos.

    (docstring existente sin cambios)

    El contexto (C4) solo se calcula cuando hay mensajes: la respuesta vacía
    del long poll debe quedar idéntica a la de siempre.
    """
    with SessionLocal() as db:
        agent_session = db.scalar(
            select(AgentSession).where(AgentSession.session_key == session_key)
        )
        if agent_session is None or agent_session.status != "active":
            return [], None

        messaging.refresh(db, settings, project_id=agent_session.project_id)
        mailbox, precise = messaging.addresses_of(db, agent_session)
        mensajes = messaging.collect_inbox(
            db, agent_session=agent_session, mailbox=mailbox, precise=precise
        )
        salida = [_to_out(m) for m in mensajes]
        contexto: InboxContext | None = None
        if salida:
            contexto = InboxContext(
                open_threads=messaging.open_thread_count(
                    db, project_id=agent_session.project_id
                ),
                oldest_open=[
                    OpenThreadRef(
                        id=hilo.id,
                        subject=hilo.subject,
                        updated_at=hilo.updated_at,
                        message_count=total,
                    )
                    for hilo, total in messaging.oldest_open_threads(
                        db, project_id=agent_session.project_id, limit=5
                    )
                ],
            )
        db.commit()
        return salida, contexto
```

Handler `inbox` — la ruta gana `response_model_exclude_none=True` (decisión 3 de la cabecera del plan) y desempaqueta la tupla:

```python
@router.get("/inbox", response_model=InboxOut, response_model_exclude_none=True)
async def inbox(
    agent_session: CurrentSession,
    settings: Config,
    wait: int = Query(default=0, ge=0, description="Segundos de espera máxima."),
) -> InboxOut:
    """(docstring existente sin cambios)"""
    session_key = agent_session.session_key
    espera = min(wait, settings.longpoll_max_seconds)

    mensajes, contexto = await run_in_threadpool(_poll_once, session_key, settings)
    if mensajes or espera <= 0:
        return InboxOut(messages=mensajes, context=contexto)

    limite = asyncio.get_running_loop().time() + espera
    while asyncio.get_running_loop().time() < limite:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        mensajes, contexto = await run_in_threadpool(_poll_once, session_key, settings)
        if mensajes:
            break
    return InboxOut(messages=mensajes, context=contexto)
```

- [ ] **Step 4: Verificar**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy`
Expected: verde. Atención a pruebas existentes del inbox que aserten la forma exacta de `MessageOut` con `to`/`in_reply_to` nulos: con `exclude_none` esos campos desaparecen de la respuesta — ajustar esas pruebas usando `.get()` o comparando subconjuntos, y dejar en el assert el porqué (decisión 3 del plan).

- [ ] **Step 5: Commit**

```bash
git add app/services/knowledge.py app/api/v1/schemas.py app/api/v1/sessions.py app/api/v1/messages.py tests/test_api_sessions.py tests/test_api_messages.py
git commit -m "C4: register entrega convenciones e inbox trae contexto de hilos"
```

---

### Task 6: C5 — compuerta dura del `agreement` (apagada por defecto)

**Files:**
- Modify: `app/config.py` (setting `require_agreement_doc`)
- Modify: `app/api/v1/schemas.py` (`SendIn.document_path`)
- Modify: `app/services/messaging.py` (`send` gana `document_path` y `require_document`; `feedback_for` gana `document_path`; helper `_document_exists`)
- Modify: `app/api/v1/messages.py` (handler `send` pasa los nuevos argumentos)
- Test: `tests/test_api_messages.py`

**Interfaces:**
- Consumes: `Document` (ya importado en Task 3), `ValidationFailedError` (422).
- Produces: firma final `messaging.send(db, *, sender, to, kind, subject, body, in_reply_to=None, thread_id=None, document_path=None, require_document=False) -> Sent` y `messaging.feedback_for(db, settings, *, sent, document_path=None) -> SendFeedback`. El plugin añade `--document-path` a `mesh.py send` (Task 7).

- [ ] **Step 1: Escribir las pruebas que fallan**

En `tests/test_api_messages.py`:

```python
import pytest


@pytest.fixture
def compuerta_agreement(monkeypatch):
    """Enciende REQUIRE_AGREEMENT_DOC solo durante la prueba."""
    from app.config import get_settings

    monkeypatch.setenv("REQUIRE_AGREEMENT_DOC", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_document_path_silencia_el_hint_con_compuerta_apagada(client, mundo):
    """C5 con la bandera en false: el campo se acepta y solo silencia el hint de C2."""
    victor = _registra(client, mundo, "victor", "db")
    salida = client.post(
        "/api/v1/messages",
        json={
            "to": "pablo.general",
            "kind": "agreement",
            "subject": "cerramos cursor",
            "body": "…",
            "document_path": "20-contracts/paginacion.md",
        },
        headers=victor,
    )
    assert salida.status_code == 201
    assert salida.json()["hint"] is None


def test_agreement_sin_ruta_es_422_con_compuerta_encendida(client, mundo, compuerta_agreement):
    victor = _registra(client, mundo, "victor", "db")
    salida = client.post(
        "/api/v1/messages",
        json={"to": "pablo.general", "kind": "agreement", "subject": "cerramos", "body": "…"},
        headers=victor,
    )
    assert salida.status_code == 422
    assert "--document-path" in salida.json()["detail"]


def test_agreement_con_ruta_inexistente_es_422_con_compuerta_encendida(client, mundo, compuerta_agreement):
    victor = _registra(client, mundo, "victor", "db")
    salida = client.post(
        "/api/v1/messages",
        json={
            "to": "pablo.general",
            "kind": "agreement",
            "subject": "cerramos",
            "body": "…",
            "document_path": "20-contracts/no-existe.md",
        },
        headers=victor,
    )
    assert salida.status_code == 422


def test_agreement_con_ruta_valida_pasa_con_compuerta_encendida(client, mundo, compuerta_agreement):
    victor = _registra(client, mundo, "victor", "db")
    client.post(
        "/api/v1/docs/contributions",
        json={
            "document_path": "20-contracts/paginacion.md",
            "base_version": 0,
            "intent": "create",
            "content": "Cursor.",
            "rationale": "acuerdo",
        },
        headers=victor,
    )
    salida = client.post(
        "/api/v1/messages",
        json={
            "to": "pablo.general",
            "kind": "agreement",
            "subject": "cerramos",
            "body": "…",
            "document_path": "20-contracts/paginacion.md",
        },
        headers=victor,
    )
    assert salida.status_code == 201
```

Nota: si el `client` de `conftest.py` no relee settings por petición (el handler recibe `Config` vía `Depends(get_settings)`, así que sí las relee tras `cache_clear`), y la prueba fallara por settings cacheadas, el patrón correcto es el que ya use `tests/test_config.py` — imitarlo.

- [ ] **Step 2: Verificar que fallan**

Run: `uv run pytest tests/test_api_messages.py -q -k compuerta`
Expected: FAIL — hoy `document_path` se rechaza o ignora y no hay 422.

- [ ] **Step 3: Implementar**

`app/config.py`:

```python
    # C5 de SPEC-DELTA, fase 2, apagada por defecto: exigir que todo agreement
    # cite el documento donde quedó escrito. Se enciende solo si, con C1-C4 en
    # producción, los acuerdos siguen quedándose en los mensajes.
    require_agreement_doc: bool = False
```

`app/api/v1/schemas.py`, `SendIn` gana al final:

```python
    document_path: str | None = Field(
        default=None,
        description="Ruta del documento donde quedó escrito el acuerdo. Con "
        "REQUIRE_AGREEMENT_DOC activo es obligatoria para kind=agreement; "
        "apagada, solo silencia el hint.",
    )
```

`app/services/messaging.py` — `send` gana dos parámetros y la validación (tras validar la forma de la dirección):

```python
def send(
    db: Session,
    *,
    sender: AgentSession,
    to: str | None,
    kind: str,
    subject: str,
    body: str,
    in_reply_to: str | None = None,
    thread_id: str | None = None,
    document_path: str | None = None,
    require_document: bool = False,
) -> Sent:
```

```python
    if kind == "agreement" and require_document:
        if document_path is None or not _document_exists(
            db, project_id=sender.project_id, path=document_path
        ):
            raise ValidationFailedError(
                "un agreement debe citar el documento donde quedó escrito; "
                "apórtalo primero con contribute y reintenta con --document-path"
            )
```

y el helper:

```python
def _document_exists(db: Session, *, project_id: str, path: str) -> bool:
    return bool(
        db.scalar(
            select(
                exists().where(
                    Document.project_id == project_id, Document.path == path.strip()
                )
            )
        )
    )
```

`feedback_for` gana `document_path` (silencia el hint del agreement, C5):

```python
def feedback_for(
    db: Session, settings: Settings, *, sent: Sent, document_path: str | None = None
) -> SendFeedback:
```

y la condición del hint del agreement pasa a:

```python
    if (
        sent.message.kind == "agreement"
        and document_path is None
        and not agreement_cited(
            db, project_id=sent.thread.project_id, thread_id=sent.thread.id
        )
    ):
```

`app/api/v1/messages.py`, handler `send`, pasa los argumentos:

```python
    enviado = messaging.send(
        db,
        sender=agent_session,
        to=body.to,
        kind=body.kind,
        subject=body.subject,
        body=body.body,
        in_reply_to=body.in_reply_to,
        thread_id=body.thread_id,
        document_path=body.document_path,
        require_document=settings.require_agreement_doc,
    )
    feedback = messaging.feedback_for(
        db, settings, sent=enviado, document_path=body.document_path
    )
```

- [ ] **Step 4: Verificar**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy`
Expected: verde.

- [ ] **Step 5: Commit**

```bash
git add app/config.py app/api/v1/schemas.py app/services/messaging.py app/api/v1/messages.py tests/test_api_messages.py
git commit -m "C5: compuerta REQUIRE_AGREEMENT_DOC, apagada por defecto"
```

---

### Task 7: Cliente — `mesh.py` gana `resolve` y `threads`; `api.md` documenta v0.2

**Files:**
- Modify: `skill/agent-mesh/scripts/mesh.py`
- Modify: `skill/agent-mesh/references/api.md`

**Interfaces:**
- Consumes: rutas de Tasks 4–6.
- Produces: subcomandos `mesh.py resolve --thread <id>`, `mesh.py threads [--status open|in_progress|resolved]`, y `mesh.py send --document-path <ruta>`. El plan del plugin (que renombra `skill/` → `plugin/`) corre DESPUÉS de este; aquí se edita en la ruta actual.

- [ ] **Step 1: Añadir los comandos a `mesh.py`**

Junto a `cmd_thread`:

```python
def cmd_threads(a):
    """Hilos del proyecto de la sesión, con conteo. --status filtra."""
    emit(request("GET", "/threads", params={"status": a.status}))


def cmd_resolve(a):
    """Marca un hilo como resuelto. Un send posterior lo reabre solo."""
    emit(request("POST", f"/threads/{a.thread}/resolve"))
```

En `build_parser()`, tras el bloque de `roster`:

```python
    t = sub.add_parser("threads", help="Hilos del proyecto, con estado y conteo")
    t.add_argument("--status", choices=["open", "in_progress", "resolved"])
    t.set_defaults(func=cmd_threads)

    rs = sub.add_parser("resolve", help="Marca un hilo como resuelto")
    rs.add_argument("--thread", required=True)
    rs.set_defaults(func=cmd_resolve)
```

En el parser de `send`, junto a `--thread`:

```python
    s.add_argument("--document-path",
                   help="Documento donde quedó escrito el acuerdo (kind=agreement)")
```

y en `cmd_send`, la clave en el cuerpo:

```python
        "document_path": a.document_path,
```

- [ ] **Step 2: Prueba de humo del cliente**

Run: `python skill/agent-mesh/scripts/mesh.py threads --help && python skill/agent-mesh/scripts/mesh.py resolve --help && python skill/agent-mesh/scripts/mesh.py send --help | grep document-path`
Expected: los tres imprimen ayuda sin traceback.

- [ ] **Step 3: Actualizar `references/api.md`**

1. En la respuesta de `POST /sessions`, añadir a la salida JSON: `"conventions": "…contenido de 00-conventions/messaging.md, o null…", "open_threads": 3` con una línea: *"Si `conventions` no es null, léelas ahí mismo y cúmplelas: son las reglas de mensajería del proyecto."*
2. En `POST /messages`: la respuesta pasa a `{ "id", "thread_id", "status", "thread_status", "thread_message_count", "hint" }` con la explicación de los dos casos de `hint`, y el campo de entrada opcional `document_path` (obligatorio para `kind=agreement` solo si el servidor tiene `REQUIRE_AGREEMENT_DOC`; entonces el error es `422` accionable).
3. En `POST /messages/{id}/ack`: la respuesta trae `thread_id`, `thread_status` y `subject` — *"es tu última oportunidad de apuntar la llave del hilo"*.
4. En `GET /inbox`: documentar el bloque `context` (solo con mensajes) con `open_threads` y `oldest_open` (hasta 5, más viejos primero).
5. Sección nueva tras `GET /threads/{id}`:

```markdown
### `GET /threads?status=open`
Hilos del proyecto de la sesión, los más recientes primero.
`status` opcional ∈ `open | in_progress | resolved`; sin él, todos.

​```json
{ "threads": [ { "id": "thr_…", "subject": "…", "status": "open",
                 "message_count": 14, "updated_at": "…" } ] }
​```

### `POST /threads/{id}/resolve`
Marca el hilo como resuelto. Idempotente; `404` si el hilo no es de tu proyecto.
Un `send` posterior al hilo lo **reabre automáticamente**: cerrar de más no
cuesta nada. Cierra cuando el hilo de verdad terminó — y si terminó en un
acuerdo, escríbelo antes con `contribute` citando el hilo en el rationale.
```

(Quitar los `​` de escape al pegar — están solo para que este plan no rompa su propio bloque de código.)

- [ ] **Step 4: Verificar y commit**

Run: `uv run pytest -q && uv run ruff check .`
Expected: verde (mesh.py está fuera de mypy strict, pero ruff sí lo revisa).

```bash
git add skill/agent-mesh/scripts/mesh.py skill/agent-mesh/references/api.md
git commit -m "Cliente v0.2: threads, resolve y document-path; api.md al día"
```

---

### Task 8: ESTADO.md y PR

**Files:**
- Modify: `ESTADO.md`

- [ ] **Step 1: Actualizar `ESTADO.md`**

- Cambiar «Última actualización» a la fecha del día y añadir sección bajo «Dónde está el proyecto»: los cambios C1–C5 de `SPEC-DELTA.md` implementados, rutas de API 17 → 19, cero migraciones, `REQUIRE_AGREEMENT_DOC` apagada por defecto, y las variables nuevas (`THREAD_LONG_HINT_AFTER=10`, `REQUIRE_AGREEMENT_DOC=false`).
- Registrar la decisión «hilo abierto = no resuelto» y la de `response_model_exclude_none` en el inbox (decisiones 1 y 3 de este plan) en la sección de decisiones.

- [ ] **Step 2: Verificación completa final**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: todo verde. Conteo esperado: 287 previas + ~15 nuevas.

- [ ] **Step 3: Commit y PR**

```bash
git add ESTADO.md
git commit -m "ESTADO: delta v0.2 del servicio implementado"
git push -u origin delta-v02-servicio
gh pr create --title "SPEC-DELTA v0.2: C1-C5 del servicio" --body "..."
```

El cuerpo del PR enumera C1–C5 con una línea cada uno y cita `SPEC-DELTA.md`.

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** C1 → Task 2; C2 → Task 3; C3 → Task 4; C4 → Task 5; C5 → Task 6; `mesh.py resolve/threads` y compat de `api.md` → Task 7; «pruebas nuevas mínimas» del delta → repartidas en Tasks 2–6 (las nueve están). «Migración: ninguna» → constraint global.
- **Sin placeholders:** cada paso trae código o texto concreto.
- **Consistencia de tipos:** `feedback_for` se define en Task 3 sin `document_path` y Task 6 muestra la firma final completa; `oldest_open_threads`/`open_thread_count` se definen en Task 4 y se consumen en Task 5 con esas firmas exactas.
