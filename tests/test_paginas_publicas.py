"""Las páginas públicas que Google exige para publicar la app de OAuth.

Sin ellas no se puede sacar la app del estado «Prueba», y en Prueba el
refresh token de Calendar vence cada siete días. Se prueban acá porque son
parte del contenedor que atiende WhatsApp: si devuelven un error, el bot
sigue andando y nadie se entera hasta que Google rechaza la publicación.
"""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from test_agente import agente_falso
from agente.web.webhook import crear_app

PUBLICAS = ("/", "/privacidad", "/terminos")


@pytest.fixture
def cliente():
    agente = agente_falso(["hola"])
    agente.config = replace(
        agente.config,
        chatwoot_url="https://chatwoot.ejemplo.com",
        chatwoot_token="tecnico-falso",
        chatwoot_webhook_token="secreto-de-prueba",
    )
    # Sin context manager a propósito: así no arranca el lifespan ni el
    # trabajador de agenda, que saldrían a la red. Estas rutas son estáticas.
    return TestClient(crear_app(agente.config, agente=agente))


@pytest.mark.parametrize("ruta", PUBLICAS)
def test_las_paginas_publicas_responden_html(cliente, ruta):
    respuesta = cliente.get(ruta)
    assert respuesta.status_code == 200
    assert "text/html" in respuesta.headers["content-type"]


def test_la_politica_declara_el_uso_limitado_de_los_datos_de_google(cliente):
    # Google busca esta declaración al revisar un alcance sensible como
    # calendar.events. Sin ella la publicación se rechaza.
    cuerpo = cliente.get("/privacidad").text
    assert "api-services-user-data-policy" in cuerpo
    assert "uso limitado" in cuerpo.lower()


def test_la_politica_explica_como_revocar_el_acceso(cliente):
    assert "myaccount.google.com/permissions" in cliente.get("/privacidad").text


@pytest.mark.parametrize("ruta", PUBLICAS)
def test_cada_pagina_ofrece_un_contacto(cliente, ruta):
    assert "mailto:" in cliente.get(ruta).text


@pytest.mark.parametrize("ruta", PUBLICAS)
def test_las_paginas_no_filtran_configuracion(cliente, ruta):
    # Son accesibles sin autenticación: no pueden revelar nada del montaje.
    cuerpo = cliente.get(ruta).text.lower()
    for secreto in ("token", "chatwoot", "secreto", "dsn", "postgres"):
        assert secreto not in cuerpo


def test_el_webhook_sigue_protegido(cliente):
    # Agregar páginas públicas no puede haber abierto la puerta de Chatwoot.
    assert cliente.post("/chatwoot/equivocado", json={}).status_code == 401
