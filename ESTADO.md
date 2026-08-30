# Estado del proyecto

Este archivo existe para que el contexto **viaje entre máquinas**. Lo demás vive en
`~/.claude/`, que es local y no cruza; esto sí está versionado.

Si acabas de clonar el repo en otra máquina, lee esto primero.

**Última actualización:** 2026-08-30 (tras el delta v0.2 del servicio y el plugin 0.2.0)

---

## Dónde está el proyecto

Los **ocho pasos** del orden de implementación de `SPEC.md` §10 están implementados, y
las **siete pruebas críticas** del §11 pasan. Encima de eso, los cambios **C1–C5 de
`SPEC-DELTA.md`** (v0.2, salidos del primer uso real en el proyecto `cck`) también:

- **C1**: el `ack` devuelve `thread_id`, `thread_status` y `subject` — la llave del hilo
  se conserva en la misma salida que el agente acaba de leer.
- **C2**: el `send` devuelve `thread_status`, `thread_message_count` y un `hint` cuando
  un `agreement` no está citado en ningún rationale o un hilo supera
  `THREAD_LONG_HINT_AFTER` (default 10) sin resolverse.
- **C3**: `POST /threads/{id}/resolve` (idempotente) y `GET /threads?status=`; un `send`
  a un hilo `resolved` lo reabre en la misma transacción.
- **C4**: el `register` entrega `conventions` (contenido de
  `00-conventions/messaging.md`, o null) y `open_threads`; el inbox con mensajes trae
  `context` con los hilos abiertos más viejos.
- **C5**: compuerta `REQUIRE_AGREEMENT_DOC` (default **false**): encendida, un
  `agreement` sin `document_path` válido es `422` accionable.

Cero migraciones de esquema: todo se calcula de tablas existentes. `mesh.py` ganó
`threads`, `resolve` y `send --document-path`.

```
pytest        306 passed
ruff / format limpio
mypy strict   sin fallos en app/ (39 archivos)
rutas de API  19: las 17 del §8 + resolve y GET /threads (SPEC-DELTA C3)
```

**El plugin v0.2 también está implementado** (`PLUGIN-REDISENO.md`): `skill/` se
reestructuró a `plugin/` con la forma de un plugin de Claude Code —
`.claude-plugin/plugin.json` (0.2.0), `commands/` (`setup`, `register`, `monitor`,
`stop`), `skills/agent-mesh/` (SKILL.md recortada a solo el juicio en vuelo) y
`scripts/` (`mesh.py` + `monitor.py`, el sondeador sin LLM que persiste → registra →
solo entonces acusa). La regla de reparto: el servicio impone, los comandos tienen
pasos, el monitor espera, la skill juzga. **Pendiente: la prueba de aceptación manual
(`plugin/ACEPTACION.md`, necesita dos tokens y a Víctor) y, solo después, la copia al
marketplace.**

La skill de `plugin/skills/agent-mesh/` (antes `skill/agent-mesh/`) es el **test de
aceptación** del servicio, no un artefacto que se ajuste a él. Funcionó sin una sola
modificación hasta el 27 de agosto de 2026, cuando el servicio se levantó por primera vez
de punta a punta (dos personas, tres sesiones, mensajes, reclamo con carrera, documentos
con `409`) y todo pasó. Ese mismo día se ajustó por primera vez —ver *Decisiones
tomadas* abajo— con un escenario de prueba antes y después del cambio. Desde el plugin
0.2.0, sus scripts se lintean y formatean como el resto del repo (el bundle del
marketplace se genera desde aquí).

### Todo el código está en `main` (desde PR #10)

Los ocho pasos se desarrollaron en PRs **apilados** (`#1 paso-1` ← `#2 paso-2` ← … ←
`#8 paso-8`) y se fusionaron **de arriba hacia abajo**: #1 entró a `main` primero, cuando
`paso-1` aún era solo el esqueleto, y cada PR siguiente cayó en la rama de abajo *antes*
de que esa rama recibiera su propio merge. Resultado: `main` quedó con el paso 1 y la
única punta que contenía los ocho pasos era `paso-7-documentos` (merge del #8).

Se corrigió con **PR #10** (`paso-7-documentos` → `main`, sin conflictos). Desde ese
merge, **`main` es la referencia**; las ramas `paso-*` son historia y no contienen nada
que falte en `main`.

Lección para la próxima pila: mergear **de abajo hacia arriba** (#8 → #7 → … → #1) o,
si ya se fusionó al revés, abrir un PR desde la rama que recibió el último merge.

---

## Decisiones tomadas el 27 de agosto de 2026

Las dos salieron de levantar el servicio y correr la skill contra él, no de leer código.

### La skill consulta el roster **antes** de proponer rol

Antes registraba en su paso 4 y miraba el roster en el 6, así que el agente proponía un
rol a ciegas aunque el texto le pidiera "no repetir el rol" de otra sesión. En el
escenario de prueba (repo genérico, `victor.general` ya vivo), el agente con la skill
vieja propuso `general` y escribió literalmente que *"el roster requiere sesión
registrada"*. El servidor nunca exigió eso —`GET /projects/{slug}/roster` solo pide el
token—; el que lo exigía era `mesh.py`, que sacaba el slug de la sesión guardada.

Cambio: `mesh.py roster --project <slug>` (opcional; sin flag se comporta igual que
antes), y los pasos de `SKILL.md` reordenados: entorno → `projects` → `roster` del
candidato → **una sola** confirmación de proyecto y rol → `register` → convenciones. Se
añadió también qué hacer ante un `410`, que solo estaba en `api.md`.

Esto baja la frecuencia del duplicado `victor.general × 2`; **no** elimina la necesidad
del reclamo atómico, porque siguen existiendo otros caminos (sesión huérfana que aún no
caduca, dos worktrees a propósito).

### Latido implícito

Solo `POST /sessions/{key}/heartbeat` refrescaba `last_seen_at`, y la skill nunca lo
menciona —a propósito: le pedimos al agente que no haga polling, y pedirle un ritual
aparte es frágil—. Consecuencia: un agente que revisaba el inbox "en pausas naturales"
quedaba `stale` a los 5 minutos y recibía `410` en la siguiente llamada.

Ahora `current_session` (`app/security/deps.py`) registra señal de vida en **toda**
petición con sesión válida, en su propia transacción para no depender del commit del
handler. Una sesión ya `stale` sigue dando `410`: revivirla dejaría en el aire los
mensajes que ya volvieron a circular. El endpoint explícito se conserva.

---

## Decisiones tomadas el 30 de agosto de 2026 (delta v0.2)

Dos elecciones que `SPEC-DELTA.md` dejaba abiertas, resueltas al implementar:

- **"Hilo abierto" para los conteos = `status != "resolved"`** (incluye `in_progress`,
  que hoy nada escribe en hilos). `GET /threads?status=X` en cambio filtra por igualdad
  exacta: ahí el agente pide un estado literal.
- **`GET /inbox` responde con `response_model_exclude_none`** para que la respuesta
  vacía del long poll siga siendo `{"messages": []}` sin `"context": null` (lo exige el
  delta para el bucle del monitor). Efecto colateral deliberado: `to`/`in_reply_to`
  nulos también se omiten en el inbox — `api.md` nunca los mostró ahí y los clientes
  leen con `.get()`.

---

## Pendiente de decisión

Nada. Todo lo que estaba abierto quedó decidido el 27 de agosto de 2026:

- **`admin_users.role` se queda con `owner | admin`.** `SPEC.md` §9 pide el campo sin fijar
  valores; `owner` es el administrador de bootstrap y `admin` cualquier otro que se dé de
  alta. Hoy nadie lee el campo (solo se pinta como etiqueta en el encabezado del panel) y
  ambos pueden hacer lo mismo; si algún día se restringe algo al `owner`, el dato ya está.
- **`GET /` redirige a `/admin`** (307, temporal a propósito: si la raíz se vuelve una
  página, que ningún navegador tenga la redirección cacheada). Quien recibe la URL pelona
  del servicio cae en el login y no en un 404.

---

## Despliegue

- Contenedor publicado en `127.0.0.1:8840` —el 8000 es el puerto por defecto de uvicorn
  y en la máquina de despliegue hay decenas de servicios así; el segmento 8840–8849 queda
  para Agent Mesh—. Verificado que **no** responde en la IP de LAN (`SPEC.md` §9).
- **Túnel de Cloudflare montado el 27 de agosto de 2026**: `https://mesh.agoconsultores.dev`.
  Verificado desde fuera: `/healthz` 200, `/admin/login` 200 y la API contesta con token.
  Ese es el `MESH_URL` que instalan las personas; `PUBLIC_SERVICE_DOMAIN` en `.env` ya
  apunta ahí (y **no** tiene relación con `ADMIN_EMAIL_DOMAIN`, regla 6).
- Recordatorio del §9: el panel se protege con usuario y contraseña propios, y eso
  *reemplaza* a Cloudflare Access. Es aceptable solo mientras el túnel sea la única
  puerta. `tests/test_despliegue.py` verifica la parte del compose; el túnel en sí no lo
  puede comprobar una prueba.
- `GET /` redirige (307) a `/admin`; la API vive en `/api/v1` y la salud en `/healthz`.
- El panel **exporta a Markdown** (PR #14): un hilo o un documento sueltos (`…/download`),
  todos los hilos (`threads.zip`), todos los documentos (`docs.zip`) o el proyecto entero
  (`export.zip`, con `INDEX.md`). Solo la versión vigente de cada documento, y solo desde
  el panel: la API de agentes no cambia. Pensado para bajarlo desde el celular entrando
  con usuario y contraseña.

---

## Notas operativas

Cosas que muerden en una máquina nueva y no se deducen leyendo el código.

### El nombre del repo no coincide con el del directorio

- Repo remoto: **`vimsanchez/agent-mesh`** (privado)
- Directorio local en la máquina original: `~/git/agents_mesh`

Es deliberado: `agent-mesh` coincide con el nombre del producto en `SPEC.md` y con el
nombre de la skill. No "corregir" ninguno de los dos por parecer un descuido.

### `origin` va por HTTPS, no por SSH

`gh` está configurado con `git_protocol: ssh` para github.com, pero si
`~/.ssh/known_hosts` no tiene entrada para github.com, cualquier push por SSH falla con
`Host key verification failed`. En la máquina original se resolvió apuntando `origin` a
HTTPS, donde ya había credencial guardada.

Si prefieres SSH, los tres fingerprints publicados por GitHub coinciden con los que
devuelve `ssh-keyscan`, así que esto es seguro:

```bash
ssh-keyscan github.com >> ~/.ssh/known_hosts
git remote set-url origin git@github.com:vimsanchez/agent-mesh.git
```

Falta confirmar que la clave pública de la máquina esté registrada en la cuenta.

### Python 3.12 con `uv`

`SPEC.md` pide 3.12. Si el Python del sistema es más viejo, `uv` lo resuelve sin tocarlo:

```bash
uv sync          # descarga cpython-3.12 y crea .venv
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

### `DATABASE_URL` es distinta en local y en contenedor

`.env.example` trae la ruta **local** (`sqlite:///./mesh.db`), que es la que necesitan
`alembic`, `uvicorn` y `pytest` fuera del contenedor. `compose.yaml` la sobrescribe con
`sqlite:////data/mesh.db`, que es el volumen nombrado.

Si `.env` trae la ruta del contenedor, cualquier comando local falla con
`unable to open database file`.

### El plugin se distribuye por el marketplace `vimasamo-skills`

La fuente de verdad es `plugin/` en **este** repo, que es donde se prueba contra la API
(desde el 0.2.0 es un plugin completo: comandos + skill + scripts, con la versión en
`plugin/.claude-plugin/plugin.json`). La copia instalable vive en
`vimsanchez/vimasamo-skills`, carpeta `agent-mesh/`. Al cambiar algo aquí: correr
`plugin/ACEPTACION.md` de punta a punta, copiar `plugin/` completo sobre la carpeta de
allá y subir la versión. Sigue siendo manual; sigue siendo el punto frágil conocido.
Instalación:
`/plugin marketplace add vimsanchez/vimasamo-skills` y `/plugin install agent-mesh@vimasamo-skills`.

### Levantar y probar de punta a punta

```bash
cp .env.example .env      # ajusta ADMIN_EMAIL_DOMAIN, BOOTSTRAP_ADMIN_EMAIL y fija SECRET_KEY
docker compose up -d --build
docker compose logs mesh | grep -A3 "ADMINISTRADOR INICIAL"   # la contraseña, una sola vez
```

La contraseña de bootstrap sale **solo en el log del primer arranque** con la base vacía.
Si recreas el contenedor (`up -d` tras cambiar `.env` o el puerto), el nuevo log dice
`bootstrap: ya existe al menos un administrador` y no la repite: usa la que ya cambiaste
en `/admin/password`. Si se perdió, la salida es borrar el volumen (`down -v`) y arrancar
de cero. Sin `SECRET_KEY` en `.env`, la sesión del panel se cierra en cada reinicio.

Luego, con dos agentes en **directorios distintos** (`mesh.py` guarda su sesión en
`./.agent-mesh/` y dos sesiones en el mismo cwd se pisan):

```bash
export MESH_URL=http://127.0.0.1:8840 MESH_TOKEN=<token emitido en /admin>
cd /tmp/agente-a && python .../plugin/scripts/mesh.py register --project <slug> --role db
```

No redirijas la salida a `/dev/null` al verificar: un `send` desde el directorio
equivocado falla en silencio y parece un bug del servidor.
