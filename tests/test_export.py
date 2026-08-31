"""Exportación a Markdown desde el panel: un hilo, un documento, o todo en zip.

Es una vista de solo lectura más (SPEC §10.8): no cambia estados ni registra
nada. Lo que se prueba con más cuidado es que la frontera de proyecto se respete
también aquí: un zip que mezclara proyectos sería la fuga más cómoda de todas.
"""

import io
import re
import zipfile
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Message, Project, Thread
from app.services import export
from tests.test_admin_panel import _admin_listo, _entrar, _escenario_de_agentes

# ------------------------------------------------------------------- servicio


def _hilo_de_juguete() -> tuple[Project, Thread, list[Message]]:
    project = Project(id="prj_1", slug="proyecto-pablo", name="Pedidos")
    thread = Thread(
        id="thr_9b419da7467a9bf5012c9d59",
        project_id="prj_1",
        subject="Paginación de /v1/orders: ¿cursor u offset?",
        status="resolved",
        created_at=datetime(2026, 8, 27, 15, 40, tzinfo=UTC),
        updated_at=datetime(2026, 8, 27, 15, 41, tzinfo=UTC),
    )
    mensajes = [
        Message(
            id="msg_1",
            project_id="prj_1",
            thread_id=thread.id,
            sender_address="pablo.general",
            recipient_address="victor.general",
            kind="question",
            subject="Paginación de /v1/orders",
            body="¿cursor u offset? Propongo cursor.",
            status="answered",
            created_at=datetime(2026, 8, 27, 15, 40, 3, tzinfo=UTC),
        ),
        Message(
            id="msg_2",
            project_id="prj_1",
            thread_id=thread.id,
            sender_address="victor.general",
            recipient_address=None,
            kind="answer",
            subject="Re: Paginación",
            body="Cursor. Acordado.",
            status="delivered",
            created_at=datetime(2026, 8, 27, 15, 41, 0, tzinfo=UTC),
        ),
    ]
    return project, thread, mensajes


def test_el_nombre_del_archivo_es_legible_y_unico() -> None:
    _, thread, _ = _hilo_de_juguete()

    nombre = export.thread_filename(thread)

    assert nombre == "2026-08-27-paginacion-de-v1-orders-cursor-u-offset-9d59.md"
    assert re.fullmatch(r"[a-z0-9.-]+", nombre), "solo ASCII seguro para cabeceras y zips"


def test_el_nombre_usa_el_dia_del_calendario_de_quien_exporta() -> None:
    """Un hilo de madrugada UTC pertenece al día anterior en la zona del panel.

    Sin convertir, el archivo saldría fechado un día después de la conversación
    que contiene, y quien lo archiva no lo encontraría donde lo busca.
    """
    _, thread, _ = _hilo_de_juguete()
    thread.created_at = datetime(2026, 9, 1, 3, 30, tzinfo=UTC)  # 21:30 del 31-ago en CDMX

    assert export.thread_filename(thread).startswith("2026-08-31-")


def test_el_hilo_en_markdown_trae_cabecera_y_un_bloque_por_mensaje() -> None:
    project, thread, mensajes = _hilo_de_juguete()

    md = export.thread_markdown(project, thread, mensajes)

    assert md.startswith("# Paginación de /v1/orders: ¿cursor u offset?\n")
    assert "Proyecto: proyecto-pablo" in md
    assert "Estado: resolved" in md
    assert "2 mensajes" in md
    # En la zona del panel (DISPLAY_TIMEZONE), no en UTC: el export lo lee una
    # persona. 15:40 UTC son las 09:40 en Ciudad de México.
    assert "## 1. pablo.general → victor.general · question · 2026-08-27 09:40 CST" in md
    assert "## 2. victor.general → (sin destinatario) · answer · 2026-08-27 09:41 CST" in md
    assert "¿cursor u offset? Propongo cursor." in md
    assert "Cursor. Acordado." in md
    assert md.endswith("\n")


def test_el_documento_se_exporta_tal_cual() -> None:
    """Ya es Markdown y la idea es que sirva pegado en un repo: sin cabecera
    añadida. La metadata va al índice del zip."""
    assert (
        export.document_markdown("# Contrato\n\nPor cursor.") == "# Contrato\n\nPor cursor.\n"
    )
    assert export.document_markdown("") == ""


def test_el_zip_conserva_la_estructura_del_proyecto() -> None:
    project, thread, mensajes = _hilo_de_juguete()
    docs = [
        (
            export.DocumentInfo(
                path="20-contracts/api-orders.md",
                title="API orders",
                version=7,
                status="active",
                updated_at=thread.updated_at,
            ),
            "# API orders\n",
        ),
        (
            export.DocumentInfo(
                path="00-conventions/messaging.md",
                title="Mensajería",
                version=1,
                status="active",
                updated_at=thread.updated_at,
            ),
            "# Mensajería\n",
        ),
    ]

    contenido = export.project_zip(project, threads=[(thread, mensajes)], documents=docs)

    with zipfile.ZipFile(io.BytesIO(contenido)) as z:
        nombres = sorted(z.namelist())
        assert nombres == [
            "proyecto-pablo/INDEX.md",
            "proyecto-pablo/docs/00-conventions/messaging.md",
            "proyecto-pablo/docs/20-contracts/api-orders.md",
            "proyecto-pablo/threads/2026-08-27-paginacion-de-v1-orders-cursor-u-offset-9d59.md",
        ]
        indice = z.read("proyecto-pablo/INDEX.md").decode()
        assert "## Hilos" in indice and "## Documentos" in indice
        assert "20-contracts/api-orders.md" in indice and "v7" in indice
        assert "threads/2026-08-27-paginacion" in indice, "el índice enlaza al archivo"
        assert (
            z.read("proyecto-pablo/docs/20-contracts/api-orders.md").decode()
            == "# API orders\n"
        )


def test_el_zip_parcial_solo_lleva_lo_pedido() -> None:
    project, thread, mensajes = _hilo_de_juguete()

    solo_hilos = export.project_zip(project, threads=[(thread, mensajes)], documents=None)
    solo_docs = export.project_zip(project, threads=None, documents=[])

    with zipfile.ZipFile(io.BytesIO(solo_hilos)) as z:
        indice = z.read("proyecto-pablo/INDEX.md").decode()
        assert "## Hilos" in indice and "## Documentos" not in indice
        assert any(n.startswith("proyecto-pablo/threads/") for n in z.namelist())
    with zipfile.ZipFile(io.BytesIO(solo_docs)) as z:
        indice = z.read("proyecto-pablo/INDEX.md").decode()
        assert "## Documentos" in indice and "## Hilos" not in indice
        assert "Todavía no hay documentos" in indice


# ----------------------------------------------------------------------- panel


def _ids(client: TestClient, slug: str) -> tuple[str, str]:
    hilos = client.get(f"/admin/projects/{slug}/threads").text
    docs = client.get(f"/admin/projects/{slug}/docs").text
    thread_id = re.search(r"thr_[a-f0-9]+", hilos)
    doc_id = re.search(r"doc_[a-f0-9]+", docs)
    assert thread_id and doc_id
    return thread_id.group(0), doc_id.group(0)


def test_descargar_un_hilo(client: TestClient, db: Session) -> None:
    slug, _ = _escenario_de_agentes(client, db)
    _admin_listo(db)
    _entrar(client, "jefe@empresa-interna.test")
    thread_id, _ = _ids(client, slug)

    respuesta = client.get(f"/admin/projects/{slug}/threads/{thread_id}/download")

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("text/markdown")
    disposicion = respuesta.headers["content-disposition"]
    assert disposicion.startswith("attachment; filename=")
    assert disposicion.endswith('.md"')
    assert "Cuerpo largo." in respuesta.text
    assert "victor.db → pablo.general · question" in respuesta.text


def test_descargar_un_documento(client: TestClient, db: Session) -> None:
    slug, _ = _escenario_de_agentes(client, db)
    _admin_listo(db)
    _entrar(client, "jefe@empresa-interna.test")
    _, doc_id = _ids(client, slug)

    respuesta = client.get(f"/admin/projects/{slug}/docs/{doc_id}/download")

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("text/markdown")
    assert 'filename="api-orders.md"' in respuesta.headers["content-disposition"]
    assert respuesta.text == "# Contrato\n\nPor cursor.\n"


def test_descargar_todo_el_proyecto(client: TestClient, db: Session) -> None:
    slug, _ = _escenario_de_agentes(client, db)
    _admin_listo(db)
    _entrar(client, "jefe@empresa-interna.test")

    respuesta = client.get(f"/admin/projects/{slug}/export.zip")

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"] == "application/zip"
    assert 'filename="proyecto-pablo.zip"' in respuesta.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(respuesta.content)) as z:
        nombres = z.namelist()
        assert "proyecto-pablo/INDEX.md" in nombres
        assert "proyecto-pablo/docs/20-contracts/api-orders.md" in nombres
        assert sum(n.startswith("proyecto-pablo/threads/") for n in nombres) == 1


def test_los_zips_parciales(client: TestClient, db: Session) -> None:
    slug, _ = _escenario_de_agentes(client, db)
    _admin_listo(db)
    _entrar(client, "jefe@empresa-interna.test")

    hilos = client.get(f"/admin/projects/{slug}/threads.zip")
    docs = client.get(f"/admin/projects/{slug}/docs.zip")

    assert 'filename="proyecto-pablo-hilos.zip"' in hilos.headers["content-disposition"]
    assert 'filename="proyecto-pablo-docs.zip"' in docs.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(hilos.content)) as z:
        assert not any("/docs/" in n for n in z.namelist())
    with zipfile.ZipFile(io.BytesIO(docs.content)) as z:
        assert not any("/threads/" in n for n in z.namelist())


def test_el_zip_de_un_proyecto_no_incluye_otro(client: TestClient, db: Session) -> None:
    """La frontera dura, también al exportar."""
    _escenario_de_agentes(client, db)
    from app.services import identity as ident

    otro = ident.create_project(db, slug="proyecto-luis", name="Portal")
    db.commit()
    _admin_listo(db)
    _entrar(client, "jefe@empresa-interna.test")

    respuesta = client.get(f"/admin/projects/{otro.slug}/export.zip")

    with zipfile.ZipFile(io.BytesIO(respuesta.content)) as z:
        nombres = z.namelist()
        assert nombres == ["proyecto-luis/INDEX.md"]
        assert "api-orders" not in z.read(nombres[0]).decode()


def test_un_hilo_de_otro_proyecto_no_se_descarga(client: TestClient, db: Session) -> None:
    slug, _ = _escenario_de_agentes(client, db)
    from app.services import identity as ident

    otro = ident.create_project(db, slug="proyecto-luis", name="Portal")
    db.commit()
    _admin_listo(db)
    _entrar(client, "jefe@empresa-interna.test")
    thread_id, doc_id = _ids(client, slug)

    hilo = client.get(
        f"/admin/projects/{otro.slug}/threads/{thread_id}/download", follow_redirects=False
    )
    doc = client.get(
        f"/admin/projects/{otro.slug}/docs/{doc_id}/download", follow_redirects=False
    )

    assert hilo.status_code == 303
    assert hilo.headers["location"] == f"/admin/projects/{otro.slug}/threads"
    assert doc.status_code == 303
    assert doc.headers["location"] == f"/admin/projects/{otro.slug}/docs"


def test_las_descargas_exigen_sesion(client: TestClient, db: Session) -> None:
    slug, _ = _escenario_de_agentes(client, db)

    for ruta in (
        f"/admin/projects/{slug}/export.zip",
        f"/admin/projects/{slug}/threads.zip",
        f"/admin/projects/{slug}/docs.zip",
    ):
        respuesta = client.get(ruta, follow_redirects=False)
        assert respuesta.status_code == 303, ruta
        assert respuesta.headers["location"] == "/admin/login", ruta


def test_cada_pagina_ofrece_la_descarga_que_le_toca(client: TestClient, db: Session) -> None:
    """El botón vive junto a lo que descarga: la lista trae uno por fila y uno
    para el conjunto; el proyecto, uno junto a cada sección."""
    slug, _ = _escenario_de_agentes(client, db)
    _admin_listo(db)
    _entrar(client, "jefe@empresa-interna.test")
    thread_id, doc_id = _ids(client, slug)

    proyecto = client.get(f"/admin/projects/{slug}").text
    hilos = client.get(f"/admin/projects/{slug}/threads").text
    docs = client.get(f"/admin/projects/{slug}/docs").text

    assert f"/admin/projects/{slug}/export.zip" in proyecto
    assert (
        f"/admin/projects/{slug}/threads.zip" in proyecto
        and f"/admin/projects/{slug}/docs.zip" in proyecto
    )
    assert f"/admin/projects/{slug}/threads.zip" in hilos
    assert f"/admin/projects/{slug}/threads/{thread_id}/download" in hilos, "uno por fila"
    assert f"/admin/projects/{slug}/docs.zip" in docs
    assert f"/admin/projects/{slug}/docs/{doc_id}/download" in docs, "uno por fila"
