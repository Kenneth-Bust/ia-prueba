"""Pruebas del catálogo y del cotizador; no llaman al proveedor ni a Chatwoot.

Los importes de aceptación salen del plan de la demo de uniformes
(docs/demo-uniformes-plan.md): si cambian ahí, tienen que cambiar acá.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agente.agente import Agente  # noqa: E402
from agente.catalogo import (  # noqa: E402
    ConsultaInvalida,
    NecesitaUnaPersona,
    cotizar,
    crear_herramientas_catalogo,
    leer_catalogo,
)
from agente.config import Config  # noqa: E402
from agente.herramientas import herramientas_para  # noqa: E402
from agente.memoria import ram  # noqa: E402
from agente.promociones import ErrorDeCatalogo  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
CATALOGO_DEMO = RAIZ / "catalogos/demo_uniformes.json"


@pytest.fixture(scope="module")
def demo():
    return leer_catalogo(CATALOGO_DEMO, RAIZ)


def _invocar(herramienta, argumentos: dict) -> ToolMessage:
    return herramienta.invoke(
        {
            "name": herramienta.name,
            "args": argumentos,
            "id": "llamada-1",
            "type": "tool_call",
        }
    )


def _catalogo_de_prueba(raiz: Path, **cambios_del_producto) -> Path:
    imagen = raiz / "recursos/prueba/producto.png"
    imagen.parent.mkdir(parents=True, exist_ok=True)
    imagen.write_bytes(b"\x89PNG\r\n\x1a\ncontenido-de-prueba")

    producto = {
        "sku": "P-1",
        "nombre": "Producto de prueba",
        "categoria": "Pruebas",
        "incluye": "Una unidad",
        "precio_base": "10.00",
        "tallas": [],
        "extras": [],
        "imagen": "recursos/prueba/producto.png",
        "cotizacion_automatica": True,
        "activo": True,
    }
    producto.update(cambios_del_producto)
    datos = {
        "version": "prueba",
        "negocio": "Negocio de prueba",
        "ficticio": True,
        "moneda": "USD",
        "cantidad_maxima_automatica": 50,
        "descuentos_por_cantidad": [],
        "productos": [producto],
    }
    ruta = raiz / "catalogos/prueba.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    return ruta


# -- El catálogo de la demo ----------------------------------------------------


def test_el_catalogo_demo_es_ficticio_y_tiene_sus_seis_fotos(demo):
    assert demo.ficticio is True
    assert [producto.sku for producto in demo.productos] == [
        "FUT-01",
        "FUT-02",
        "BEI-01",
        "BEI-02",
        "SUB-01",
        "SUB-02",
    ]
    assert all(
        producto.imagen.ruta.is_file() and producto.imagen.mime == "image/png"
        for producto in demo.productos
    )


def test_aceptacion_dieciocho_uniformes_con_nombre_y_numero(demo):
    cotizacion = cotizar(demo, "FUT-01", 18, tallas=["M"], extras=["nombre", "número"])

    assert cotizacion.base_con_descuento == Decimal("20.90")
    assert cotizacion.extras_por_unidad == Decimal("2.00")
    assert cotizacion.unitario == Decimal("22.90")
    assert cotizacion.total == Decimal("412.20")


def test_aceptacion_doce_tazas(demo):
    assert cotizar(demo, "SUB-01", 12).total == Decimal("91.20")


@pytest.mark.parametrize(
    "cantidad, porcentaje",
    [(1, None), (11, None), (12, "5"), (23, "5"), (24, "10"), (200, "10")],
)
def test_los_tramos_de_descuento_respetan_sus_bordes(demo, cantidad, porcentaje):
    cotizacion = cotizar(demo, "FUT-01", cantidad, tallas=["L"])

    obtenido = None if cotizacion.descuento is None else str(cotizacion.descuento.porcentaje)
    assert obtenido == porcentaje


def test_el_descuento_no_se_aplica_a_los_extras(demo):
    cotizacion = cotizar(demo, "BEI-01", 24, tallas=["M"], extras=["nombre"])

    assert cotizacion.base_con_descuento == Decimal("28.80")
    assert cotizacion.unitario == Decimal("29.80")
    assert cotizacion.total == Decimal("715.20")


def test_mas_del_maximo_lo_cotiza_una_persona(demo):
    with pytest.raises(NecesitaUnaPersona):
        cotizar(demo, "FUT-01", 201, tallas=["M"])


@pytest.mark.parametrize("cantidad", [0, -3, True])
def test_una_cantidad_invalida_se_pregunta(demo, cantidad):
    with pytest.raises(ConsultaInvalida):
        cotizar(demo, "FUT-01", cantidad, tallas=["M"])


def test_sin_talla_no_se_cotiza_un_uniforme(demo):
    with pytest.raises(ConsultaInvalida, match="talla"):
        cotizar(demo, "FUT-02", 12)


def test_una_talla_fuera_de_la_lista_la_revisa_una_persona(demo):
    with pytest.raises(NecesitaUnaPersona):
        cotizar(demo, "FUT-02", 12, tallas=["M", "XXL"])


def test_la_taza_no_ofrece_nombre_ni_numero(demo):
    with pytest.raises(ConsultaInvalida, match="no ofrece"):
        cotizar(demo, "SUB-01", 5, extras=["nombre"])


def test_un_codigo_que_no_existe_no_se_cotiza(demo):
    with pytest.raises(ConsultaInvalida):
        cotizar(demo, "FUT-99", 5)


def test_un_logo_propio_lo_cotiza_una_persona(demo):
    with pytest.raises(NecesitaUnaPersona):
        cotizar(demo, "SUB-02", 10, tallas=["M"], diseno_propio=True)


# -- Validación del archivo ----------------------------------------------------


def test_un_importe_escrito_como_numero_se_rechaza(tmp_path):
    ruta = _catalogo_de_prueba(tmp_path, precio_base=22.1)

    with pytest.raises(ErrorDeCatalogo, match="texto"):
        leer_catalogo(ruta, tmp_path)


def test_un_codigo_repetido_invalida_el_catalogo(tmp_path):
    ruta = _catalogo_de_prueba(tmp_path)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["productos"].append(dict(datos["productos"][0], sku="p-1"))
    ruta.write_text(json.dumps(datos), encoding="utf-8")

    with pytest.raises(ErrorDeCatalogo, match="repetido"):
        leer_catalogo(ruta, tmp_path)


def test_un_producto_inactivo_no_se_ofrece(tmp_path):
    ruta = _catalogo_de_prueba(tmp_path, activo=False, imagen="recursos/prueba/borrada.png")

    catalogo = leer_catalogo(ruta, tmp_path)

    assert catalogo.productos == ()
    with pytest.raises(ConsultaInvalida):
        cotizar(catalogo, "P-1", 1)


def test_una_foto_fuera_de_recursos_invalida_el_catalogo(tmp_path):
    ruta = _catalogo_de_prueba(tmp_path, imagen="../secreto.png")

    with pytest.raises(ErrorDeCatalogo, match="dentro de recursos"):
        leer_catalogo(ruta, tmp_path)


# -- Las herramientas ----------------------------------------------------------


def test_mostrar_fotos_adjunta_solo_productos_del_catalogo():
    _, fotos, _ = crear_herramientas_catalogo(CATALOGO_DEMO, raiz=RAIZ)

    resultado = _invocar(fotos, {"codigos": ["BEI-02", "NO-EXISTE"]})

    assert [adjunto["codigo"] for adjunto in resultado.artifact["adjuntos"]] == ["BEI-02"]
    assert "NO-EXISTE" in resultado.content


def test_mostrar_fotos_no_manda_mas_de_tres():
    _, fotos, _ = crear_herramientas_catalogo(CATALOGO_DEMO, raiz=RAIZ)

    resultado = _invocar(fotos, {"codigos": ["FUT-01", "FUT-02", "BEI-01", "BEI-02"]})

    assert len(resultado.artifact["adjuntos"]) == 3
    assert "BEI-02" in resultado.content


def test_cotizar_pedido_devuelve_el_desglose_calculado():
    _, _, cotizador = crear_herramientas_catalogo(CATALOGO_DEMO, raiz=RAIZ)

    resultado = _invocar(
        cotizador,
        {"codigo": "FUT-01", "cantidad": 18, "tallas": ["M"], "extras": ["nombre", "numero"]},
    )

    assert "US$ 22.90" in resultado.content
    assert "US$ 412.20" in resultado.content
    assert "ficticios" in resultado.content


def test_cotizar_pedido_deriva_sin_inventar_un_precio():
    _, _, cotizador = crear_herramientas_catalogo(CATALOGO_DEMO, raiz=RAIZ)

    resultado = _invocar(
        cotizador,
        {"codigo": "SUB-02", "cantidad": 10, "tallas": ["M"], "diseno_propio": True},
    )

    assert "persona del equipo" in resultado.content
    assert "US$" not in resultado.content


def test_un_catalogo_roto_no_voltea_la_conversacion(tmp_path):
    ruta = _catalogo_de_prueba(tmp_path, precio_base=10)
    ver, fotos, cotizador = crear_herramientas_catalogo(ruta, raiz=tmp_path)

    assert "No se pudo validar el catálogo" in _invocar(ver, {}).content
    assert _invocar(fotos, {"codigos": ["P-1"]}).artifact == {"adjuntos": []}
    assert "No se pudo validar" in _invocar(cotizador, {"codigo": "P-1", "cantidad": 1}).content


def test_sin_catalogo_configurado_no_hay_herramientas_de_catalogo():
    assert {herramienta.name for herramienta in herramientas_para()} == {"clima"}

    nombres = {herramienta.name for herramienta in herramientas_para(ruta_catalogo=CATALOGO_DEMO)}
    assert {"ver_catalogo", "mostrar_fotos", "cotizar_pedido"} <= nombres


def test_el_agente_devuelve_las_fotos_que_pidio_el_modelo():
    class ModeloFalso(GenericFakeChatModel):
        def bind_tools(self, herramientas, **kwargs):
            return self

    agente = Agente.__new__(Agente)
    agente.config = Config(
        proveedor="gemini",
        modelo="modelo-de-prueba",
        api_key="no-hace-falta",
        max_tokens=1024,
        memoria_mensajes=20,
        prompt_sistema=RAIZ / "prompts/demo_uniformes.md",
        catalogo_ruta=CATALOGO_DEMO,
    )
    agente.modelo = ModeloFalso(
        messages=iter(
            [
                AIMessage(
                    "",
                    tool_calls=[
                        {"name": "mostrar_fotos", "args": {"codigos": ["FUT-01"]}, "id": "foto-1"}
                    ],
                ),
                AIMessage("Este es el uniforme azul y blanco."),
            ]
        )
    )
    agente.checkpointer = ram()
    agente.grafo = agente._construir_grafo()

    salida = agente.responder_partido_con_adjuntos("quiero ver el uniforme azul", "conversacion-1")

    assert salida.mensajes == ["Este es el uniforme azul y blanco."]
    assert [adjunto.codigo for adjunto in salida.adjuntos] == ["FUT-01"]
