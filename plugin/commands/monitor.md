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
