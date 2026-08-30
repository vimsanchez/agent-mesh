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
