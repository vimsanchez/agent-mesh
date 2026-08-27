"""M3: hashing de contraseñas y de tokens.

Las dos decisiones que este paso tenía que cerrar, con su prueba.
"""

import time

from app.security import passwords, tokens

# ------------------------------------------------------- contraseñas de admin


def test_el_hash_no_contiene_la_contraseña() -> None:
    hashed = passwords.hash_password("contraseña-larguisima-1")

    assert "contraseña-larguisima-1" not in hashed


def test_es_argon2id() -> None:
    """Regla 7: Argon2id, no MD5 ni SHA suelto."""
    assert passwords.hash_password("x" * 14).startswith("$argon2id$")


def test_dos_hashes_de_la_misma_contraseña_difieren() -> None:
    """Con sal. Si coincidieran, un atacante podría agrupar cuentas iguales."""
    uno = passwords.hash_password("misma-contraseña-12")
    otro = passwords.hash_password("misma-contraseña-12")

    assert uno != otro
    assert passwords.verify_password("misma-contraseña-12", uno)
    assert passwords.verify_password("misma-contraseña-12", otro)


def test_verify_rechaza_la_contraseña_incorrecta() -> None:
    hashed = passwords.hash_password("la-correcta-123")

    assert not passwords.verify_password("la-incorrecta-123", hashed)


def test_verify_no_explota_con_un_hash_corrupto() -> None:
    """Una fila mal escrita en la base no debe tumbar el login con un 500."""
    assert not passwords.verify_password("x", "esto-no-es-un-hash")
    assert not passwords.verify_password("x", "")


# ------------------------------------------------------------ tokens de agente


def test_el_token_lleva_prefijo_reconocible() -> None:
    """Para que un token filtrado en un log se identifique de inmediato."""
    assert tokens.new_token().startswith("amt_")


def test_dos_tokens_nunca_coinciden() -> None:
    assert len({tokens.new_token() for _ in range(200)}) == 200


def test_el_hash_del_token_es_determinista() -> None:
    """Es lo que permite buscarlo por índice único en un solo lookup."""
    plain = tokens.new_token()

    assert tokens.hash_token(plain) == tokens.hash_token(plain)
    assert tokens.hash_token(plain) != tokens.hash_token(tokens.new_token())


def test_el_hash_del_token_no_contiene_el_token() -> None:
    plain = tokens.new_token()

    assert plain not in tokens.hash_token(plain)
    assert plain.removeprefix("amt_") not in tokens.hash_token(plain)


def test_looks_like_token_descarta_basura_sin_tocar_la_base() -> None:
    assert not tokens.looks_like_token("")
    assert not tokens.looks_like_token("Bearer algo")
    assert not tokens.looks_like_token("amt_corto")
    assert tokens.looks_like_token(tokens.new_token())


def test_hashear_un_token_es_barato() -> None:
    """La razón de no usar Argon2 aquí: esto corre en CADA petición.

    El umbral es holgado a propósito para no volverse una prueba inestable en una
    máquina cargada; con Argon2 (cientos de ms por llamada) sería imposible de
    cumplir por dos órdenes de magnitud.
    """
    plain = tokens.new_token()

    inicio = time.perf_counter()
    for _ in range(1000):
        tokens.hash_token(plain)
    transcurrido = time.perf_counter() - inicio

    assert transcurrido < 0.5, f"1000 hashes tardaron {transcurrido:.3f}s"
