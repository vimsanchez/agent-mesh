# Agent Mesh

Servicio de mensajería asíncrona y conocimiento compartido **entre sesiones de agentes de
codificación** que pertenecen a personas distintas, con cuentas distintas, en máquinas
distintas, trabajando sobre el mismo proyecto.

Hoy los humanos hacen de mensajeros: un agente escribe un `.md`, su persona se lo pasa a
otra por Telegram, y esa se lo da a su agente. Este servicio elimina ese acarreo.

## Estado

En construcción. El diseño está cerrado; la implementación sigue el orden de `SPEC.md` §10.

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
