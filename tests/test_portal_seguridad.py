"""Contraseñas, límite de intentos y almacén de fotos del portal."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from portal.almacen import MAXIMO_FOTO, Almacen, FotoInvalida  # noqa: E402
from portal.seguridad import (  # noqa: E402
    ClaveDebil,
    LimiteDeIntentos,
    hashear_clave,
    huella,
    validar_clave_nueva,
    verificar_clave,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100
JPG = b"\xff\xd8\xff" + b"0" * 100


def test_la_contrasena_se_verifica_sin_guardarse_en_claro():
    guardada = hashear_clave("una clave larga")

    assert "una clave larga" not in guardada
    assert verificar_clave("una clave larga", guardada)
    assert not verificar_clave("otra clave larga", guardada)
    assert hashear_clave("una clave larga") != guardada  # cada una con su sal


@pytest.mark.parametrize("guardada", ["", "texto", "bcrypt$1$2$3$4$5", "scrypt$x$8$1$aaaa$bbbb"])
def test_un_hash_roto_no_deja_entrar(guardada):
    assert not verificar_clave("una clave larga", guardada)


def test_una_contrasena_gigante_ni_se_procesa():
    assert not verificar_clave("a" * 10_000, hashear_clave("a" * 100))


def test_la_contrasena_nueva_tiene_minimo():
    with pytest.raises(ClaveDebil):
        validar_clave_nueva("corta")
    assert validar_clave_nueva("suficientemente-larga")


def test_de_una_sesion_se_guarda_la_huella_y_no_el_token():
    assert huella("token") != "token"
    assert huella("token") == huella("token")


def test_el_limite_bloquea_y_despues_vence():
    reloj = [0.0]
    limite = LimiteDeIntentos(maximo=3, ventana_segundos=60, reloj=lambda: reloj[0])

    for _ in range(3):
        assert not limite.bloqueado("correo:a")
        limite.registrar_fallo("correo:a")

    assert limite.bloqueado("correo:a")
    assert not limite.bloqueado("correo:b")
    reloj[0] = 61
    assert not limite.bloqueado("correo:a")


def test_el_almacen_guarda_png_y_jpg_en_la_carpeta_del_negocio(tmp_path):
    almacen = Almacen(tmp_path)

    guardado = almacen.guardar("smarth-house", PNG)

    assert guardado.mime == "image/png"
    assert guardado.clave.startswith("smarth-house/") and guardado.clave.endswith(".png")
    assert guardado.bytes == len(PNG) and len(guardado.id) == 32
    assert almacen.leer(guardado.clave) == PNG
    assert almacen.guardar("smarth-house", JPG).mime == "image/jpeg"


@pytest.mark.parametrize("contenido", [b"", b"GIF89a" + b"0" * 20, b"<html></html>", PNG[:4]])
def test_el_almacen_rechaza_lo_que_no_es_foto(tmp_path, contenido):
    with pytest.raises(FotoInvalida):
        Almacen(tmp_path).guardar("smarth-house", contenido)


def test_el_almacen_rechaza_fotos_de_mas_de_5_mb(tmp_path):
    with pytest.raises(FotoInvalida, match="5 MB"):
        Almacen(tmp_path).guardar("smarth-house", PNG + b"0" * MAXIMO_FOTO)


@pytest.mark.parametrize(
    "clave",
    ["../secreto.png", "smarth-house/../../x.png", "smarth-house/" + "a" * 32 + ".exe", "/etc/passwd"],
)
def test_el_almacen_no_lee_fuera_de_su_carpeta(tmp_path, clave):
    with pytest.raises(FotoInvalida):
        Almacen(tmp_path).leer(clave)


def test_el_almacen_no_acepta_un_negocio_inventado(tmp_path):
    with pytest.raises(FotoInvalida):
        Almacen(tmp_path).guardar("../otro", PNG)
