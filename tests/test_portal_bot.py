"""El bot leyendo promociones del portal (src/agente/portal.py).

Sin red: un HTTP falso devuelve exactamente lo que devolvería el portal.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agente.portal import (  # noqa: E402
    ErrorDePortal,
    crear_herramienta_promociones_portal,
    promociones_del_portal,
)

URL = "https://catalogos.automaticnic.online"
CLAVE = "clave-de-prueba"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100
SHA_PNG = hashlib.sha256(PNG).hexdigest()


def item(**cambios) -> dict:
    return {
        "sku": "PLAN-45", "tipo": "promocion", "nombre": "Plan mensual", "precio": "45.00",
        "moneda": "USD", "unidad": "al mes", "descripcion": "Incluye CRM, app, soporte y capacitación.",
        "vigente_desde": None, "vigente_hasta": "2026-10-11",
        "fotos": [{"id": "foto-1", "mime": "image/png", "bytes": len(PNG), "sha256": SHA_PNG}],
    } | cambios


def contenido(*items) -> dict:
    return {"negocio": {"id": "smarth-house", "nombre": "Smarth House"}, "perfil": {}, "items": list(items)}


class HTTPFalso:
    """Un cliente_http de prueba: registra los pedidos y contesta lo que se le cargó."""

    def __init__(self, catalogo=None, fotos=None, falla_catalogo=False):
        self.catalogo = catalogo
        self.fotos = fotos or {}
        self.falla_catalogo = falla_catalogo
        self.pedidos: list[str] = []

    def __call__(self, metodo: str, url: str) -> bytes:
        self.pedidos.append(url)
        assert metodo == "GET"
        if url.endswith("/api/bot/catalogo"):
            if self.falla_catalogo:
                raise ErrorDePortal("simulado: el portal no contestó.")
            return json.dumps({"version": 1, "contenido": self.catalogo}).encode("utf-8")
        for foto_id, bytes_ in self.fotos.items():
            if url.endswith(f"/api/bot/fotos/{foto_id}"):
                return bytes_
        raise AssertionError(f"pedido inesperado: {url}")


def test_trae_la_promocion_vigente_y_la_foto(tmp_path):
    http = HTTPFalso(catalogo=contenido(item()), fotos={"foto-1": PNG})

    promos = promociones_del_portal(URL, CLAVE, cache_dir=tmp_path, hoy=date(2026, 9, 14), cliente_http=http)

    assert len(promos) == 1
    promo = promos[0]
    assert (promo.codigo, promo.precio, promo.moneda) == ("PLAN-45", "45.00", "USD")
    assert promo.imagen is not None and promo.imagen.ruta.read_bytes() == PNG
    assert http.pedidos == [f"{URL}/api/bot/catalogo", f"{URL}/api/bot/fotos/foto-1"]


def test_no_pide_la_foto_dos_veces(tmp_path):
    http = HTTPFalso(catalogo=contenido(item()), fotos={"foto-1": PNG})
    promociones_del_portal(URL, CLAVE, cache_dir=tmp_path, hoy=date(2026, 9, 14), cliente_http=http)

    promociones_del_portal(URL, CLAVE, cache_dir=tmp_path, hoy=date(2026, 9, 14), cliente_http=http)

    assert http.pedidos.count(f"{URL}/api/bot/fotos/foto-1") == 1


@pytest.mark.parametrize(
    "hoy, esperado",
    [(date(2026, 10, 11), True), (date(2026, 10, 12), False), (date(2026, 1, 1), True)],
)
def test_respeta_la_vigencia(tmp_path, hoy, esperado):
    http = HTTPFalso(catalogo=contenido(item()), fotos={"foto-1": PNG})

    promos = promociones_del_portal(URL, CLAVE, cache_dir=tmp_path, hoy=hoy, cliente_http=http)

    assert bool(promos) is esperado


def test_ignora_lo_que_no_es_promocion_o_no_tiene_precio(tmp_path):
    http = HTTPFalso(catalogo=contenido(
        item(sku="OTRO", tipo="producto"),
        item(sku="SIN-PRECIO", precio=None),
        item(fotos=[]),  # esta prueba es sobre el filtro, no sobre fotos
    ))

    promos = promociones_del_portal(URL, CLAVE, cache_dir=tmp_path, hoy=date(2026, 9, 14), cliente_http=http)

    assert [p.codigo for p in promos] == ["PLAN-45"]


def test_si_el_portal_no_contesta_usa_la_ultima_copia_buena(tmp_path):
    bueno = HTTPFalso(catalogo=contenido(item()), fotos={"foto-1": PNG})
    promociones_del_portal(URL, CLAVE, cache_dir=tmp_path, hoy=date(2026, 9, 14), cliente_http=bueno)

    caido = HTTPFalso(falla_catalogo=True)
    promos = promociones_del_portal(URL, CLAVE, cache_dir=tmp_path, hoy=date(2026, 9, 14), cliente_http=caido)

    assert [p.codigo for p in promos] == ["PLAN-45"]


def test_sin_copia_previa_y_el_portal_caido_avisa_el_problema(tmp_path):
    caido = HTTPFalso(falla_catalogo=True)

    with pytest.raises(ErrorDePortal):
        promociones_del_portal(URL, CLAVE, cache_dir=tmp_path, hoy=date(2026, 9, 14), cliente_http=caido)


def test_una_foto_con_firma_que_no_coincide_no_frena_la_promocion(tmp_path):
    http = HTTPFalso(catalogo=contenido(item()), fotos={"foto-1": b"no es una imagen de verdad"})

    promos = promociones_del_portal(URL, CLAVE, cache_dir=tmp_path, hoy=date(2026, 9, 14), cliente_http=http)

    assert len(promos) == 1 and promos[0].imagen is None


def test_la_herramienta_devuelve_texto_y_el_adjunto(tmp_path):
    http = HTTPFalso(catalogo=contenido(item()), fotos={"foto-1": PNG})
    herramienta = crear_herramienta_promociones_portal(
        URL, CLAVE, cache_dir=tmp_path, hoy_para_pruebas=date(2026, 9, 14), cliente_http=http
    )

    texto, artefacto = herramienta.func()

    assert "PLAN-45" in texto and "US$ 45.00" in texto and "11/10/2026" in texto
    assert "CRM" in texto
    assert len(artefacto["adjuntos"]) == 1 and artefacto["adjuntos"][0]["tipo"] == "archivo_aprobado"


def test_la_herramienta_no_revienta_si_el_portal_esta_caido(tmp_path):
    herramienta = crear_herramienta_promociones_portal(
        URL, CLAVE, cache_dir=tmp_path, hoy_para_pruebas=date(2026, 9, 14),
        cliente_http=HTTPFalso(falla_catalogo=True),
    )

    texto, artefacto = herramienta.func()

    assert "No se pudo validar" in texto and artefacto == {"adjuntos": []}


def test_la_herramienta_dice_cuando_no_hay_promociones(tmp_path):
    herramienta = crear_herramienta_promociones_portal(
        URL, CLAVE, cache_dir=tmp_path, hoy_para_pruebas=date(2026, 9, 14),
        cliente_http=HTTPFalso(catalogo=contenido()),
    )

    texto, artefacto = herramienta.func()

    assert "No hay promociones vigentes" in texto and artefacto == {"adjuntos": []}
