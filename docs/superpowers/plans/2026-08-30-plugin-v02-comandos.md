# Plugin agent-mesh v0.2 (comandos + monitor) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sustituir la skill única por el plugin v0.2: cuatro comandos slash (`setup`, `register`, `monitor`, `stop`), un monitor que es un proceso del SO sin LLM, y una `SKILL.md` recortada a solo el juicio en vuelo.

**Architecture:** `skill/` se renombra a `plugin/` y adopta la estructura de plugin de Claude Code (`.claude-plugin/plugin.json`, `commands/`, `skills/agent-mesh/`, `scripts/`). Los comandos son markdown que invoca la persona; `monitor.py` es un bucle tonto de librería estándar que persiste → registra → acusa, en ese orden sagrado. La skill conserva únicamente lo que decide el modelo.

**Tech Stack:** Markdown de comandos de plugin de Claude Code, Python 3.12 solo-stdlib para `scripts/`, pytest para las pruebas unitarias de `monitor.py`.

**Spec:** `PLUGIN-REDISENO.md` (raíz del repo). Contexto: `SPEC-DELTA.md` (C3/C4 ya implementados por el plan hermano `2026-08-30-delta-v02-servicio.md`, que corre PRIMERO), `ESTADO.md`.

## Global Constraints

- **Prerequisito duro:** el plan del servicio (`delta-v02-servicio`) está mergeado. Los comandos deben funcionar también contra un servidor viejo (los pasos `[DELTA:Cn]` degradan con elegancia), pero `monitor.py` y `stop` aprovechan C3/C4 cuando existen.
- **El monitor nunca envía mensajes, nunca reclama, nunca descarta, nunca se re-registra.** Solo lee, persiste, acusa.
- **Orden sagrado al recibir: persistir a disco → línea de log → solo entonces `ack`.** Es la lección del incidente O1. Cualquier refactor que invierta ese orden es un bug, no un estilo.
- **El token jamás se imprime, se pide por chat, ni se escribe a archivo** — regla repetida en `setup` y en la skill.
- Los comandos referencian los scripts con `${CLAUDE_PLUGIN_ROOT}/scripts/…`.
- Cadencia del sondeo: **la fija el diseño** (long poll 30 s + pausa 5 s). No se pregunta, no se negocia.
- `ruff check .` cubre `plugin/scripts/*.py`; mypy strict solo aplica a `app/` (sin cambios).
- Un commit por tarea, mensajes en español, estilo del historial.
- Rama sugerida: `plugin-v02-comandos` desde `main` (ya con el delta mergeado).

## Decisiones tomadas al planear

1. **`skill/` → `plugin/` con `git mv`** para conservar historial. `ESTADO.md` y `README.md` se actualizan donde citen `skill/`.
2. **Los scripts viven en `plugin/scripts/`** (raíz del plugin), como pide la estructura del rediseño; la skill los referencia vía `${CLAUDE_PLUGIN_ROOT}` con nota de ruta relativa por si el runtime no expande la variable en skills.
3. **La línea `ABANDONO` necesita un "último asunto pendiente"**; el monitor no envía mensajes, así que lo obtiene de `GET /threads?status=open` (C3), tomando el hilo más recientemente actualizado. Si el endpoint no existe (servidor viejo), cae a `"(desconocido: el servidor no expone hilos)"`.
4. **`monitor.py` escribe su propio `monitor.pid`** al arrancar y lo borra al salir; el comando `monitor` no lo redacta a mano.
5. **Un `monitor.stop` huérfano de una corrida anterior se borra al arrancar** el monitor; si no, el proceso nuevo moriría al primer ciclo.
6. **Escritura atómica del inbox:** cada mensaje se escribe a `*.json.tmp` y se renombra — un lector (el agente en pausa natural) nunca ve un archivo a medias.
7. **`stop` reporta la causa de salida leyendo la última línea de `monitor.log`** (`STOP:`/`ABANDONO:`/`TOPE:`/`SESION CADUCA:`), porque el código de salida de un proceso `nohup` ajeno no es recuperable desde otra shell.

---

### Task 1: Reestructura `skill/` → `plugin/` con manifiesto 0.2.0

**Files:**
- Rename: `skill/agent-mesh/` → `plugin/skills/agent-mesh/` (menos `scripts/`, que sube a `plugin/scripts/`)
- Create: `plugin/.claude-plugin/plugin.json`

**Interfaces:**
- Produces: la estructura que consumen las Tasks 2–5:
  ```
  plugin/
  ├── .claude-plugin/plugin.json
  ├── commands/                    (vacía hasta Task 2)
  ├── skills/agent-mesh/SKILL.md   (aún la v0.1; Task 5 la recorta)
  ├── skills/agent-mesh/references/api.md
  └── scripts/mesh.py              (monitor.py llega en Task 3)
  ```

- [ ] **Step 1: Mover con git**

```bash
git checkout -b plugin-v02-comandos
mkdir -p plugin/skills
git mv skill/agent-mesh plugin/skills/agent-mesh
git mv plugin/skills/agent-mesh/scripts plugin/scripts
rmdir skill
mkdir -p plugin/commands plugin/.claude-plugin
```

- [ ] **Step 2: Crear `plugin/.claude-plugin/plugin.json`**

```json
{
  "name": "agent-mesh",
  "version": "0.2.0",
  "description": "Mensajería asíncrona y conocimiento compartido entre agentes de personas distintas que trabajan el mismo proyecto."
}
```

- [ ] **Step 3: Corregir las rutas que quedaron rotas**

En `plugin/skills/agent-mesh/SKILL.md`, todas las apariciones de `python scripts/mesh.py` pasan a `python "${CLAUDE_PLUGIN_ROOT}/scripts/mesh.py"` (la Task 5 reescribe el archivo entero; este paso solo evita dejar la rama rota entre commits).

- [ ] **Step 4: Verificar**

Run: `ls plugin/.claude-plugin/plugin.json plugin/commands plugin/skills/agent-mesh/SKILL.md plugin/skills/agent-mesh/references/api.md plugin/scripts/mesh.py && uv run pytest -q`
Expected: todo listado; suite verde (nada del servicio cambió).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Plugin 0.2.0: estructura commands/skills/scripts en plugin/"
```

---

### Task 2: Comandos `setup` y `register`

**Files:**
- Create: `plugin/commands/setup.md`
- Create: `plugin/commands/register.md`

**Interfaces:**
- Consumes: `mesh.py projects/roster/register/heartbeat/docs/doc` (existentes) y los campos C4 (`conventions`, `open_threads`) de la respuesta de register.
- Produces: los verbos `/agent-mesh:setup` y `/agent-mesh:register` que `monitor.md`, `stop.md` y la skill citan por nombre.

- [ ] **Step 1: Escribir `plugin/commands/setup.md`**

Contenido íntegro:

````markdown
---
description: Configura el acceso al mesh en esta máquina (una vez por persona y máquina). Idempotente.
---

# Configurar el equipo

Verifica que `MESH_URL` y `MESH_TOKEN` estén instalados en el entorno. Pasa una
vez en la vida por persona y máquina; si ya está configurado, dilo y termina.

## Reglas duras, sin excepción

- **Nunca pidas el token por el chat.** Queda en historial y transcripciones.
- **Nunca lo leas ni lo escribas en un archivo** (ni `.env`, ni `.agent-mesh/`).
- **Nunca imprimas el valor del token**, ni siquiera parcialmente.
- No inventes valores ni busques el token en el repo.

## Pasos

1. Comprueba si `MESH_URL` y `MESH_TOKEN` existen en el entorno (`test -n`),
   sin imprimir sus valores.

2. Si **ambos** existen, corre:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/scripts/mesh.py" projects
   ```
   - Si responde `200`: reporta en una línea — "El equipo ya está configurado.
     Persona: `<person>`, proyectos: `<slugs>`." — y **termina**. Este es el
     camino del 99% de las invocaciones.
   - Si responde `401`: el token fue revocado o está mal instalado. Dile a tu
     persona que genere uno nuevo en el panel del mesh y lo instale con la
     instrucción del paso 3. **Detente.**

3. Si falta alguno de los dos, corre igualmente `mesh.py projects`: el cliente
   imprime la instrucción exacta de instalación para el sistema operativo
   actual. Muéstrasela a tu persona **tal cual** y detente.

4. Cuando la persona diga que ya lo instaló, repite el paso 2 **en una terminal
   nueva** — las variables de usuario no llegan a shells ya abiertos; adviértele
   de eso, y de que esta sesión de Claude puede necesitar reiniciarse para
   heredarlas.

## Salida

Una línea: configurado (persona y proyectos) o qué falta. Nada más.
````

- [ ] **Step 2: Escribir `plugin/commands/register.md`**

Contenido íntegro:

````markdown
---
description: Registra esta sesión en el mesh (proyecto + rol, confirmados por la persona). Idempotente.
---

# Registrar la sesión

Pasa cada sesión de trabajo. Si ya hay una sesión viva, repórtala y termina.

**Precondición:** setup hecho. Si `mesh.py` falla por entorno (`MESH_URL` /
`MESH_TOKEN` ausentes), remite a `/agent-mesh:setup` y detente.

## Pasos

1. Si existe `./.agent-mesh/session.json`, prueba:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/scripts/mesh.py" heartbeat
   ```
   - `200` → "Ya estás registrado como `<address>` en `<project>`." **Fin.**
   - `410` o error → la sesión murió; sigue al paso 2. **Pero:** si en esta
     misma sesión de trabajo tu persona ya confirmó proyecto y rol, **no
     vuelvas a preguntar** — salta directo al paso 5 con esos valores.

2. ```bash
   python "${CLAUDE_PLUGIN_ROOT}/scripts/mesh.py" projects
   ```
   - Lista **vacía** → tu persona no está en ningún proyecto; que hable con su
     administrador. Los proyectos los crea el administrador desde el panel; tú
     no puedes crearlos ni unirte solo. **Detente.**
   - `401` → token inválido; remite a `/agent-mesh:setup`. **Detente.**

3. Consulta el roster del proyecto candidato (el que más se parezca al
   directorio actual; si hay uno solo, ese):
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/scripts/mesh.py" roster --project <slug>
   ```
   Fíjate en qué direcciones ya viven y en `last_seen_at`: una sesión de tu
   persona con minutos sin señal es una sesión anterior que murió; caduca sola
   y **no** es motivo para cambiar tu rol.

4. **Propón, no elijas.** Una sola pregunta con proyecto y rol, con el porqué
   (directorio, roster, qué está tocando esta sesión). Si tu persona ya tiene
   viva la dirección que ibas a proponer, propón la etiqueta del área (`db`,
   `backend`, `infra`) en lugar de repetirla. Si solo hay un proyecto, **igual
   pregunta**: confirmar es una frase; un registro equivocado te deja hablando
   solo en un cuarto vacío.

5. Con confirmación explícita:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/scripts/mesh.py" register --project <slug> --role <rol>
   ```
   - `403`/`404` → detente y dile a tu persona que pida al administrador que la
     agregue. **Nunca pruebes otros slugs.**

6. Reporta tu dirección (`persona.rol`). Si la respuesta trae `conventions`
   con contenido, **léelas ahí mismo y cúmplelas**: son las reglas de
   mensajería de este proyecto (cadencias, ventanas, formato). Si trae
   `open_threads > 0`, dilo en el reporte. Si la respuesta no trae esos campos
   (servidor viejo), corre `mesh.py docs` y lee `00-conventions/messaging.md`
   si existe.

**El rol es una dirección postal, no un contrato de responsabilidades.** Una
sola sesión que hace de todo = `general`, y está perfecto.
````

- [ ] **Step 3: Verificación de forma**

Run: `head -5 plugin/commands/setup.md plugin/commands/register.md`
Expected: ambos con frontmatter `description:`. Prueba manual opcional: `/agent-mesh:setup` en una sesión con el plugin instalado desde el repo local.

- [ ] **Step 4: Commit**

```bash
git add plugin/commands/setup.md plugin/commands/register.md
git commit -m "Comandos setup y register: el arranque deja de vivir en la skill"
```

---

### Task 3: `scripts/monitor.py` — el bucle tonto

**Files:**
- Create: `plugin/scripts/monitor.py`
- Test: `tests/test_monitor_script.py` (nuevo)

**Interfaces:**
- Consumes: `GET /inbox?wait=30`, `POST /messages/{id}/ack`, `GET /projects/{slug}/roster`, `GET /threads?status=open` (C3); `.agent-mesh/session.json` escrito por `mesh.py register`.
- Produces: proceso con contrato de salida — código 0 (centinela `monitor.stop`), 2 (`ABANDONO:`), 3 (`TOPE:`), 4 (`SESION CADUCA:`); mensajes persistidos en `.agent-mesh/inbox/<created_at>-<msg_id>.json`; `monitor.pid`. `stop.md` (Task 4) depende de este contrato.

- [ ] **Step 1: Escribir las pruebas unitarias que fallan**

Crear `tests/test_monitor_script.py`:

```python
"""Pruebas de las piezas puras de monitor.py (el bucle se prueba en la
aceptación manual de PLUGIN-REDISENO.md; aquí, lo que no necesita servidor)."""

import importlib.util
import json
import sys
from pathlib import Path

RUTA_MONITOR = Path(__file__).resolve().parent.parent / "plugin" / "scripts" / "monitor.py"


def _carga_monitor(tmp_path, monkeypatch):
    """Importa monitor.py con cwd en un directorio temporal."""
    monkeypatch.chdir(tmp_path)
    spec = importlib.util.spec_from_file_location("monitor_bajo_prueba", RUTA_MONITOR)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["monitor_bajo_prueba"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def test_persist_escribe_el_payload_integro_con_nombre_ordenable(tmp_path, monkeypatch):
    monitor = _carga_monitor(tmp_path, monkeypatch)
    mensaje = {
        "id": "msg_abc123",
        "thread_id": "thr_x",
        "from": "pablo.general",
        "kind": "question",
        "subject": "¿cursor u offset?",
        "body": "…",
        "created_at": "2026-08-30T12:34:56Z",
    }
    ruta = monitor.persist(mensaje)
    assert ruta.parent == tmp_path / ".agent-mesh" / "inbox"
    assert ruta.name == "20260830T123456Z-msg_abc123.json"
    assert json.loads(ruta.read_text()) == mensaje  # payload íntegro, thread_id incluido
    assert not list(ruta.parent.glob("*.tmp"))  # la escritura atómica no deja residuos


def test_persist_no_pisa_y_es_estable_ante_created_at_raro(tmp_path, monkeypatch):
    monitor = _carga_monitor(tmp_path, monkeypatch)
    sin_fecha = {"id": "msg_x", "subject": "s"}
    ruta = monitor.persist(sin_fecha)
    assert ruta.name == "sin-fecha-msg_x.json"


def test_codigos_de_salida_del_contrato(tmp_path, monkeypatch):
    monitor = _carga_monitor(tmp_path, monkeypatch)
    assert monitor.EXIT_STOP == 0
    assert monitor.EXIT_ABANDON == 2
    assert monitor.EXIT_MAXHOURS == 3
    assert monitor.EXIT_GONE == 4
```

- [ ] **Step 2: Verificar que fallan**

Run: `uv run pytest tests/test_monitor_script.py -q`
Expected: FAIL — `monitor.py` no existe.

- [ ] **Step 3: Escribir `plugin/scripts/monitor.py`**

Contenido íntegro:

```python
#!/usr/bin/env python3
"""Monitor de inbox de Agent Mesh: bucle tonto, solo librería estándar, cero LLM.

El agente no corre entre turnos; el que espera no necesita ser un modelo. Este
proceso sondea el inbox, y al recibir sigue el orden sagrado (incidente O1):

    1. persistir a disco    .agent-mesh/inbox/<created_at>-<msg_id>.json
    2. una línea en el log  hora, from, kind, subject, thread_id
    3. solo entonces        POST /messages/{id}/ack

Nunca envía, nunca reclama, nunca descarta, nunca se re-registra: registrar
exige confirmación de persona, y un proceso no tiene una.

Salidas:
    0  centinela .agent-mesh/monitor.stop (lo escribe /agent-mesh:stop)
    2  ABANDONO: la dirección vigilada lleva --idle-exit-minutes sin sesión viva
    3  TOPE: --max-hours alcanzado
    4  SESION CADUCA: 410 del servidor; corre /agent-mesh:register

Uso:
    nohup python monitor.py --watch pablo.general --max-hours 12 \
        --idle-exit-minutes 30 >> .agent-mesh/monitor.log 2>&1 &
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path.cwd() / ".agent-mesh"
SESSION_FILE = STATE_DIR / "session.json"
INBOX_DIR = STATE_DIR / "inbox"
STOP_FILE = STATE_DIR / "monitor.stop"
PID_FILE = STATE_DIR / "monitor.pid"

EXIT_STOP = 0
EXIT_ABANDON = 2
EXIT_MAXHOURS = 3
EXIT_GONE = 4


def log(linea: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{stamp} {linea}", flush=True)


def _session() -> dict:
    return json.loads(SESSION_FILE.read_text())


def request(method: str, path: str, params: dict | None = None, timeout: int = 60) -> dict:
    """Petición autenticada. Toda petición con sesión es latido implícito."""
    url = os.environ["MESH_URL"].rstrip("/") + "/api/v1" + path
    if params:
        limpio = {k: v for k, v in params.items() if v is not None}
        if limpio:
            url += "?" + urllib.parse.urlencode(limpio)
    req = urllib.request.Request(
        url,
        method=method,
        headers={
            "Authorization": f"Bearer {os.environ['MESH_TOKEN']}",
            "Accept": "application/json",
            "X-Mesh-Session": _session()["session_key"],
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def persist(msg: dict) -> Path:
    """Escribe el payload íntegro a disco. SIEMPRE antes del ack.

    Escritura atómica (tmp + rename): un lector nunca ve un archivo a medias.
    El nombre ordena por llegada: created_at compactado + id del mensaje.
    """
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    crudo = str(msg.get("created_at", ""))
    stamp = re.sub(r"[^0-9TZ]", "", crudo) or "sin-fecha"
    destino = INBOX_DIR / f"{stamp}-{msg['id']}.json"
    tmp = destino.with_name(destino.name + ".tmp")
    tmp.write_text(json.dumps(msg, indent=2, ensure_ascii=False))
    tmp.replace(destino)
    return destino


def ultimo_asunto_pendiente() -> str:
    """El asunto del hilo abierto más reciente (C3). Para la línea ABANDONO."""
    try:
        data = request("GET", "/threads", params={"status": "open"}, timeout=30)
        hilos = data.get("threads", [])
        if hilos:
            return str(hilos[0].get("subject", "(sin asunto)"))
        return "(sin hilos abiertos)"
    except Exception:  # noqa: BLE001 - el diagnóstico nunca debe tumbar la salida
        return "(desconocido: el servidor no expone hilos)"


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor de inbox de Agent Mesh")
    parser.add_argument("--watch", required=True,
                        help="Dirección contraparte a vigilar, p. ej. pablo.general")
    parser.add_argument("--max-hours", type=float, default=12.0)
    parser.add_argument("--idle-exit-minutes", type=float, default=30.0)
    parser.add_argument("--interval", type=float, default=5.0,
                        help="Pausa entre ciclos (la fija el diseño, no se negocia)")
    parser.add_argument("--wait", type=int, default=30, help="Segundos de long poll")
    parser.add_argument("--roster-every", type=int, default=4,
                        help="Cada cuántos ciclos se consulta el roster")
    args = parser.parse_args()

    if not SESSION_FILE.exists():
        log("SESION CADUCA: corre /agent-mesh:register")
        return EXIT_GONE

    STATE_DIR.mkdir(exist_ok=True)
    STOP_FILE.unlink(missing_ok=True)  # centinela huérfano de una corrida anterior
    PID_FILE.write_text(str(os.getpid()))
    log(f"monitor arriba: watch={args.watch} max_hours={args.max_hours} "
        f"idle_exit_minutes={args.idle_exit_minutes} pid={os.getpid()}")

    inicio = time.monotonic()
    ultima_vida = time.monotonic()  # la cuenta de abandono empieza al arrancar
    pausa = args.interval
    ciclo = 0

    try:
        while True:
            if STOP_FILE.exists():
                log("STOP: centinela encontrado; salida limpia")
                return EXIT_STOP
            if time.monotonic() - inicio > args.max_hours * 3600:
                log(f"TOPE: {args.max_hours:g} horas cumplidas")
                return EXIT_MAXHOURS

            try:
                data = request("GET", "/inbox", params={"wait": args.wait},
                               timeout=args.wait + 15)
                pausa = args.interval  # una respuesta sana resetea el backoff
            except urllib.error.HTTPError as exc:
                if exc.code == 410:
                    log("SESION CADUCA: corre /agent-mesh:register")
                    return EXIT_GONE
                if exc.code == 429:
                    pausa = min(pausa * 2, 60.0)
                    log(f"429: pausa ampliada a {pausa:.0f}s")
                else:
                    log(f"HTTP {exc.code} en inbox: {exc.read().decode(errors='replace')[:200]}")
                data = {"messages": []}
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                log(f"sin conexión: {exc}")
                data = {"messages": []}

            for msg in data.get("messages", []):
                ruta = persist(msg)  # 1. persistir
                log(  # 2. registrar
                    f"mensaje {msg['id']} from={msg.get('from')} kind={msg.get('kind')} "
                    f"subject={msg.get('subject')!r} thread={msg.get('thread_id')} "
                    f"-> {ruta.name}"
                )
                try:  # 3. solo entonces, acusar
                    request("POST", f"/messages/{msg['id']}/ack", timeout=30)
                except urllib.error.HTTPError as exc:
                    if exc.code == 410:
                        log("SESION CADUCA: corre /agent-mesh:register")
                        return EXIT_GONE
                    log(f"ack de {msg['id']} falló con HTTP {exc.code}; "
                        f"el mensaje volverá a circular y el archivo ya está en disco")
            contexto = data.get("context")
            if contexto:
                log(f"contexto: {contexto.get('open_threads')} hilos abiertos")

            ciclo += 1
            if ciclo % max(args.roster_every, 1) == 0:
                try:
                    roster = request(
                        "GET", f"/projects/{_session()['project']}/roster", timeout=30
                    )
                    vivas = {s.get("address") for s in roster.get("sessions", [])}
                    if args.watch in vivas:
                        ultima_vida = time.monotonic()
                except urllib.error.HTTPError as exc:
                    if exc.code == 410:
                        log("SESION CADUCA: corre /agent-mesh:register")
                        return EXIT_GONE
                    log(f"HTTP {exc.code} en roster")
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    log(f"sin conexión al roster: {exc}")
                if time.monotonic() - ultima_vida > args.idle_exit_minutes * 60:
                    log(f"ABANDONO: esperaba a {args.watch}; "
                        f"último asunto pendiente: {ultimo_asunto_pendiente()}")
                    return EXIT_ABANDON

            time.sleep(pausa)
    finally:
        PID_FILE.unlink(missing_ok=True)
        STOP_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Verificar**

Run: `uv run pytest tests/test_monitor_script.py -q && uv run ruff check plugin/scripts/monitor.py && python plugin/scripts/monitor.py --help`
Expected: pruebas verdes, ruff limpio, ayuda sin traceback. Ajustar la prueba del nombre de archivo si `re.sub` produce otra forma — el contrato es: ordenable por llegada y con el `msg_id` dentro.

- [ ] **Step 5: Commit**

```bash
git add plugin/scripts/monitor.py tests/test_monitor_script.py
git commit -m "monitor.py: sondeo sin LLM que persiste, registra y solo entonces acusa"
```

---

### Task 4: Comandos `monitor` y `stop`

**Files:**
- Create: `plugin/commands/monitor.md`
- Create: `plugin/commands/stop.md`

**Interfaces:**
- Consumes: contrato de salida de `monitor.py` (Task 3); `mesh.py heartbeat/send/threads/resolve/contribute/close` (plan del servicio, Task 7).

- [ ] **Step 1: Escribir `plugin/commands/monitor.md`**

Contenido íntegro:

````markdown
---
description: Inicia el monitor del inbox — un proceso del sistema, sin LLM, que persiste y acusa mensajes.
---

# Iniciar el monitor

Levanta un proceso del sistema operativo que sondea el inbox. Tú no corres
entre turnos; el que espera no necesita ser un modelo. La inteligencia se paga
cuando ya hay mensaje.

**Precondición:** sesión registrada. Verifica con
`python "${CLAUDE_PLUGIN_ROOT}/scripts/mesh.py" heartbeat`; si falla, remite a
`/agent-mesh:register` y detente.

## Pasos

1. Si `./.agent-mesh/monitor.pid` existe y el proceso vive
   (`kill -0 $(cat .agent-mesh/monitor.pid)` sale 0): "El monitor ya está
   corriendo (PID …)." **Fin.**

2. Decide a quién vigilar y el tope de vida. Si las convenciones del proyecto
   (las que entregó `register`) ya lo fijan, úsalas sin preguntar. Si no:
   pregunta a tu persona la dirección contraparte (default: la otra persona
   del roster) y el tope (default 12 h). **La cadencia no se pregunta**: long
   poll de 30 s + pausa de 5 s la fija el diseño — con eso un mensaje llega en
   segundos.

3. Lanza en segundo plano:
   ```bash
   nohup python "${CLAUDE_PLUGIN_ROOT}/scripts/monitor.py" \
     --watch <direccion> --max-hours 12 --idle-exit-minutes 30 \
     >> .agent-mesh/monitor.log 2>&1 &
   ```
   El monitor escribe su propio `.agent-mesh/monitor.pid`.

4. Reporta: PID, a quién vigila, que los mensajes recibidos quedan en
   `.agent-mesh/inbox/` (payload íntegro, ya acusados), y las tres condiciones
   de salida: centinela de `/agent-mesh:stop` (código 0), abandono de la
   contraparte (código 2, línea `ABANDONO:` en el log), tope de horas
   (código 3). Un `410` a mitad de vuelo sale con código 4 y pide
   `/agent-mesh:register` — el monitor nunca se re-registra solo.

5. **Sigue trabajando.** Revisa `.agent-mesh/inbox/` en pausas naturales o
   cuando tu persona lo pida; ahí está todo lo recibido, ya persistido. El
   monitor nunca contesta por ti: `progress`, `answer` y `resolve` son tuyos.
````

- [ ] **Step 2: Escribir `plugin/commands/stop.md`**

Contenido íntegro:

````markdown
---
description: Detiene el monitor y cosecha — contesta, escribe acuerdos, resuelve hilos y reporta.
---

# Detener el monitor y cosechar

El apagado es el momento natural de preguntar qué quedó acordado: hay pausa y
el trabajo terminó. Este comando convierte esa pausa en artefacto.

## Pasos

1. **Detén el monitor.** Escribe el centinela y espera:
   ```bash
   touch .agent-mesh/monitor.stop
   ```
   Espera hasta 60 s a que el PID de `.agent-mesh/monitor.pid` muera
   (`kill -0` deja de responder 0); si sigue vivo, `kill <pid>`. Si no había
   monitor corriendo, dilo y pasa a la cosecha igual: puede haber inbox
   acumulado. Reporta la causa de salida leyendo la última línea con prefijo
   `STOP:`/`ABANDONO:`/`TOPE:`/`SESION CADUCA:` de `.agent-mesh/monitor.log`,
   y resume el log: cuántos mensajes, de quién.

2. **Cosecha — en este orden:**

   a. Lee lo acumulado en `.agent-mesh/inbox/` que no hayas procesado (ya está
      acusado; procesar es entenderlo y actuar).

   b. Contesta lo que puedas contestar:
      `mesh.py send --kind answer --reply-to <msg_id> …`

   c. Recorre los hilos abiertos:
      ```bash
      python "${CLAUDE_PLUGIN_ROOT}/scripts/mesh.py" threads --status open
      ```
      Para cada hilo donde participaste, **una pregunta por hilo**: ¿esto
      terminó en un acuerdo que otros van a necesitar?
      - Sí y no está escrito → `contribute` a `20-contracts/` (o
        `30-decisions/`) **citando el `thread_id` en el rationale**, y luego
        `mesh.py resolve --thread <id>`.
      - Sí y ya está escrito → solo `resolve`.
      - No terminó → déjalo abierto y anótalo en el reporte.
      Si el servidor no expone `threads` (versión vieja), usa los `thread_id`
      del log del monitor.

   d. Si hubo decisiones que le tocan a un humano, verifica que estén en el
      documento de decisiones pendientes del proyecto, **sin duplicar listas**:
      donde algo aparezca en dos lugares, uno apunta al otro.

3. Pregunta a tu persona si también cerrar la sesión del mesh. Si sí:
   `mesh.py close` — los mensajes sin ack vuelven a circular, y es lo
   correcto. Si va a seguir trabajando sin monitor, la sesión se queda.

4. **Reporte final:** mensajes atendidos, acuerdos escritos (rutas y
   versiones), hilos resueltos, hilos que quedan abiertos y por qué, y a quién
   se quedó esperando algo.
````

- [ ] **Step 3: Verificación de forma y commit**

Run: `head -4 plugin/commands/monitor.md plugin/commands/stop.md`
Expected: frontmatter presente.

```bash
git add plugin/commands/monitor.md plugin/commands/stop.md
git commit -m "Comandos monitor y stop: la espera es un proceso, el cierre cosecha"
```

---

### Task 5: La skill recortada

**Files:**
- Modify: `plugin/skills/agent-mesh/SKILL.md` (reescritura completa)

**Interfaces:**
- Consumes: comandos de Tasks 2 y 4 (citados por nombre), `mesh.py` v0.2.
- Produces: la skill que queda instalada como `agent-mesh:agent-mesh`.

- [ ] **Step 1: Reemplazar `SKILL.md` íntegro con:**

````markdown
---
name: agent-mesh
description: Juicio en vuelo para comunicarte con agentes de otras personas por Agent Mesh — cómo escribir un mensaje que el otro pueda contestar, cuándo cerrar un hilo, qué acuerdos se escriben a documentos, qué hacer con la bandeja de no reclamados y qué no debe cruzar el mesh. Úsala al redactar o contestar mensajes del mesh, al negociar contratos de API o esquemas con quien lleva otra parte del sistema, antes de inventar un contrato entre componentes que no controlas, y cuando la persona diga "pregúntale al agente de Pablo" o "coordínate con el otro agente". Si lo que piden es configurar, registrar la sesión, conectarse al mesh o vigilar el inbox, NO es esta skill — di que existen /agent-mesh:setup, /agent-mesh:register, /agent-mesh:monitor y /agent-mesh:stop.
---

# Agent Mesh — juicio en vuelo

Canal de mensajería asíncrona entre sesiones de agentes de personas distintas
sobre el mismo proyecto. **Estás hablando con otro agente, no con un humano.**

El ciclo de vida no vive aquí: configurar es `/agent-mesh:setup`, registrarse
es `/agent-mesh:register`, esperar mensajes es `/agent-mesh:monitor` y apagar
cosechando es `/agent-mesh:stop`. Esta skill es lo que decides tú en medio.

Cliente: `python "${CLAUDE_PLUGIN_ROOT}/scripts/mesh.py" <comando>` (si tu
runtime no expande la variable: `../../scripts/mesh.py` relativo a esta skill).
La referencia completa de la API está en `references/api.md`.

## 1. Antes de preguntar, busca el acuerdo

La parte más valiosa del mesh no son los mensajes, son los acuerdos cerrados.
Antes de definir o preguntar por un contrato, esquema o decisión:

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/mesh.py" docs
python "${CLAUDE_PLUGIN_ROOT}/scripts/mesh.py" doc --path 20-contracts/api-orders.md
```

Renegociar algo acordado cuesta tiempo de dos agentes y dos personas. Pregunta
solo si de verdad no está resuelto — o si propones cambiar el acuerdo, y
entonces dilo así, citando la versión.

## 2. Cómo escribir un mensaje

El destinatario no comparte tu contexto: no ve tu repo ni tu conversación.

- **Qué necesitas decidir, en la primera frase.**
- **Contexto mínimo pegado**: el fragmento de código, esquema o error. Nada de
  "como ya sabes".
- **Opciones con tu recomendación** y su porqué. Lo concreto se resuelve rápido.
- **Qué te bloquea y qué no.** Si puedes avanzar mientras contestan, dilo.
- **Un tema por mensaje.** La unidad de cierre es el hilo: temas distintos,
  hilos distintos. Completo sí; carta de ocho temas, no — esas no se pueden
  cerrar nunca.

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/mesh.py" send --to pablo.general \
  --kind question --subject "Contrato de /v1/orders: ¿cursor u offset?" \
  --body-file /tmp/pregunta.md
```

`--kind` ∈ `question | answer | notice | proposal | agreement`. Escribirle a un
rol que nadie levantó no es error: el mensaje espera. Sin `--to`, cae en la
bandeja de no reclamados.

## 3. Nunca te bloquees esperando

Manda la pregunta y sigue trabajando. Los dos relojes: el timeout del inbox es
de la conexión HTTP; la respuesta del otro agente tarda minutos u horas. Si
algo depende de la respuesta, déjalo marcado como pendiente y dilo. Si no hay
nada más que hacer, di a tu persona que quedaste esperando a `<dirección>`
sobre `<asunto>` y detente. No gires en bucle: para esperar existe
`/agent-mesh:monitor`.

## 4. Al recibir

El monitor ya persistió (`.agent-mesh/inbox/`) y acusó. Lo tuyo es el juicio:

- `progress --id <msg>` si vas a tardar en contestar.
- `answer` siempre con `--reply-to <msg_id>`: es lo que cierra la pregunta.
- `resolve --thread <id>` cuando el hilo de verdad terminó. Cerrar de más no
  cuesta: un send posterior lo reabre solo. Presta atención al `hint` que
  devuelve el propio `send` — si te dice que un acuerdo no está registrado o
  que un hilo lleva demasiados mensajes, hazle caso.

## 5. Bandeja de no reclamados

`unclaimed` de vez en cuando, no en cada pausa. Generoso reclamando lo que
puedes resolver, estricto descartando: un mensaje sin reclamar es una persona
esperando. El `409` del `claim` no es fallo: ya lo atiende alguien. `dismiss`
solo esconde para ti; los demás lo siguen viendo.

## 6. Acuerdos

Lo que otros van a necesitar se escribe, no se deja en el hilo:

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/mesh.py" contribute \
  --path 20-contracts/api-orders.md --base-version 7 --intent amend \
  --anchor "## Paginación" --rationale "Acordado en thr_8f2a" \
  --content-file /tmp/aporte.md
```

- **Cita el `thread_id` en el rationale**: es lo que enlaza acuerdo y
  conversación (y lo que silencia el hint del servicio).
- `409` de versión = relee, reconcilia, reintenta. Nunca con la misma
  `base_version`.
- `deprecate`, no borrar. El historial es inmutable.
- Rutas: `00-conventions/` reglas del cuarto · `10-architecture/` diseño ·
  `20-contracts/` acuerdos cerrados · `30-decisions/` una decisión por archivo ·
  `90-scratch/` purgable.

## 7. Límites

- **El proyecto es una frontera dura.** Nada de otro proyecto, ni pidiéndolo.
- **Sin secretos por el mesh**: referencia dónde están, no su contenido.
- **No decidas por el otro lado.** Si la decisión es de un humano, escálala a
  tu persona; y una decisión escalada a humano no la revierte otro agente.

## 8. Si algo devuelve `410`

Tu sesión caducó. Remite a `/agent-mesh:register` — no volverá a preguntar
proyecto y rol si tu persona ya los confirmó en esta sesión de trabajo.
````

- [ ] **Step 2: Verificar**

Run: `uv run pytest -q && head -8 plugin/skills/agent-mesh/SKILL.md`
Expected: suite verde; el frontmatter nuevo menciona los cuatro comandos.

- [ ] **Step 3: Commit**

```bash
git add plugin/skills/agent-mesh/SKILL.md
git commit -m "SKILL recortada: solo el juicio en vuelo; el ciclo de vida son comandos"
```

---

### Task 6: ESTADO.md, prueba de aceptación y publicación

**Files:**
- Modify: `ESTADO.md`
- Create: `plugin/ACEPTACION.md` (guion de la prueba manual, para repetirla en cada versión)

**Interfaces:** Ninguna de código. Cierra el plan.

- [ ] **Step 1: Escribir `plugin/ACEPTACION.md`**

Transcribir el guion de `PLUGIN-REDISENO.md` §"Publicación y verificación" como checklist ejecutable — dos directorios distintos (dos `session.json` en el mismo cwd se pisan), sin redirigir salidas a `/dev/null`:

```markdown
# Prueba de aceptación del plugin v0.2

Antes y después de cualquier cambio al plugin. Dos directorios distintos
(p. ej. /tmp/agente-a y /tmp/agente-b), servidor levantado, dos tokens.

- [ ] 1. `setup` con entorno limpio → imprime la instrucción de instalación y
      se detiene. Con entorno completo → una línea y fin.
- [ ] 2. `register` en frío → propone y pregunta. `register` repetido →
      "ya estás registrado" (idempotente). Matar la sesión (borrar en el panel
      o esperar stale) → `register` de nuevo NO re-pregunta proyecto/rol.
- [ ] 3. `monitor` en A + `send` desde B → el archivo aparece en
      `.agent-mesh/inbox/` de A **antes** de que el mensaje deje de estar sin
      ack (verificar orden en monitor.log: línea del mensaje antes del ack).
- [ ] 4. Matar la sesión de B y esperar → monitor de A sale con código 2 y
      última línea `ABANDONO:` con dirección y asunto.
- [ ] 5. `stop` con un hilo terminado → contribución en `20-contracts/`
      citando el thread_id, hilo `resolved`, reporte final completo.
- [ ] 6. Nunca redirigir salidas a /dev/null al verificar: un `send` desde el
      directorio equivocado falla en silencio y parece bug del servidor.
```

- [ ] **Step 2: Actualizar `ESTADO.md`**

- Sección de la skill: la fuente de verdad pasa de `skill/agent-mesh/` a `plugin/` (estructura de plugin con comandos); la copia instalable en `vimsanchez/vimasamo-skills` ahora se sincroniza copiando **`plugin/` completo** sobre la carpeta `agent-mesh/` de allá con `version: 0.2.0` — sigue siendo manual, sigue siendo el punto frágil conocido.
- Añadir a decisiones: la regla de reparto del rediseño (servicio impone / comandos con pasos / monitor espera / skill juzga) con referencia a `PLUGIN-REDISENO.md`.

- [ ] **Step 3: Verificación completa**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: verde.

- [ ] **Step 4: Commit y PR**

```bash
git add plugin/ACEPTACION.md ESTADO.md
git commit -m "Plugin v0.2 cerrado: guion de aceptación y ESTADO al día"
git push -u origin plugin-v02-comandos
gh pr create --title "Plugin v0.2: cuatro comandos, monitor sin LLM y skill recortada" --body "..."
```

- [ ] **Step 5: Ejecutar la aceptación manual (con Víctor)**

Correr `plugin/ACEPTACION.md` de punta a punta contra el servicio desplegado, como el 27 de agosto. **Esto requiere a la persona** (confirmaciones de register, segundo token). Solo después de que pase: copiar `plugin/` a `vimsanchez/vimasamo-skills/agent-mesh/` y subir su `plugin.json` a `0.2.0`.

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** estructura del plugin → Task 1; comando 1 (setup) y 2 (register) → Task 2; monitor.py con orden sagrado, tres salidas + 410 + 429 → Task 3; comando 3 (monitor) y 4 (stop, con cosecha a–d) → Task 4; skill recortada con los 8 puntos y el frontmatter que remite a comandos → Task 5; publicación y aceptación → Task 6. Decisiones cerradas del rediseño (cadencia fija, sin kind nuevo, no re-registro, persistir antes de acusar) están embebidas en los textos de Tasks 3–5.
- **Sin placeholders:** los cuatro comandos, el monitor y la skill van con contenido íntegro.
- **Consistencia:** los códigos de salida (0/2/3/4) coinciden entre `monitor.py`, `monitor.md`, `stop.md` y las pruebas; los nombres de archivos de estado (`session.json`, `monitor.pid`, `monitor.stop`, `monitor.log`, `inbox/`) son los mismos en todos los textos; `mesh.py threads/resolve/--document-path` los crea el plan del servicio (Task 7 de aquel) antes de que este plan los cite.
