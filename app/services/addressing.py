"""Direcciones públicas de agente: `persona.rol`.

Se usa el rol como dirección, y no un identificador aleatorio, porque permite
escribirle "al de base de datos" sin saber qué sesión concreta está viva
(SPEC §3).

El punto es el separador, y por eso `Person.display_name` no admite puntos: uno
de más volvería ambigua la dirección.
"""

from app.services.errors import ValidationFailedError

SEPARATOR = "."


def format_address(person_name: str, role_label: str) -> str:
    return f"{person_name}{SEPARATOR}{role_label}"


def parse_address(address: str) -> tuple[str, str]:
    """`victor.db` -> `("victor", "db")`.

    Se parte en el **primer** punto: el nombre de persona no lleva puntos, pero
    un rol sí podría, y en ese caso lo que sobra pertenece al rol.
    """
    person, separator, role = address.partition(SEPARATOR)
    if not separator or not person or not role:
        raise ValidationFailedError(
            f"'{address}' no es una dirección válida; usa 'persona.rol', "
            f"por ejemplo 'pablo.general'"
        )
    return person, role
