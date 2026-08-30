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
