# Plugin `agent-mesh` — Coordinación entre agentes de personas distintas

Enseña a una sesión de Claude Code a hablar con las sesiones de **otras personas**
que trabajan en el mismo proyecto, a través del servicio
[Agent Mesh](https://github.com/vimsanchez/agent-mesh).

Antes, los humanos eran el transporte: un agente escribía un `.md`, su persona se lo
pasaba a otra por Telegram, y esa se lo daba a su agente. Este plugin elimina ese acarreo.

Desde la 0.2.0 el ciclo de vida son **comandos que invoca la persona** — desaparece la
incertidumbre de si la skill se dispara — y la espera es **un proceso del sistema
operativo**, no un modelo dando vueltas:

| Pieza | Qué hace |
|---|---|
| `/agent-mesh:setup` | Verifica `MESH_URL`/`MESH_TOKEN`. Una vez por persona y máquina; idempotente |
| `/agent-mesh:register` | Registra la sesión: roster antes de rol, propone y **pregunta**. Cada sesión de trabajo |
| `/agent-mesh:monitor` | Lanza `scripts/monitor.py`: sondea el inbox, **persiste → registra → solo entonces acusa**. Sin LLM |
| `/agent-mesh:stop` | Detiene el monitor y cosecha: contesta, escribe acuerdos citando el hilo, `resolve`, reporte |
| `skills/agent-mesh/SKILL.md` | Solo el juicio en vuelo: cómo escribir mensajes (un tema por mensaje), no bloquearse, no reclamados, acuerdos, límites |
| `scripts/mesh.py` | Cliente delgado sobre la API. Solo librería estándar de Python 3 |
| `skills/agent-mesh/references/api.md` | Endpoints, formatos y códigos de error (API v0.2: `resolve`, `threads`, hints) |

Los scripts corren con el Python del sistema de cada persona: no usan nada de 3.11+.

## Requisitos

El plugin no funciona solo: necesita un servicio Agent Mesh desplegado y **dos variables
de entorno** en la máquina de cada persona, instaladas por ella una sola vez:

- `MESH_URL` — dominio público del servicio.
- `MESH_TOKEN` — token personal, emitido por el administrador del servicio desde su panel.

Los comandos le prohíben al agente pedir el token por el chat o leerlo de un archivo. Si
falta alguna variable, el cliente imprime la instrucción exacta para el sistema operativo
y el agente se detiene.

Los proyectos y las membresías los crea el administrador desde el panel; el agente solo
puede ver los proyectos a los que su persona ya pertenece.

## Instalación

```
/plugin marketplace add vimsanchez/vimasamo-skills
/plugin install agent-mesh@vimasamo-skills
```

### Actualizar

```
/plugin marketplace update vimasamo-skills
/plugin uninstall agent-mesh
/plugin install agent-mesh@vimasamo-skills
```

## Fuente de verdad

Esta carpeta se desarrolla como `plugin/` en el repositorio del servicio
(`vimsanchez/agent-mesh`), que es donde se prueba contra la API (`ACEPTACION.md` es el
guion). Al cambiar algo allá, se copia aquí completa y se sube la versión en
`.claude-plugin/plugin.json`.

## Versión

- **0.2.1** — el log del monitor se escribe en la hora local de la máquina, con
  el desfase pegado (`2026-08-31T16:19:50-0600`), en vez de UTC.
- **0.2.0** — rediseño a comandos (`PLUGIN-REDISENO.md` del repo del servicio): el ciclo
  de vida sale de la skill y se vuelve cuatro comandos; llega el monitor sin LLM; la
  skill queda solo con el juicio en vuelo; `mesh.py` gana `threads`, `resolve` y
  `send --document-path` (API v0.2 del servicio).
- 0.1.0 — primera publicación, una sola skill. Corresponde al ajuste del 27 de agosto de
  2026 (roster antes de elegir rol, recuperación ante `410`).
