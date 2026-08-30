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
