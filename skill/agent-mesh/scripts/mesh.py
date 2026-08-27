#!/usr/bin/env python3
"""Cliente delgado para Agent Mesh. Solo librería estándar.

Uso:
    python mesh.py projects
    python mesh.py register --project <slug> --role <etiqueta>
    python mesh.py inbox --wait 30
    python mesh.py send --to pablo.general --kind question \
        --subject "..." --body-file /tmp/p.md

Requiere MESH_URL y MESH_TOKEN en el entorno. El token NUNCA se lee de un archivo
ni se guarda en disco: solo del entorno del proceso.
El estado de la sesión se guarda en .agent-mesh/session.json del directorio actual.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

STATE_DIR = Path.cwd() / ".agent-mesh"
STATE_FILE = STATE_DIR / "session.json"


# --------------------------------------------------------------------------- io

def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def base_url() -> str:
    url = os.environ.get("MESH_URL")
    if not url:
        die(env_help("MESH_URL", "https://mesh.ejemplo.com"))
    return url.rstrip("/") + "/api/v1"


def env_help(var: str, example: str) -> str:
    """Instrucción de configuración según el sistema operativo.

    Los secretos viven SOLO en el entorno. El cliente nunca los lee de un archivo
    ni los escribe en disco.
    """
    if os.name == "nt":
        return (
            f"{var} no está configurada.\n"
            f"  PowerShell (permanente, usuario actual):\n"
            f"    [Environment]::SetEnvironmentVariable('{var}', '{example}', 'User')\n"
            f"  cmd.exe:\n"
            f"    setx {var} \"{example}\"\n"
            f"  Cierra y vuelve a abrir la terminal para que tome efecto."
        )
    shell = os.environ.get("SHELL", "")
    rc = "~/.zshrc" if shell.endswith("zsh") else "~/.bashrc"
    return (
        f"{var} no está configurada.\n"
        f"  Agrega esta línea a {rc}:\n"
        f"    export {var}=\"{example}\"\n"
        f"  Luego: source {rc}"
    )


def token() -> str:
    tok = os.environ.get("MESH_TOKEN")
    if not tok:
        die(env_help("MESH_TOKEN", "<tu-token-personal>"))
    return tok


def load_session() -> dict:
    if not STATE_FILE.exists():
        die("no hay sesión registrada; corre primero: mesh.py register --project X --role Y")
    return json.loads(STATE_FILE.read_text())


def save_session(data: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2))


def emit(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def read_content(inline: str | None, path: str | None, label: str) -> str:
    if path:
        return Path(path).read_text()
    if inline is not None:
        return inline
    die(f"falta --{label} o --{label}-file")
    return ""  # inalcanzable


# ------------------------------------------------------------------------ http

def request(method: str, path: str, body: dict | None = None,
            params: dict | None = None, with_session: bool = True,
            timeout: int = 60) -> dict:
    url = base_url() + path
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url += "?" + urllib.parse.urlencode(clean)

    headers = {
        "Authorization": f"Bearer {token()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if with_session and STATE_FILE.exists():
        headers["X-Mesh-Session"] = load_session()["session_key"]

    payload = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=payload, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {"status": resp.status}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            detail = json.loads(raw)
        except Exception:
            detail = {"detail": raw.decode(errors="replace")}
        emit({"http_status": exc.code, **detail})
        # 409 en claim no es fallo real; el que llama decide qué hacer.
        sys.exit(2 if exc.code == 409 else 1)
    except urllib.error.URLError as exc:
        die(f"no se pudo conectar con {base_url()}: {exc.reason}")
        return {}


# -------------------------------------------------------------------- comandos

def cmd_projects(a):
    """Proyectos donde la persona dueña del token ya es miembro.

    No crea nada. Si la lista viene vacía, la persona no ha sido agregada a ningún
    proyecto y debe pedírselo a su administrador.
    """
    emit(request("GET", "/projects", with_session=False))


def cmd_register(a):
    out = request("POST", "/sessions",
                  {"project": a.project, "role": a.role}, with_session=False)
    save_session({"session_key": out["session_key"],
                  "address": out["address"],
                  "project": out["project"]})
    emit(out)


def cmd_heartbeat(a):
    s = load_session()
    emit(request("POST", f"/sessions/{s['session_key']}/heartbeat"))


def cmd_close(a):
    s = load_session()
    emit(request("DELETE", f"/sessions/{s['session_key']}"))
    STATE_FILE.unlink(missing_ok=True)


def cmd_roster(a):
    s = load_session()
    emit(request("GET", f"/projects/{s['project']}/roster"))


def cmd_send(a):
    body = {
        "to": a.to,
        "kind": a.kind,
        "subject": a.subject,
        "body": read_content(a.body, a.body_file, "body"),
        "in_reply_to": a.reply_to,
        "thread_id": a.thread,
    }
    emit(request("POST", "/messages", {k: v for k, v in body.items() if v is not None}))


def cmd_inbox(a):
    emit(request("GET", "/inbox", params={"wait": a.wait}, timeout=a.wait + 15))


def cmd_ack(a):
    emit(request("POST", f"/messages/{a.id}/ack"))


def cmd_progress(a):
    emit(request("POST", f"/messages/{a.id}/progress"))


def cmd_unclaimed(a):
    emit(request("GET", "/unclaimed"))


def cmd_claim(a):
    emit(request("POST", f"/messages/{a.id}/claim"))


def cmd_dismiss(a):
    emit(request("POST", f"/messages/{a.id}/dismiss"))


def cmd_thread(a):
    emit(request("GET", f"/threads/{a.id}"))


def cmd_docs(a):
    s = load_session()
    emit(request("GET", f"/projects/{s['project']}/docs"))


def cmd_doc(a):
    emit(request("GET", "/docs", params={"path": a.path}))


def cmd_contribute(a):
    emit(request("POST", "/docs/contributions", {
        "document_path": a.path,
        "base_version": a.base_version,
        "intent": a.intent,
        "anchor": a.anchor,
        "content": read_content(a.content, a.content_file, "content"),
        "rationale": a.rationale,
    }))


def cmd_versions(a):
    emit(request("GET", f"/docs/{a.id}/versions"))


# ---------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mesh", description="Cliente de Agent Mesh")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("projects", help="Proyectos de tu persona").set_defaults(func=cmd_projects)

    r = sub.add_parser("register", help="Registra esta sesión")
    r.add_argument("--project", required=True)
    r.add_argument("--role", required=True)
    r.set_defaults(func=cmd_register)

    sub.add_parser("heartbeat", help="Mantiene viva la sesión").set_defaults(func=cmd_heartbeat)
    sub.add_parser("close", help="Cierra la sesión").set_defaults(func=cmd_close)
    sub.add_parser("roster", help="Quién está vivo").set_defaults(func=cmd_roster)
    sub.add_parser("unclaimed", help="Bandeja de no reclamados").set_defaults(func=cmd_unclaimed)
    sub.add_parser("docs", help="Índice de documentos").set_defaults(func=cmd_docs)

    s = sub.add_parser("send", help="Envía un mensaje")
    s.add_argument("--to")
    s.add_argument("--kind", default="question",
                   choices=["question", "answer", "notice", "proposal", "agreement"])
    s.add_argument("--subject", required=True)
    s.add_argument("--body")
    s.add_argument("--body-file")
    s.add_argument("--reply-to")
    s.add_argument("--thread")
    s.set_defaults(func=cmd_send)

    i = sub.add_parser("inbox", help="Long poll de mensajes")
    i.add_argument("--wait", type=int, default=30)
    i.set_defaults(func=cmd_inbox)

    for name, fn, helptext in [
        ("ack", cmd_ack, "Confirma recepción"),
        ("progress", cmd_progress, "Marca en proceso"),
        ("claim", cmd_claim, "Reclama un mensaje"),
        ("dismiss", cmd_dismiss, "Descarta un mensaje"),
        ("thread", cmd_thread, "Muestra un hilo"),
        ("versions", cmd_versions, "Historial de un documento"),
    ]:
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("--id", required=True)
        sp.set_defaults(func=fn)

    d = sub.add_parser("doc", help="Lee un documento")
    d.add_argument("--path", required=True)
    d.set_defaults(func=cmd_doc)

    c = sub.add_parser("contribute", help="Aporta a un documento")
    c.add_argument("--path", required=True)
    c.add_argument("--base-version", type=int, required=True)
    c.add_argument("--intent", required=True,
                   choices=["create", "append", "amend", "deprecate"])
    c.add_argument("--anchor")
    c.add_argument("--content")
    c.add_argument("--content-file")
    c.add_argument("--rationale", required=True)
    c.set_defaults(func=cmd_contribute)

    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    args.func(args)
