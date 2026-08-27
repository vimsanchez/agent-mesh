"""Dependencias del panel: quién está dentro y si puede seguir.

La sesión del panel es una cookie firmada, no una fila en la base: no hay tabla
para eso en SPEC §7 y añadirla sería salirse del esquema acordado. La cookie solo
guarda el id del administrador; todo lo demás se relee de la base en cada
petición, así que desactivar una cuenta surte efecto de inmediato.
"""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db.models import AdminUser
from app.db.session import get_db

SESSION_ADMIN_KEY = "admin_id"


class RedirectToLoginError(Exception):
    """El panel no devuelve 401: redirige al login.

    Es una excepción y no un `return` porque se lanza desde una dependencia, que
    no puede devolver una respuesta.
    """

    def __init__(self, to: str = "/admin/login") -> None:
        self.to = to
        super().__init__(to)


def redirect(to: str) -> RedirectResponse:
    """303 y no 302: tras un POST, el navegador debe seguir con GET."""
    return RedirectResponse(url=to, status_code=303)


def current_admin(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> AdminUser:
    """El administrador de la cookie, releído de la base.

    No exige contraseña cambiada: eso lo hace `active_admin`. Separarlos permite
    que la propia pantalla de cambio de contraseña sepa quién es sin caer en un
    bucle de redirecciones.
    """
    admin_id = request.session.get(SESSION_ADMIN_KEY)
    if not admin_id:
        raise RedirectToLoginError
    admin = db.get(AdminUser, admin_id)
    if admin is None or not admin.is_active:
        request.session.clear()
        raise RedirectToLoginError
    return admin


def active_admin(
    admin: Annotated[AdminUser, Depends(current_admin)],
) -> AdminUser:
    """Como `current_admin`, pero además con la contraseña ya cambiada.

    El admin de bootstrap nace con `must_change_password=True` y su contraseña
    salió impresa en un log; dejarlo navegar el panel con ella sería dejar la
    puerta abierta a quien haya leído ese log.
    """
    if admin.must_change_password:
        raise RedirectToLoginError("/admin/password")
    return admin


CurrentAdmin = Annotated[AdminUser, Depends(current_admin)]
ActiveAdmin = Annotated[AdminUser, Depends(active_admin)]
Db = Annotated[Session, Depends(get_db)]
