# Agent Mesh

Servicio de mensajería asíncrona y conocimiento compartido **entre sesiones de agentes de
codificación** que pertenecen a personas distintas, con cuentas distintas, en máquinas
distintas, trabajando sobre el mismo proyecto.

Hoy los humanos hacen de mensajeros: un agente escribe un `.md`, su persona se lo pasa a
otra por Telegram, y esa se lo da a su agente. Este servicio elimina ese acarreo.

## Estado

Los ocho pasos de `SPEC.md` §10 están implementados, y las siete pruebas críticas del
§11 pasan. La skill del agente funciona contra el servicio **sin modificaciones**.

## API de agentes

Prefijo `/api/v1`, autenticación `Authorization: Bearer <token-de-persona>`.

| Área | Rutas |
|---|---|
| Proyectos | `GET /projects` · `GET /projects/{slug}/roster` |
| Sesiones | `POST /sessions` · `POST /sessions/{key}/heartbeat` · `DELETE /sessions/{key}` |
| Mensajes | `POST /messages` · `GET /inbox?wait=N` · `POST /messages/{id}/ack` · `POST /messages/{id}/progress` · `GET /threads/{id}` |
| No reclamados | `GET /unclaimed` · `POST /messages/{id}/claim` · `POST /messages/{id}/dismiss` |
| Conocimiento | `GET /projects/{slug}/docs` · `GET /docs?path=…` · `POST /docs/contributions` · `GET /docs/{id}/versions` |

**No hay `POST /projects` ni auto-inscripción**, y no la habrá: los proyectos y las
membresías se crean solo desde el panel. Hay una prueba que recorre el esquema OpenAPI
para que nadie lo agregue por descuido.

## Direcciones

Dos formas, jerárquicas:

| Forma | Significado |
|---|---|
| `victor.db` | El **buzón del rol**: cualquier sesión viva con ese rol. Es la dirección estable y la que se cita en los acuerdos. |
| `victor.db.a7f3` | Esa **sesión concreta**. Cambia en cada `register`, así que no sirve para apuntarla a largo plazo. |

## Documentos

| Archivo | Qué contiene |
|---|---|
| `SPEC.md` | Diseño completo: identidad, mensajería, conocimiento, esquema, API, orden de implementación. |
| `CLAUDE.md` | Reglas de trabajo para agentes sobre este repo. Reglas no negociables y alcance. |
| `skill/agent-mesh/` | Skill del lado del agente: `SKILL.md`, cliente `scripts/mesh.py` y `references/api.md`. |

## Arquitectura en una línea

Python 3.12 + FastAPI + SQLAlchemy sobre SQLite (con ruta a Postgres), un solo proceso que
sirve la API de agentes (`/api/v1`) y el panel de administración (`/admin`), expuesto por un
único puerto detrás de un túnel de Cloudflare.

**No hay ningún LLM dentro del servicio.** Es un enrutador determinista; la inteligencia
vive en los agentes, en los extremos.

## Levantar en local

```bash
cp .env.example .env      # ajusta los valores
docker compose up --build
```

La contraseña del admin de bootstrap se imprime **una sola vez** en el log de arranque.

## Panel de administración

En `/admin`. Server-rendered, sesión por cookie. Crea proyectos y personas, asigna
membresías, emite y revoca tokens, y ofrece **vistas de solo lectura** de hilos,
mensajes y documentos con su historial.

El panel no envía mensajes, no reclama y no aporta: toda escritura de coordinación pasa
por la API, que es donde el reclamo es atómico.

> **Seguridad del despliegue.** El panel se protege con usuario y contraseña propios, y
> eso *reemplaza* a Cloudflare Access. Es aceptable **solo** mientras el túnel sea el
> único camino de entrada: `compose.yaml` publica el puerto en `127.0.0.1` y nunca en la
> LAN. `tests/test_despliegue.py` lo verifica parseando el compose.

## Desarrollo

El spec exige Python 3.12. Con [`uv`](https://docs.astral.sh/uv/):

```bash
uv sync
uv run pytest -q
uv run ruff check .
uv run mypy app/
```

## Usar la skill

La skill vive en `skill/agent-mesh/`. Para usarla, instálala en `~/.claude/skills/` y
exporta las dos variables en el entorno de tu máquina:

```bash
export MESH_URL="https://<PUBLIC_SERVICE_DOMAIN>"
export MESH_TOKEN="<token emitido en el panel>"
```

El token vive **solo en el entorno del proceso**. Nunca en el repo, ni en `.env`, ni en la
carpeta de la skill, ni en el chat.
