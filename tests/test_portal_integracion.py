"""Catálogo publicado → herramientas → memoria y salida, sin red ni tokens."""

import json
from dataclasses import replace
from datetime import date

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from test_agente import ModeloFalso, agente_falso
from test_portal_app import armar, entrar, crear_con_foto, CABECERA, CLAVE_BOT, bot
from test_portal_bot import URL, CLAVE, PNG, contenido, item, HTTPFalso
from agente.config import ErrorDeConfiguracion
from agente.fuente_portal import (
    FuentePortal, ErrorDePortal, PortalNoDisponible, AccesoAlPortalRechazado,
)
from agente.portal import crear_herramientas_portal
from agente.herramientas import herramientas_para

HOY = date(2026, 9, 14)


def herramientas(tmp_path, *items, perfil=None, reglas=None, hoy=HOY):
    datos = contenido(*items)
    datos["perfil"] = perfil or {}
    datos["reglas"] = reglas or {}
    http = HTTPFalso(datos, {"foto-1": PNG})
    tools = crear_herramientas_portal(
        URL, CLAVE, negocio_id="smarth-house", cache_dir=tmp_path,
        hoy_para_pruebas=hoy, cliente_http=http,
    )
    return {t.name: t for t in tools}, http


def test_claves_y_origenes_no_comparten_respaldo(tmp_path):
    http = HTTPFalso(contenido(item(fotos=[])))
    FuentePortal(URL, CLAVE, cache_dir=tmp_path, cliente_http=http).leer()
    http.falla_catalogo = True
    for url, clave in [(URL, "otro-negocio"), ("https://otro.example", CLAVE)]:
        with pytest.raises(ErrorDePortal):
            FuentePortal(url, clave, cache_dir=tmp_path, cliente_http=http).leer()


def test_rechaza_clave_de_otro_negocio_aunque_devuelva_datos(tmp_path):
    with pytest.raises(ErrorDePortal, match="otro negocio"):
        FuentePortal(
            URL, CLAVE, negocio_id="otro-negocio", cache_dir=tmp_path,
            cliente_http=HTTPFalso(contenido(item(fotos=[]))),
        ).leer()


def test_respaldo_caduca_y_no_permite_cotizar(tmp_path):
    tiempo = [1000]
    http = HTTPFalso(contenido(item(fotos=[])))
    fuente = FuentePortal(URL, CLAVE, cache_dir=tmp_path, cliente_http=http, reloj=lambda: tiempo[0])
    fuente.leer()
    http.falla_catalogo = True
    assert fuente.leer()["_respaldo"] is True
    with pytest.raises(PortalNoDisponible):
        fuente.leer(permitir_respaldo=False)
    tiempo[0] += 301
    with pytest.raises(ErrorDePortal):
        fuente.leer()


def test_clave_revocada_invalida_el_respaldo(tmp_path):
    fuente = FuentePortal(
        URL, CLAVE, cache_dir=tmp_path, cliente_http=HTTPFalso(contenido(item(fotos=[])))
    )
    fuente.leer()

    def rechazar(*args):
        raise AccesoAlPortalRechazado()

    fuente.http = rechazar
    with pytest.raises(AccesoAlPortalRechazado):
        fuente.leer()
    fuente.http = HTTPFalso(falla_catalogo=True)
    with pytest.raises(ErrorDePortal):
        fuente.leer()


def test_foto_con_png_valido_pero_huella_distinta_no_se_envia(tmp_path):
    tools, http = herramientas(tmp_path, item())
    http.fotos = {"a" * 32: PNG + b"otra-foto"}
    texto, artefacto = tools["mostrar_fotos"].func(["PLAN-45"])
    assert artefacto == {"adjuntos": []}
    assert "sin foto disponible" in texto


def test_archivo_cache_alterado_se_descarga_de_nuevo(tmp_path):
    fuente = FuentePortal(
        URL, CLAVE, cache_dir=tmp_path,
        cliente_http=HTTPFalso(contenido(item()), {"foto-1": PNG}),
    )
    datos = fuente.leer()
    foto = fuente.foto(datos, datos["items"][0])
    foto.ruta.write_bytes(b"otro-contenido")
    assert fuente.foto(datos, datos["items"][0]).ruta.read_bytes() == PNG


def test_no_convierte_un_servicio_regular_en_promocion(tmp_path):
    tools, _ = herramientas(tmp_path, item(tipo="servicio", vigente_hasta=None))
    texto, artefacto = tools["promociones_disponibles"].func()
    assert "No hay promociones vigentes" in texto
    assert "Servicios regulares publicados" in texto and "US$ 45.00" in texto
    assert len(artefacto["adjuntos"]) == 1


def test_vence_la_promocion_y_ofrece_el_plan_regular_publicado(tmp_path):
    tools, _ = herramientas(
        tmp_path, item(), item(sku="PLAN-REGULAR", tipo="servicio", precio="70.00", vigente_hasta=None),
        hoy=date(2026, 10, 12),
    )
    texto, _ = tools["promociones_disponibles"].func()
    assert "PLAN-REGULAR" in texto and "PLAN-45" not in texto


def test_cotiza_opciones_extras_descuento_y_adjunta_foto(tmp_path):
    tools, _ = herramientas(
        tmp_path, item(
            tipo="producto", precio="22.00", cotizacion_automatica=True,
            opciones=[{"nombre": "Talla", "valores": [{"valor": "XXL", "recargo": "2.00"}]}],
            extras=[{"codigo": "nombre", "nombre": "Nombre", "precio": "1.00"}],
        ), reglas={"descuentos": [{"desde": 12, "porcentaje": "5"}], "cantidad_maxima": 200},
    )
    _, artefacto = tools["cotizar_pedido"].func("PLAN-45", 18, {"Talla": "XXL"}, ["nombre"])
    cotizacion = artefacto["cotizacion"]
    assert cotizacion["base_con_descuento"] == "20.90"
    assert cotizacion["unitario"] == "23.90" and cotizacion["total"] == "430.20"
    assert cotizacion["version"] == 1 and len(artefacto["adjuntos"]) == 1


@pytest.mark.parametrize("cambios,cantidad,opciones,extras,a_medida", [
    ({"agotado": True}, 1, {}, [], False),
    ({"precio_desde": True}, 1, {}, [], False),
    ({"cotizacion_automatica": False}, 1, {}, [], False),
    ({}, 0, {}, [], False),
    ({}, 201, {}, [], False),
    ({}, 1, {}, ["inexistente"], False),
    ({}, 1, {"Color": "rojo"}, [], False),
    ({"opciones": [{"nombre": "Talla", "valores": [{"valor": "M", "recargo": None}]}]}, 1, {}, [], False),
    ({}, 1, {}, [], True),
])
def test_no_cotiza_pedidos_no_autorizados(tmp_path, cambios, cantidad, opciones, extras, a_medida):
    tools, _ = herramientas(
        tmp_path, item(cotizacion_automatica=True, **{k: v for k, v in cambios.items() if k != "cotizacion_automatica"})
        | cambios, reglas={"cantidad_maxima": 200},
    )
    texto, artefacto = tools["cotizar_pedido"].func("PLAN-45", cantidad, opciones, extras, a_medida)
    assert "No se pudo cotizar" in texto and "cotizacion" not in artefacto


def test_dos_lineas_del_mismo_negocio_filtran_productos_y_direccion(tmp_path):
    datos = contenido(
        item(sku="A", lineas=["uniformes"], fotos=[]),
        item(sku="B", lineas=["sublimacion"], fotos=[]),
    )
    datos["perfil"] = {"lineas": [
        {"codigo": "uniformes", "direccion": "Centro", "horarios": "8 a 5"},
        {"codigo": "sublimacion", "direccion": "Masaya", "horarios": "9 a 6"},
    ]}
    tools = {t.name: t for t in crear_herramientas_portal(
        URL, CLAVE, linea="uniformes", negocio_id="smarth-house", cache_dir=tmp_path,
        hoy_para_pruebas=HOY, cliente_http=HTTPFalso(datos),
    )}
    assert '"sku": "A"' in tools["ver_catalogo"].func()
    assert '"sku": "B"' not in tools["ver_catalogo"].func()
    assert "Masaya" not in tools["datos_del_negocio"].func()
    texto, artefacto = tools["mostrar_fotos"].func(["B"])
    assert not artefacto["adjuntos"]


def test_fuentes_locales_no_se_mezclan_con_portal():
    tools = herramientas_para(
        ruta_catalogo="catalogo-de-otro-negocio.json",
        portal_url=URL, portal_clave_bot=CLAVE,
    )
    nombres = [t.name for t in tools]
    assert nombres.count("ver_catalogo") == 1
    a = agente_falso(["hola"])
    with pytest.raises(ErrorDeConfiguracion, match="vacíos"):
        replace(a.config, portal_url=URL, portal_clave_bot=CLAVE,
                portal_negocio_id="smarth-house", catalogo_ruta="demo.json")


def test_salud_distingue_reglas_del_portal_sin_exponer_claves():
    import hashlib

    from test_chatwoot import ChatwootFalso, cliente
    from agente.portal import REGLA_CATALOGO

    agente = agente_falso(["hola"])
    with cliente(ChatwootFalso(), agente) as web:
        anterior = web.get("/salud").json()
        agente.config.portal_url = URL
        agente.config.portal_clave_bot = CLAVE
        actual = web.get("/salud").json()
    assert "catalogo_fuente" not in anterior
    assert actual["catalogo_fuente"] == "portal"
    assert actual["prompt_sha256"] == anterior["prompt_sha256"]
    assert actual["reglas_catalogo_sha256"] == hashlib.sha256(REGLA_CATALOGO.encode()).hexdigest()
    assert CLAVE not in json.dumps(actual) and URL not in json.dumps(actual)


def test_bot_y_empleado_solo_descargan_fotos_publicadas(tmp_path):
    portal = armar(tmp_path)
    dueno = entrar(portal)
    empleado = entrar(portal, "empleado@ejemplo.com")
    producto, foto_id = crear_con_foto(dueno)
    assert bot(portal).get(f"/api/bot/fotos/{foto_id}").status_code == 404
    assert empleado.get(f"/api/fotos/{foto_id}").status_code == 404
    dueno.post("/api/publicar", headers=CABECERA)
    assert bot(portal).get(f"/api/bot/fotos/{foto_id}").status_code == 200
    dueno.delete(f"/api/items/{producto['id']}/fotos/{foto_id}", headers=CABECERA)
    assert empleado.get(f"/api/fotos/{foto_id}").status_code == 200
    dueno.post("/api/publicar", headers=CABECERA)
    assert bot(portal).get(f"/api/bot/fotos/{foto_id}").status_code == 404


def test_publicacion_nueva_se_consulta_en_el_mismo_hilo_sin_borrar_memoria(tmp_path, monkeypatch):
    portal = armar(tmp_path / "portal")
    dueno = entrar(portal)
    producto, _ = crear_con_foto(dueno)
    dueno.post("/api/publicar", headers=CABECERA)
    cliente = bot(portal)

    def http(metodo, url):
        respuesta = cliente.request(metodo, url.removeprefix(URL))
        respuesta.raise_for_status()
        return respuesta.content

    tools = crear_herramientas_portal(
        URL, CLAVE_BOT, negocio_id="smarth-house", cache_dir=tmp_path / "bot",
        hoy_para_pruebas=HOY, cliente_http=http,
    )
    monkeypatch.setattr("agente.agente.herramientas_para", lambda *args: tools)
    agente = agente_falso([])
    agente.config = replace(
        agente.config, portal_url=URL, portal_clave_bot=CLAVE_BOT,
        portal_negocio_id="smarth-house", cache=False,
    )
    llamadas = lambda id: AIMessage("", tool_calls=[
        {"name": "promociones_disponibles", "args": {}, "id": id},
    ])
    agente.modelo = ModeloFalso(messages=iter([
        llamadas("antes"), AIMessage("La tarifa publicada es 45."),
        llamadas("despues"), AIMessage("La tarifa publicada ahora es 55."),
        AIMessage("Con gusto."),
    ]))
    agente.grafo = agente._construir_grafo()
    primera = agente.responder_partido_con_adjuntos("precio", "prueba")
    dueno.put(f"/api/items/{producto['id']}", json=producto | {"precio": "55.00"}, headers=CABECERA)
    dueno.post("/api/publicar", headers=CABECERA)
    segunda = agente.responder_partido_con_adjuntos("precio actual", "prueba")
    tercera = agente.responder_partido_con_adjuntos("gracias", "prueba")
    historial = agente.historial("prueba")
    resultados = [m.content for m in historial if isinstance(m, ToolMessage)]
    assert "US$ 45.00" in resultados[0] and "US$ 55.00" in resultados[1]
    assert primera.adjuntos and segunda.adjuntos and not tercera.adjuntos
    assert len(historial) == 10 and agente.historial("otro-chat") == []
    assert "en este turno" in agente._sistema().content
