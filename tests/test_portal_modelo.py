"""Reglas de los datos del portal. Sin base, sin red."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from portal.modelo import (  # noqa: E402
    DatosInvalidos,
    armar_contenido,
    huella_de,
    validar_ajustes,
    validar_correo,
    validar_item,
    validar_negocio_id,
    validar_perfil,
)

NEGOCIO = {"id": "smarth-house", "nombre": "Smarth House"}


def item(**cambios) -> dict:
    return {
        "tipo": "servicio",
        "sku": "plan-45",
        "nombre": "Plan mensual",
        "precio": "45",
        "unidad": "al mes",
        "cotizacion_automatica": False,
        "activo": True,
    } | cambios


def test_un_plan_mensual_es_un_servicio_con_unidad_y_vigencia():
    validado = validar_item(item(vigente_desde="2026-09-01", vigente_hasta="2026-10-11"))

    assert validado["sku"] == "PLAN-45"
    assert validado["precio"] == "45.00"
    assert validado["unidad"] == "al mes"
    assert (validado["vigente_desde"], validado["vigente_hasta"]) == ("2026-09-01", "2026-10-11")


def test_una_talla_es_una_opcion_y_el_extra_lleva_codigo():
    validado = validar_item(
        item(
            tipo="producto",
            opciones=[{"nombre": "Talla", "valores": ["S", " M ", "L"]}],
            extras=[{"nombre": "Número estampado", "precio": "1"}],
        )
    )

    assert validado["opciones"] == [
        {"nombre": "Talla", "valores": [{"valor": v, "recargo": None} for v in ("S", "M", "L")]}
    ]
    assert validado["extras"] == [
        {"codigo": "numero_estampado", "nombre": "Número estampado", "precio": "1.00"}
    ]


def test_un_valor_de_la_opcion_puede_costar_mas():
    validado = validar_item(
        item(tipo="producto", opciones=[{"nombre": "Talla", "valores": [
            "M", {"valor": "XXL", "recargo": "2"}, {"valor": "L", "recargo": "0"},
        ]}])
    )

    assert validado["opciones"][0]["valores"] == [
        {"valor": "M", "recargo": None},
        {"valor": "XXL", "recargo": "2.00"},
        {"valor": "L", "recargo": None},
    ]
    with pytest.raises(DatosInvalidos, match="recargo"):
        validar_item(item(precio="", opciones=[{"nombre": "Talla", "valores": [{"valor": "XXL", "recargo": "2"}]}]))
    with pytest.raises(DatosInvalidos):
        validar_item(item(opciones=[{"nombre": "Talla", "valores": [{"valor": "XXL", "recargo": "-2"}]}]))


def test_precio_desde_y_agotado():
    validado = validar_item(item(precio="300", precio_desde=True, agotado=True))

    assert validado["precio_desde"] is True and validado["agotado"] is True
    assert validar_item(item())["precio_desde"] is False and validar_item(item())["agotado"] is False
    with pytest.raises(DatosInvalidos, match="referencia"):
        validar_item(item(precio="", precio_desde=True))
    with pytest.raises(DatosInvalidos, match="cotización automática"):
        validar_item(item(precio_desde=True, cotizacion_automatica=True))
    with pytest.raises(DatosInvalidos):
        validar_item(item(agotado="sí"))


def test_el_item_se_ofrece_solo_en_lineas_que_existen():
    validas = ["uniformes", "sublimacion"]

    assert validar_item(item(lineas=["uniformes", "uniformes"]), lineas_validas=validas)["lineas"] == ["uniformes"]
    assert validar_item(item())["lineas"] == []
    with pytest.raises(DatosInvalidos, match="ya no existe"):
        validar_item(item(lineas=["masaya"]), lineas_validas=validas)
    with pytest.raises(DatosInvalidos):
        validar_item(item(lineas=["Con Espacio"]))


def test_las_lineas_del_negocio_conservan_su_codigo():
    perfil = validar_perfil({"lineas": [
        {"nombre": "Sublimación"},
        {"codigo": "sublimacion", "nombre": "Sublimación anterior"},
        {"nombre": "Sucursal Masaya", "direccion": "Masaya, frente al parque", "horarios": "8:00 a 17:00"},
    ]})

    assert [linea["codigo"] for linea in perfil["lineas"]] == ["sublimacion_2", "sublimacion", "sucursal_masaya"]
    assert perfil["lineas"][2]["direccion"] == "Masaya, frente al parque"
    with pytest.raises(DatosInvalidos, match="repetida"):
        validar_perfil({"lineas": [{"nombre": "Uniformes"}, {"nombre": "uniformes"}]})
    with pytest.raises(DatosInvalidos, match="números de cuenta"):
        validar_perfil({"lineas": [{"nombre": "Centro", "direccion": "Cuenta BAC 123456789"}]})


def test_una_linea_borrada_saca_a_los_items_que_solo_estaban_ahi():
    perfil = validar_perfil({"lineas": [{"codigo": "uniformes", "nombre": "Uniformes"}]})
    anterior = {
        "id": 4, "sku": "D-1", "tipo": "producto", "nombre": "Guardado antes", "categoria": "", "descripcion": "",
        "precio": "1.00", "moneda": "USD", "unidad": "", "vigente_desde": None, "vigente_hasta": None,
        "opciones": [{"nombre": "Talla", "valores": ["S"]}], "extras": [], "cotizacion_automatica": False, "activo": True,
    }
    items = [
        validar_item(item(sku="A-1", lineas=["uniformes", "borrada"])) | {"id": 1},
        validar_item(item(sku="B-1", lineas=["borrada"])) | {"id": 2},
        validar_item(item(sku="C-1")) | {"id": 3},
        anterior,
    ]

    contenido = armar_contenido(NEGOCIO, perfil, validar_ajustes({}), items, [])

    assert [(i["sku"], i["lineas"]) for i in contenido["items"]] == [("A-1", ["uniformes"]), ("C-1", []), ("D-1", [])]
    guardado_antes = contenido["items"][-1]
    assert guardado_antes["opciones"] == [{"nombre": "Talla", "valores": [{"valor": "S", "recargo": None}]}]
    assert guardado_antes["precio_desde"] is False and guardado_antes["agotado"] is False
    assert contenido["perfil"]["lineas"][0]["codigo"] == "uniformes"


def test_cada_item_lleva_su_moneda():
    assert validar_item(item())["moneda"] == "USD"
    assert validar_item(item(moneda="NIO"))["moneda"] == "NIO"
    with pytest.raises(DatosInvalidos, match="moneda"):
        validar_item(item(moneda="EUR"))


@pytest.mark.parametrize("precio, esperado", [("22,50", "22.50"), (22, "22.00"), ("0", "0.00")])
def test_el_precio_acepta_coma_y_enteros(precio, esperado):
    assert validar_item(item(precio=precio))["precio"] == esperado


@pytest.mark.parametrize("precio", ["22.555", "-1", 22.5, True, "abc", "1e3"])
def test_un_precio_raro_no_se_guarda(precio):
    with pytest.raises(DatosInvalidos):
        validar_item(item(precio=precio))


def test_sin_precio_lo_cotiza_una_persona():
    assert validar_item(item(precio=""))["precio"] is None
    with pytest.raises(DatosInvalidos, match="cargá el precio"):
        validar_item(item(precio="", cotizacion_automatica=True))


def test_al_editar_el_codigo_queda_el_de_siempre():
    assert validar_item(item(sku="OTRO"), sku_actual="PLAN-45")["sku"] == "PLAN-45"


@pytest.mark.parametrize("sku", ["", "-A", "A-", "con espacio", "Ñ1", "A" * 33, None])
def test_codigo_invalido(sku):
    with pytest.raises(DatosInvalidos):
        validar_item(item(sku=sku))


@pytest.mark.parametrize(
    "cambios",
    [
        {"tipo": "combo"},
        {"nombre": "   "},
        {"activo": "true"},
        {"vigente_desde": "2026-10-12", "vigente_hasta": "2026-10-11"},
        {"vigente_hasta": "11/10/2026"},
        {"opciones": [{"nombre": "Talla", "valores": ["S"]}, {"nombre": "talla", "valores": ["M"]}]},
        {"opciones": [{"nombre": "Color", "valores": ["Azul", "azul"]}]},
        {"opciones": [{"nombre": "Color", "valores": []}]},
        {"extras": [{"nombre": "Nombre", "precio": "1"}, {"nombre": "nombre", "precio": "2"}]},
        {"extras": [{"nombre": "Queso", "precio": ""}]},
    ],
)
def test_items_que_no_se_pueden_guardar(cambios):
    with pytest.raises(DatosInvalidos):
        validar_item(item(**cambios))


def test_la_nota_de_pagos_no_admite_numeros_de_cuenta():
    with pytest.raises(DatosInvalidos, match="números de cuenta"):
        validar_perfil({"nota_pagos": "Depositá a la 123 456 789"})

    perfil = validar_perfil(
        {"formas_de_pago": ["efectivo", "transferencia", "efectivo"], "nota_pagos": "Efectivo al retirar"}
    )
    assert perfil["formas_de_pago"] == ["transferencia", "efectivo"]


def test_un_telefono_esta_bien_pero_una_cuenta_en_otro_texto_no():
    assert validar_perfil({"direccion": "Managua, frente al parque. Tel 8888 8888"})["direccion"]

    with pytest.raises(DatosInvalidos, match="números de cuenta"):
        validar_perfil(
            {"preguntas": [{"pregunta": "¿A qué cuenta deposito?", "respuesta": "BAC 123456789"}]}
        )
    with pytest.raises(DatosInvalidos, match="números de cuenta"):
        validar_item(item(descripcion="Pagá a la cuenta 1234-5678-90"))


@pytest.mark.parametrize(
    "datos",
    [
        {"formas_de_pago": ["bitcoin"]},
        {"mapa_url": "http://maps.example/lugar"},
        {"preguntas": [{"pregunta": "¿Hacen envíos?", "respuesta": ""}]},
        {"horarios": 123},
    ],
)
def test_perfiles_que_no_se_pueden_guardar(datos):
    with pytest.raises(DatosInvalidos):
        validar_perfil(datos)


def test_las_reglas_ordenan_los_tramos_y_limpian_el_porcentaje():
    ajustes = validar_ajustes(
        {
            "moneda": "NIO",
            "cantidad_maxima": 200,
            "descuentos": [{"desde": 24, "porcentaje": "10.00"}, {"desde": 12, "porcentaje": 5}],
        }
    )

    assert ajustes == {
        "moneda": "NIO",
        "cantidad_maxima": 200,
        "descuentos": [{"desde": 12, "porcentaje": "5"}, {"desde": 24, "porcentaje": "10"}],
    }
    assert validar_ajustes({}) == {"moneda": "USD", "cantidad_maxima": None, "descuentos": []}


@pytest.mark.parametrize(
    "datos",
    [
        {"moneda": "EUR"},
        {"cantidad_maxima": 0},
        {"cantidad_maxima": "200"},
        {"descuentos": [{"desde": 1, "porcentaje": "5"}]},
        {"descuentos": [{"desde": 12, "porcentaje": "100"}]},
        {"descuentos": [{"desde": 12, "porcentaje": "5"}, {"desde": 12, "porcentaje": "6"}]},
        {"cantidad_maxima": 10, "descuentos": [{"desde": 12, "porcentaje": "5"}]},
    ],
)
def test_reglas_que_no_se_pueden_guardar(datos):
    with pytest.raises(DatosInvalidos):
        validar_ajustes(datos)


def test_la_publicacion_lleva_solo_lo_activo_y_su_huella_no_depende_del_orden():
    items = [
        validar_item(item(sku="B-1")) | {"id": 2},
        validar_item(item(sku="A-1", activo=False)) | {"id": 1},
        validar_item(item(sku="C-1")) | {"id": 3},
    ]
    fotos = [
        {
            "id": "f" * 32, "item_id": 2, "clave": "smarth-house/" + "f" * 32 + ".png",
            "mime": "image/png", "bytes": 10, "sha256": "x", "creada_en": "2026-09-14T10:00:00+00:00",
        }
    ]
    perfil = validar_perfil({"formas_de_pago": ["transferencia"]})
    ajustes = validar_ajustes({})

    contenido = armar_contenido(NEGOCIO, perfil, ajustes, items, fotos)

    assert [i["sku"] for i in contenido["items"]] == ["B-1", "C-1"]
    assert contenido["items"][0]["moneda"] == "USD" and "moneda" not in contenido
    assert contenido["items"][0]["fotos"] == [{"id": "f" * 32, "mime": "image/png", "bytes": 10, "sha256": "x"}]
    assert contenido["perfil"]["formas_de_pago"] == ["Transferencia bancaria"]
    assert "activo" not in contenido["items"][0] and "id" not in contenido["items"][0]
    assert "clave" not in contenido["items"][0]["fotos"][0]
    otra = armar_contenido(NEGOCIO, perfil, ajustes, list(reversed(items)), fotos)
    assert huella_de(contenido) == huella_de(otra)


def test_identificadores_y_correos():
    assert validar_negocio_id("smarth-house") == "smarth-house"
    assert validar_correo("  Dueno@Ejemplo.com ") == "dueno@ejemplo.com"
    for invalido in ("Smarth House", "-x", "a"):
        with pytest.raises(DatosInvalidos):
            validar_negocio_id(invalido)
    with pytest.raises(DatosInvalidos):
        validar_correo("sin-arroba")
