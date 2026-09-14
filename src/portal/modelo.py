"""Qué acepta el portal y cómo arma lo que se publica.

Todo lo que llega del navegador pasa por acá antes de guardarse. El
navegador puede mandar cualquier cosa —no solo lo que permite la
pantalla—, así que estas funciones deciden de verdad qué es un precio, un
código o una fecha válidos. Los mensajes de error son para quien carga el
catálogo: dicen qué corregir.

No hay campos propios de un rubro. Una talla es una opción llamada «Talla»;
un plan mensual es un servicio con unidad «al mes». Ver
docs/metodologia-clientes.md, «Un mismo portal para cualquier rubro».
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date
from decimal import Decimal

FORMATO_PUBLICACION = 1

TIPOS = {"producto": "Producto", "servicio": "Servicio", "promocion": "Promoción"}
MONEDAS = {"USD": "US$", "NIO": "C$"}
FORMAS_DE_PAGO = {
    "transferencia": "Transferencia bancaria",
    "deposito": "Depósito bancario",
    "efectivo": "Efectivo",
    "tarjeta": "Tarjeta de crédito o débito",
    "contra_entrega": "Pago contra entrega",
}
ROLES = ("administrador", "empleado")

MAXIMO_OPCIONES = 10
MAXIMO_VALORES = 30
MAXIMO_EXTRAS = 20
MAXIMO_PREGUNTAS = 30
MAXIMO_TRAMOS = 10
MAXIMO_FOTOS_POR_ITEM = 5

TEXTOS_DEL_PERFIL = (
    # (clave, largo máximo, cómo se nombra en un mensaje de error)
    ("nombre_publico", 120, "el nombre del negocio"),
    ("descripcion", 600, "la descripción del negocio"),
    ("direccion", 300, "la dirección"),
    ("horarios", 600, "los horarios"),
    ("envios", 800, "la información de envíos"),
    ("politicas", 1500, "las políticas"),
)

CAMPOS_PUBLICOS_DEL_ITEM = (
    "sku",
    "tipo",
    "nombre",
    "categoria",
    "descripcion",
    "precio",
    "moneda",
    "unidad",
    "vigente_desde",
    "vigente_hasta",
    "opciones",
    "extras",
    "cotizacion_automatica",
)

_SKU = re.compile(r"[A-Z0-9](?:[A-Z0-9-]{0,30}[A-Z0-9])?")
_NEGOCIO = re.compile(r"[a-z0-9][a-z0-9-]{1,40}")
_IMPORTE = re.compile(r"\d{1,9}(?:\.\d{1,2})?")
_FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")
_CORREO = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Seis dígitos o más, aunque vengan separados por espacios, puntos o guiones.
_TIRA_DE_DIGITOS = re.compile(r"\d(?:[ .-]?\d){5,}")
_HABLA_DE_CUENTAS = re.compile(
    r"\b(cuentas?|iban|bancos?|bac|banpro|lafise|bdf|ficohsa|avanz)\b", re.IGNORECASE
)


class DatosInvalidos(ValueError):
    """Lo que llegó no se puede guardar. El mensaje se muestra tal cual."""


# -- Identificadores ------------------------------------------------------------


def validar_negocio_id(valor: object) -> str:
    """El identificador estable del negocio: no cambia aunque cambie el nombre."""
    if not isinstance(valor, str) or not _NEGOCIO.fullmatch(valor):
        raise DatosInvalidos(
            "El identificador del negocio va en minúsculas, con letras, números "
            "o guiones (por ejemplo, smarth-house)."
        )
    return valor


def validar_correo(valor: object) -> str:
    if not isinstance(valor, str):
        raise DatosInvalidos("Escribí un correo válido.")
    correo = valor.strip().lower()
    if len(correo) > 254 or not _CORREO.fullmatch(correo):
        raise DatosInvalidos("Escribí un correo válido.")
    return correo


def validar_rol(valor: object) -> str:
    if valor not in ROLES:
        raise DatosInvalidos("El rol tiene que ser administrador o empleado.")
    return valor


def codigo_de(texto: str) -> str:
    """«Número estampado» → «numero_estampado». Lo usa el cotizador del bot."""
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", sin_tildes.lower()).strip("_")


# -- Ítems: productos, servicios y promociones ----------------------------------


def validar_item(datos: object, sku_actual: str | None = None) -> dict:
    """Valida un ítem completo. Al editar, el código es el que ya tenía.

    El código no se cambia después de crearlo: lo usan las fotos, las
    publicaciones anteriores y las cotizaciones que el bot ya mandó.
    """
    if not isinstance(datos, dict):
        raise DatosInvalidos("Faltan los datos del ítem.")

    tipo = datos.get("tipo")
    if tipo not in TIPOS:
        raise DatosInvalidos("Elegí si es un producto, un servicio o una promoción.")

    sku = sku_actual if sku_actual is not None else _sku(datos.get("sku"))
    nombre = _texto(datos, "nombre", 120, "el nombre", obligatorio=True)
    descripcion = _texto(datos, "descripcion", 600, "la descripción")
    for texto, etiqueta in ((nombre, "el nombre"), (descripcion, "la descripción")):
        _sin_numeros_de_cuenta(texto, etiqueta)

    precio = _importe(datos.get("precio"), "el precio", opcional=True)
    # Cada ítem lleva su moneda: acá es común cobrar unas cosas en dólares y
    # otras en córdobas dentro del mismo negocio.
    moneda = datos.get("moneda", "USD")
    if moneda not in MONEDAS:
        raise DatosInvalidos("Elegí la moneda del precio: dólares (US$) o córdobas (C$).")
    desde = _fecha(datos.get("vigente_desde"), "la fecha de inicio")
    hasta = _fecha(datos.get("vigente_hasta"), "la fecha de fin")
    if desde and hasta and desde > hasta:
        raise DatosInvalidos("La vigencia termina antes de empezar.")

    cotizacion = _booleano(datos.get("cotizacion_automatica", False), "la cotización automática")
    if cotizacion and precio is None:
        raise DatosInvalidos(
            "Para que el bot calcule el precio solo, cargá el precio. Sin precio, "
            "apagá la cotización automática y lo cotiza una persona."
        )

    return {
        "sku": sku,
        "tipo": tipo,
        "nombre": nombre,
        "categoria": _texto(datos, "categoria", 60, "la categoría"),
        "descripcion": descripcion,
        "precio": precio,
        "moneda": moneda,
        "unidad": _texto(datos, "unidad", 40, "la unidad"),
        "vigente_desde": desde,
        "vigente_hasta": hasta,
        "opciones": _opciones(datos.get("opciones")),
        "extras": _extras(datos.get("extras")),
        "cotizacion_automatica": cotizacion,
        "activo": _booleano(datos.get("activo", True), "el campo Activo"),
    }


def _sku(valor: object) -> str:
    if not isinstance(valor, str) or not _SKU.fullmatch(valor.strip().upper()):
        raise DatosInvalidos(
            "El código va con letras, números y guiones, hasta 32 caracteres "
            "(por ejemplo, PLAN-45 o FUT-01)."
        )
    return valor.strip().upper()


def _opciones(valor: object) -> list[dict]:
    """Listas sin recargo que define cada negocio: talla, color, sabor."""
    if valor in (None, ""):
        return []
    if not isinstance(valor, list) or len(valor) > MAXIMO_OPCIONES:
        raise DatosInvalidos(f"Se pueden cargar hasta {MAXIMO_OPCIONES} opciones.")

    opciones, nombres = [], set()
    for opcion in valor:
        if not isinstance(opcion, dict):
            raise DatosInvalidos("Revisá las opciones: falta el nombre o los valores.")
        nombre = _texto(opcion, "nombre", 40, "el nombre de la opción", obligatorio=True)
        if nombre.casefold() in nombres:
            raise DatosInvalidos(f"La opción «{nombre}» está repetida.")
        nombres.add(nombre.casefold())

        crudos = opcion.get("valores")
        if not isinstance(crudos, list) or not 1 <= len(crudos) <= MAXIMO_VALORES:
            raise DatosInvalidos(
                f"La opción «{nombre}» necesita entre 1 y {MAXIMO_VALORES} valores."
            )
        valores, vistos = [], set()
        for crudo in crudos:
            limpio = crudo.strip() if isinstance(crudo, str) else ""
            if not limpio or len(limpio) > 40:
                raise DatosInvalidos(
                    f"Cada valor de «{nombre}» tiene que tener entre 1 y 40 caracteres."
                )
            if limpio.casefold() in vistos:
                raise DatosInvalidos(f"En «{nombre}», el valor «{limpio}» está repetido.")
            vistos.add(limpio.casefold())
            valores.append(limpio)
        opciones.append({"nombre": nombre, "valores": valores})
    return opciones


def _extras(valor: object) -> list[dict]:
    """Adicionales con precio por unidad: nombre estampado, queso extra."""
    if valor in (None, ""):
        return []
    if not isinstance(valor, list) or len(valor) > MAXIMO_EXTRAS:
        raise DatosInvalidos(f"Se pueden cargar hasta {MAXIMO_EXTRAS} extras.")

    extras, codigos = [], set()
    for extra in valor:
        if not isinstance(extra, dict):
            raise DatosInvalidos("Revisá los extras: cada uno lleva nombre y precio.")
        nombre = _texto(extra, "nombre", 60, "el nombre del extra", obligatorio=True)
        codigo = codigo_de(nombre)
        if not codigo:
            raise DatosInvalidos(f"El extra «{nombre}» necesita letras o números en el nombre.")
        if codigo in codigos:
            raise DatosInvalidos(f"El extra «{nombre}» está repetido.")
        codigos.add(codigo)
        precio = _importe(extra.get("precio"), f"el precio de «{nombre}»")
        extras.append({"codigo": codigo, "nombre": nombre, "precio": precio})
    return extras


# -- Mi negocio -------------------------------------------------------------------


def perfil_vacio() -> dict:
    return {clave: "" for clave, _, _ in TEXTOS_DEL_PERFIL} | {
        "mapa_url": "",
        "formas_de_pago": [],
        "nota_pagos": "",
        "preguntas": [],
    }


def validar_perfil(datos: object) -> dict:
    if not isinstance(datos, dict):
        raise DatosInvalidos("Faltan los datos del negocio.")

    perfil = perfil_vacio()
    for clave, maximo, etiqueta in TEXTOS_DEL_PERFIL:
        perfil[clave] = _texto(datos, clave, maximo, etiqueta)
        _sin_numeros_de_cuenta(perfil[clave], etiqueta)

    mapa = _texto(datos, "mapa_url", 500, "el enlace del mapa")
    if mapa and not re.fullmatch(r"https://\S+", mapa):
        raise DatosInvalidos("El enlace del mapa tiene que empezar con https://")
    perfil["mapa_url"] = mapa

    formas = datos.get("formas_de_pago") or []
    if not isinstance(formas, list) or any(forma not in FORMAS_DE_PAGO for forma in formas):
        raise DatosInvalidos("Elegí las formas de pago de la lista.")
    # Orden fijo y sin repetidas: dos guardados iguales dan la misma huella.
    perfil["formas_de_pago"] = [forma for forma in FORMAS_DE_PAGO if forma in formas]

    perfil["nota_pagos"] = _texto(datos, "nota_pagos", 300, "la nota sobre pagos")
    _sin_numeros_de_cuenta(perfil["nota_pagos"], "la nota sobre pagos", estricto=True)

    perfil["preguntas"] = _preguntas(datos.get("preguntas"))
    return perfil


def _preguntas(valor: object) -> list[dict]:
    if valor in (None, ""):
        return []
    if not isinstance(valor, list) or len(valor) > MAXIMO_PREGUNTAS:
        raise DatosInvalidos(f"Se pueden cargar hasta {MAXIMO_PREGUNTAS} preguntas frecuentes.")
    preguntas = []
    for cruda in valor:
        if not isinstance(cruda, dict):
            raise DatosInvalidos("Cada pregunta frecuente lleva pregunta y respuesta.")
        pregunta = _texto(cruda, "pregunta", 200, "la pregunta", obligatorio=True)
        respuesta = _texto(cruda, "respuesta", 800, "la respuesta", obligatorio=True)
        _sin_numeros_de_cuenta(pregunta, "la pregunta")
        _sin_numeros_de_cuenta(respuesta, "la respuesta")
        preguntas.append({"pregunta": pregunta, "respuesta": respuesta})
    return preguntas


def _sin_numeros_de_cuenta(texto: str, etiqueta: str, estricto: bool = False) -> None:
    """El portal no guarda números de cuenta: los pagos los atiende una persona.

    Decisión del usuario del 14/09/2026. En la nota de pagos cualquier tira
    larga de dígitos es sospechosa. En los demás textos un teléfono es
    normal, así que se frena solo si además se habla de cuentas o bancos.
    """
    if not _TIRA_DE_DIGITOS.search(texto):
        return
    if estricto or _HABLA_DE_CUENTAS.search(texto):
        raise DatosInvalidos(
            f"{_mayuscula(etiqueta)} no puede llevar números de cuenta. Los pagos "
            "los atiende una persona del equipo, no el bot."
        )


# -- Reglas de precio ---------------------------------------------------------------


def ajustes_por_defecto() -> dict:
    # «moneda» es la habitual del negocio: con la que arranca un ítem nuevo.
    return {"moneda": "USD", "cantidad_maxima": None, "descuentos": []}


def validar_ajustes(datos: object) -> dict:
    if not isinstance(datos, dict):
        raise DatosInvalidos("Faltan las reglas de precio.")

    moneda = datos.get("moneda", "USD")
    if moneda not in MONEDAS:
        raise DatosInvalidos("La moneda tiene que ser dólares (USD) o córdobas (NIO).")

    maxima = datos.get("cantidad_maxima")
    if maxima in (None, ""):
        maxima = None
    elif isinstance(maxima, bool) or not isinstance(maxima, int) or not 1 <= maxima <= 100_000:
        raise DatosInvalidos("La cantidad máxima tiene que ser un número entero entre 1 y 100000.")

    crudos = datos.get("descuentos") or []
    if not isinstance(crudos, list) or len(crudos) > MAXIMO_TRAMOS:
        raise DatosInvalidos(f"Se pueden cargar hasta {MAXIMO_TRAMOS} tramos de descuento.")

    descuentos = []
    for crudo in crudos:
        if not isinstance(crudo, dict):
            raise DatosInvalidos("Cada tramo lleva la cantidad desde la que aplica y el porcentaje.")
        desde = crudo.get("desde")
        if isinstance(desde, bool) or not isinstance(desde, int) or desde < 2:
            raise DatosInvalidos("Cada tramo empieza desde 2 unidades o más.")
        if maxima is not None and desde > maxima:
            raise DatosInvalidos(
                f"El tramo desde {desde} unidades pasa la cantidad máxima ({maxima})."
            )
        descuentos.append({"desde": desde, "porcentaje": _porcentaje(crudo.get("porcentaje"))})

    descuentos.sort(key=lambda tramo: tramo["desde"])
    for anterior, siguiente in zip(descuentos, descuentos[1:]):
        if anterior["desde"] == siguiente["desde"]:
            raise DatosInvalidos(f"Hay dos tramos desde {siguiente['desde']} unidades.")

    return {"moneda": moneda, "cantidad_maxima": maxima, "descuentos": descuentos}


def _porcentaje(valor: object) -> str:
    texto = _numero_como_texto(valor)
    if texto is None or not _IMPORTE.fullmatch(texto) or not 0 < Decimal(texto) < 100:
        raise DatosInvalidos("El descuento tiene que ser un porcentaje mayor que 0 y menor que 100.")
    return f"{Decimal(texto):.2f}".rstrip("0").rstrip(".")


# -- Publicación ----------------------------------------------------------------------


def armar_contenido(
    negocio: dict, perfil: dict, ajustes: dict, items: list[dict], fotos: list[dict]
) -> dict:
    """Lo que ve el bot: una foto fija de lo que el negocio tiene cargado.

    Solo entran los ítems activos, con sus fotos vigentes. Ni la versión ni
    la fecha van adentro: así dos publicaciones con los mismos datos tienen
    la misma huella y el portal sabe que no hay nada nuevo que publicar.
    """
    fotos_por_item: dict[int, list[dict]] = {}
    for foto in sorted(fotos, key=lambda f: (f["creada_en"], f["id"])):
        fotos_por_item.setdefault(foto["item_id"], []).append(
            {"id": foto["id"], "mime": foto["mime"], "bytes": foto["bytes"], "sha256": foto["sha256"]}
        )

    perfil = perfil_vacio() | perfil
    ajustes = ajustes_por_defecto() | ajustes

    return {
        "formato": FORMATO_PUBLICACION,
        "negocio": {"id": negocio["id"], "nombre": negocio["nombre"]},
        # Sin moneda general: la de cada precio va en su ítem.
        "perfil": perfil
        | {"formas_de_pago": [FORMAS_DE_PAGO[forma] for forma in perfil["formas_de_pago"]]},
        "reglas": {
            "cantidad_maxima": ajustes["cantidad_maxima"],
            "descuentos": ajustes["descuentos"],
        },
        "items": [
            {campo: item[campo] for campo in CAMPOS_PUBLICOS_DEL_ITEM}
            | {"fotos": fotos_por_item.get(item["id"], [])}
            for item in sorted(items, key=lambda i: i["sku"])
            if item["activo"]
        ],
    }


def huella_de(contenido: dict) -> str:
    canonico = json.dumps(contenido, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


# -- Piezas chicas ----------------------------------------------------------------------


def _texto(datos: dict, clave: str, maximo: int, etiqueta: str, obligatorio: bool = False) -> str:
    valor = datos.get(clave)
    if valor is None:
        valor = ""
    if not isinstance(valor, str):
        raise DatosInvalidos(f"{_mayuscula(etiqueta)} tiene que ser texto.")
    limpio = _CONTROL.sub("", valor.replace("\r\n", "\n").replace("\r", "\n")).strip()
    if obligatorio and not limpio:
        raise DatosInvalidos(f"Falta completar {etiqueta}.")
    if len(limpio) > maximo:
        raise DatosInvalidos(f"{_mayuscula(etiqueta)} admite hasta {maximo} caracteres.")
    return limpio


def _importe(valor: object, etiqueta: str, opcional: bool = False) -> str | None:
    texto = _numero_como_texto(valor)
    if texto is None:
        if opcional:
            return None
        raise DatosInvalidos(f"Falta {etiqueta}.")
    if not _IMPORTE.fullmatch(texto):
        raise DatosInvalidos(f"{_mayuscula(etiqueta)} tiene que ser un número como 22 o 22.50.")
    return f"{Decimal(texto):.2f}"


def _numero_como_texto(valor: object) -> str | None:
    """Acepta texto o enteros; nunca float, que ya perdió centavos al llegar."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    if isinstance(valor, bool) or not isinstance(valor, (str, int)):
        return "x"  # no pasa ninguna validación de formato
    texto = str(valor).strip()
    # «22,50» es como lo escribe la mayoría acá.
    if "," in texto and "." not in texto:
        texto = texto.replace(",", ".")
    return texto


def _fecha(valor: object, etiqueta: str) -> str | None:
    if valor in (None, ""):
        return None
    if not isinstance(valor, str) or not _FECHA.fullmatch(valor):
        raise DatosInvalidos(f"{_mayuscula(etiqueta)} no es una fecha válida.")
    try:
        return date.fromisoformat(valor).isoformat()
    except ValueError:
        raise DatosInvalidos(f"{_mayuscula(etiqueta)} no es una fecha válida.") from None


def _booleano(valor: object, etiqueta: str) -> bool:
    if not isinstance(valor, bool):
        raise DatosInvalidos(f"{_mayuscula(etiqueta)} tiene que ser sí o no.")
    return valor


def _mayuscula(texto: str) -> str:
    return texto[:1].upper() + texto[1:]
