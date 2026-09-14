"""Catálogo de productos con fotos aprobadas y cotización hecha con código.

Es la misma idea que promociones.py, para un negocio que vende productos.
Gemini entiende qué quiere la persona y redacta; el precio, el descuento y
la foto salen de acá. El modelo nunca hace la cuenta ni elige un archivo,
que es lo que pide docs/metodologia-clientes.md.

Hoy el catálogo es un JSON del repositorio porque los datos de la demo son
ficticios. Cuando exista el portal de catálogos cambia de dónde se leen los
productos; las herramientas y el envío de fotos quedan iguales.
"""

from __future__ import annotations

import json
import logging
import unicodedata
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from langchain_core.tools import tool

from .canales.base import AdjuntoSaliente
from .config import RAIZ
from .promociones import ErrorDeCatalogo, artefacto_de_adjunto, imagen_aprobada

registro = logging.getLogger("agente.catalogo")

# WhatsApp muestra cada foto como un mensaje aparte: más de tres seguidas
# tapan la conversación en vez de ayudar a elegir.
MAXIMO_FOTOS = 3
CENTAVOS = Decimal("0.01")

SIN_CATALOGO = (
    "No se pudo validar el catálogo. No des productos, precios ni fotos; "
    "ofrecé pasar la consulta al equipo."
)


class ConsultaInvalida(Exception):
    """Al pedido le falta un dato o trae uno que el catálogo no tiene."""


class NecesitaUnaPersona(Exception):
    """El pedido no tiene una regla automática: lo cotiza el equipo."""


@dataclass(frozen=True)
class Extra:
    codigo: str
    nombre: str
    precio: Decimal


@dataclass(frozen=True)
class Producto:
    sku: str
    nombre: str
    categoria: str
    incluye: str
    precio_base: Decimal
    tallas: tuple[str, ...]
    extras: tuple[Extra, ...]
    imagen: AdjuntoSaliente
    cotizacion_automatica: bool


@dataclass(frozen=True)
class Descuento:
    desde: int
    porcentaje: Decimal


@dataclass(frozen=True)
class Catalogo:
    negocio: str
    moneda: str
    ficticio: bool
    cantidad_maxima: int
    descuentos: tuple[Descuento, ...]
    productos: tuple[Producto, ...]

    def producto(self, codigo: str) -> Producto:
        buscado = str(codigo or "").strip().upper()
        for producto in self.productos:
            if producto.sku.upper() == buscado:
                return producto
        raise ConsultaInvalida(f"No existe el producto '{codigo}' en el catálogo.")


@dataclass(frozen=True)
class Cotizacion:
    producto: Producto
    cantidad: int
    tallas: tuple[str, ...]
    extras: tuple[Extra, ...]
    descuento: Descuento | None
    base_con_descuento: Decimal
    extras_por_unidad: Decimal
    unitario: Decimal
    total: Decimal


# -- Lectura -------------------------------------------------------------------


def leer_catalogo(ruta: Path, raiz: Path = RAIZ) -> Catalogo:
    """Lee y valida el catálogo completo. Un dato roto invalida todo el archivo.

    Es a propósito: ofrecer la mitad de un catálogo con un precio mal cargado
    es peor que no ofrecer nada y pasarle la consulta al equipo.
    """
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ErrorDeCatalogo("No existe el catálogo configurado.") from None
    except json.JSONDecodeError as error:
        raise ErrorDeCatalogo(f"El catálogo no es JSON válido: {error.msg}.") from None
    if not isinstance(datos, dict):
        raise ErrorDeCatalogo("La raíz del catálogo tiene que ser un objeto.")

    ficticio = datos.get("ficticio")
    if not isinstance(ficticio, bool):
        raise ErrorDeCatalogo("'ficticio' tiene que ser true o false.")

    maxima = datos.get("cantidad_maxima_automatica")
    if not _entero_positivo(maxima):
        raise ErrorDeCatalogo("'cantidad_maxima_automatica' debe ser un entero positivo.")

    descuentos = tuple(
        sorted(
            (_descuento(crudo) for crudo in _lista(datos, "descuentos_por_cantidad")),
            key=lambda descuento: descuento.desde,
        )
    )

    productos: list[Producto] = []
    vistos: set[str] = set()
    for crudo in _lista(datos, "productos"):
        if not isinstance(crudo, dict):
            raise ErrorDeCatalogo("Cada producto tiene que ser un objeto.")
        activo = crudo.get("activo")
        if not isinstance(activo, bool):
            raise ErrorDeCatalogo("'activo' tiene que ser true o false en cada producto.")
        if not activo:
            # Un producto retirado no se ofrece ni se valida: su foto vieja
            # puede no existir más y no tiene que tirar abajo el resto.
            continue
        producto = _producto(crudo, raiz)
        if producto.sku.upper() in vistos:
            raise ErrorDeCatalogo(f"El código {producto.sku} está repetido.")
        vistos.add(producto.sku.upper())
        productos.append(producto)

    return Catalogo(
        negocio=_texto(datos, "negocio"),
        moneda=_texto(datos, "moneda"),
        ficticio=ficticio,
        cantidad_maxima=maxima,
        descuentos=descuentos,
        productos=tuple(productos),
    )


# -- Cotización ----------------------------------------------------------------


def cotizar(
    catalogo: Catalogo,
    codigo: str,
    cantidad: int,
    tallas: list[str] | tuple[str, ...] = (),
    extras: list[str] | tuple[str, ...] = (),
    diseno_propio: bool = False,
) -> Cotizacion:
    """Calcula el precio de un pedido con las reglas del catálogo.

    El descuento se aplica solo al precio base y se redondea a centavos por
    unidad antes de sumar extras y multiplicar. Es el orden en que lo haría
    una persona con calculadora, y así el desglose que ve el cliente cierra.
    """
    producto = catalogo.producto(codigo)

    if diseno_propio:
        raise NecesitaUnaPersona(
            "los logos, escudos y diseños nuevos los evalúa el equipo"
        )
    if not producto.cotizacion_automatica:
        raise NecesitaUnaPersona(f"{producto.nombre} no tiene precio automático")
    if isinstance(cantidad, bool) or not isinstance(cantidad, int) or cantidad < 1:
        raise ConsultaInvalida("La cantidad tiene que ser un número entero de 1 o más.")
    if cantidad > catalogo.cantidad_maxima:
        raise NecesitaUnaPersona(
            f"los pedidos de más de {catalogo.cantidad_maxima} unidades los cotiza el equipo"
        )

    pedidas = tuple(
        talla.strip().upper() for talla in tallas if isinstance(talla, str) and talla.strip()
    )
    if producto.tallas:
        if not pedidas:
            raise ConsultaInvalida(
                f"Falta la talla. Opciones: {', '.join(producto.tallas)}."
            )
        fuera = [talla for talla in pedidas if talla not in producto.tallas]
        if fuera:
            raise NecesitaUnaPersona(
                f"las tallas {', '.join(fuera)} no están en la lista y requieren revisión"
            )
    else:
        # Una taza no tiene talla: si el modelo manda una, no cambia nada.
        pedidas = ()

    disponibles: dict[str, Extra] = {}
    for extra in producto.extras:
        disponibles[extra.codigo] = extra
        disponibles[_normalizar(extra.nombre)] = extra

    elegidos: list[Extra] = []
    for pedido in extras:
        clave = _normalizar(pedido)
        if not clave:
            continue
        if clave not in disponibles:
            ofrecidos = ", ".join(extra.codigo for extra in producto.extras) or "ninguno"
            raise ConsultaInvalida(
                f"{producto.sku} no ofrece el extra '{pedido}'. Extras disponibles: {ofrecidos}."
            )
        if disponibles[clave] not in elegidos:
            elegidos.append(disponibles[clave])

    descuento = None
    for candidato in catalogo.descuentos:
        if cantidad >= candidato.desde:
            descuento = candidato

    porcentaje = descuento.porcentaje if descuento else Decimal(0)
    base = (producto.precio_base * (100 - porcentaje) / 100).quantize(
        CENTAVOS, rounding=ROUND_HALF_UP
    )
    extras_por_unidad = sum((extra.precio for extra in elegidos), Decimal(0))
    unitario = base + extras_por_unidad

    return Cotizacion(
        producto=producto,
        cantidad=cantidad,
        tallas=pedidas,
        extras=tuple(elegidos),
        descuento=descuento,
        base_con_descuento=base,
        extras_por_unidad=extras_por_unidad,
        unitario=unitario,
        total=(unitario * cantidad).quantize(CENTAVOS),
    )


# -- Textos para el modelo -----------------------------------------------------


def texto_del_catalogo(catalogo: Catalogo, categoria: str = "") -> str:
    filtro = _normalizar(categoria)
    productos = [
        producto
        for producto in catalogo.productos
        if not filtro or filtro in _normalizar(producto.categoria)
    ]
    if not catalogo.productos:
        return "El catálogo no tiene productos disponibles. Ofrecé pasar la consulta al equipo."
    if not productos:
        categorias = sorted({producto.categoria for producto in catalogo.productos})
        return (
            f"No hay productos en la categoría '{categoria}'. "
            f"Categorías disponibles: {', '.join(categorias)}."
        )

    lineas = [
        f"Catálogo de {catalogo.negocio}"
        + (" (productos y precios ficticios de demostración)" if catalogo.ficticio else "")
        + "."
    ]
    for producto in productos:
        partes = [
            producto.sku,
            producto.nombre,
            f"categoría {producto.categoria}",
            f"incluye: {producto.incluye}",
            f"{_dinero(catalogo, producto.precio_base)} por unidad",
        ]
        if producto.tallas:
            partes.append(f"tallas: {', '.join(producto.tallas)}")
        if producto.extras:
            partes.append(
                "extras: "
                + ", ".join(
                    f"{extra.codigo} ({extra.nombre}, +{_dinero(catalogo, extra.precio)} por unidad)"
                    for extra in producto.extras
                )
            )
        if not producto.cotizacion_automatica:
            partes.append("el precio lo confirma el equipo")
        lineas.append("- " + " · ".join(partes))

    if catalogo.descuentos:
        tramos = ", ".join(
            f"desde {descuento.desde} unidades {_porcentaje(descuento.porcentaje)}"
            for descuento in catalogo.descuentos
        )
        lineas.append(
            f"Descuentos por cantidad sobre el precio base, no sobre extras: {tramos}. "
            f"Más de {catalogo.cantidad_maxima} unidades lo cotiza el equipo."
        )
    lineas.append("Para dar totales usá cotizar_pedido; para mostrar productos, mostrar_fotos.")
    return "\n".join(lineas)


def texto_de_cotizacion(catalogo: Catalogo, cotizacion: Cotizacion) -> str:
    producto = cotizacion.producto
    unidades = "unidad" if cotizacion.cantidad == 1 else "unidades"
    tallas = f", tallas {', '.join(cotizacion.tallas)}" if cotizacion.tallas else ""
    lineas = [
        "Cotización calculada por el sistema"
        + (" con precios ficticios de demostración" if catalogo.ficticio else "")
        + ".",
        f"{producto.sku} {producto.nombre} ({producto.incluye}): "
        f"{cotizacion.cantidad} {unidades}{tallas}.",
        f"Precio base: {_dinero(catalogo, producto.precio_base)} por unidad.",
    ]

    if cotizacion.descuento:
        lineas.append(
            f"Descuento por cantidad (desde {cotizacion.descuento.desde} unidades): "
            f"{_porcentaje(cotizacion.descuento.porcentaje)}, queda en "
            f"{_dinero(catalogo, cotizacion.base_con_descuento)} por unidad."
        )
    elif catalogo.descuentos:
        lineas.append(
            "Sin descuento por cantidad: empieza desde "
            f"{catalogo.descuentos[0].desde} unidades."
        )

    if cotizacion.extras:
        detalle = " + ".join(
            f"{extra.nombre} {_dinero(catalogo, extra.precio)}" for extra in cotizacion.extras
        )
        lineas.append(
            f"Extras por unidad: {detalle} = {_dinero(catalogo, cotizacion.extras_por_unidad)}."
        )

    lineas += [
        f"Precio por unidad: {_dinero(catalogo, cotizacion.unitario)}.",
        f"Total: {_dinero(catalogo, cotizacion.total)}.",
        "No incluye envío, impuestos ni plazo de fabricación: eso lo confirma un asesor.",
    ]
    return "\n".join(lineas)


# -- Herramientas --------------------------------------------------------------


def crear_herramientas_catalogo(ruta_catalogo: Path, *, raiz: Path = RAIZ) -> list:
    """Las tres herramientas de catálogo, atadas al archivo de este bot."""

    def cargar() -> Catalogo:
        # Se lee en cada consulta, igual que el prompt: un catálogo corregido
        # entra sin reiniciar el bot.
        return leer_catalogo(ruta_catalogo, raiz)

    @tool("ver_catalogo")
    def ver_catalogo(categoria: str = "") -> str:
        """Lista los productos que vende este negocio: código, qué incluye, precio base por unidad, tallas, extras y descuentos por cantidad.

        Usala antes de hablar de productos o precios. No existen otros
        productos que los que devuelve. `categoria` es opcional y filtra la
        lista; vacío trae todo.
        """
        try:
            return texto_del_catalogo(cargar(), categoria)
        except Exception:
            # Se traga a propósito: sin catálogo no hay nada correcto que
            # decir de productos, pero la conversación puede seguir. El
            # detalle queda en logs y el modelo recibe una instrucción segura.
            registro.exception("No se pudo leer el catálogo")
            return SIN_CATALOGO

    @tool("mostrar_fotos", response_format="content_and_artifact")
    def mostrar_fotos(codigos: list[str]) -> tuple[str, dict]:
        """Envía a la persona las fotos de hasta tres productos del catálogo, por su código.

        Usala cuando pida ver un producto o cuando la foto ayude a elegir
        entre modelos. El sistema adjunta las fotos al mensaje: no escribas
        enlaces, y si el resultado informa un problema no digas que las
        enviaste.
        """
        try:
            catalogo = cargar()
        except Exception:
            # Mismo motivo que en ver_catalogo: sin catálogo válido no sale
            # ninguna foto, pero la conversación sigue.
            registro.exception("No se pudo leer el catálogo para mostrar fotos")
            return SIN_CATALOGO, {"adjuntos": []}

        encontrados: list[Producto] = []
        faltantes: list[str] = []
        for codigo in codigos or []:
            try:
                producto = catalogo.producto(codigo)
            except ConsultaInvalida:
                faltantes.append(str(codigo))
                continue
            if producto not in encontrados:
                encontrados.append(producto)

        sobrantes = encontrados[MAXIMO_FOTOS:]
        encontrados = encontrados[:MAXIMO_FOTOS]

        partes: list[str] = []
        if encontrados:
            partes.append(
                "Se adjuntan las fotos de: "
                + "; ".join(f"{producto.sku} {producto.nombre}" for producto in encontrados)
                + "."
            )
            if catalogo.ficticio:
                partes.append("Son imágenes ficticias de demostración.")
        if sobrantes:
            partes.append(
                f"Se envían como máximo {MAXIMO_FOTOS} fotos por mensaje; quedaron sin enviar: "
                + ", ".join(producto.sku for producto in sobrantes)
                + "."
            )
        if faltantes:
            partes.append(
                "No existen en el catálogo: "
                + ", ".join(faltantes)
                + ". No inventes esos productos."
            )
        if not partes:
            partes.append("No se indicó ningún código de producto; no se envió ninguna foto.")

        return " ".join(partes), {
            "adjuntos": [artefacto_de_adjunto(producto.imagen) for producto in encontrados]
        }

    @tool("cotizar_pedido")
    def cotizar_pedido(
        codigo: str,
        cantidad: int,
        tallas: list[str] | None = None,
        extras: list[str] | None = None,
        diseno_propio: bool = False,
    ) -> str:
        """Calcula con las reglas del negocio el precio de un pedido de un producto del catálogo.

        Usala siempre que haya que dar un total, un precio con descuento o
        con extras: nunca hagas la cuenta vos. `codigo` es el código del
        producto y `cantidad`, las unidades enteras. `tallas` son las tallas
        pedidas, si el producto las tiene. `extras` son los códigos de los
        extras elegidos (por ejemplo nombre o numero); vacío si no quiere
        ninguno. `diseno_propio` va en true si quiere su logo, escudo o un
        diseño nuevo. Antes de llamarla, preguntá lo que falte y cambie el
        precio.
        """
        try:
            catalogo = cargar()
        except Exception:
            # Mismo motivo que en ver_catalogo: sin catálogo válido no se
            # cotiza, y el modelo lo informa en vez de inventar un precio.
            registro.exception("No se pudo leer el catálogo para cotizar")
            return SIN_CATALOGO

        try:
            cotizacion = cotizar(
                catalogo, codigo, cantidad, tallas or (), extras or (), diseno_propio
            )
        except ConsultaInvalida as error:
            return (
                f"No se pudo cotizar: {error} Preguntale a la persona lo que "
                "falta; no calcules vos."
            )
        except NecesitaUnaPersona as error:
            return (
                f"Este pedido lo cotiza una persona del equipo: {error}. No des "
                "precio ni plazo. Recopilá lo básico del pedido y ofrecé el traspaso."
            )
        return texto_de_cotizacion(catalogo, cotizacion)

    return [ver_catalogo, mostrar_fotos, cotizar_pedido]


# -- Ayudantes -----------------------------------------------------------------


def _producto(crudo: dict, raiz: Path) -> Producto:
    sku = _texto(crudo, "sku")
    tallas = _lista(crudo, "tallas")
    if not all(isinstance(talla, str) and talla.strip() for talla in tallas):
        raise ErrorDeCatalogo(f"{sku}: 'tallas' necesita textos.")
    automatica = crudo.get("cotizacion_automatica")
    if not isinstance(automatica, bool):
        raise ErrorDeCatalogo(f"{sku}: 'cotizacion_automatica' tiene que ser true o false.")

    return Producto(
        sku=sku,
        nombre=_texto(crudo, "nombre"),
        categoria=_texto(crudo, "categoria"),
        incluye=_texto(crudo, "incluye"),
        precio_base=_importe(crudo.get("precio_base"), f"{sku}: 'precio_base'"),
        tallas=tuple(talla.strip().upper() for talla in tallas),
        extras=tuple(_extra(extra, sku) for extra in _lista(crudo, "extras")),
        imagen=imagen_aprobada(_texto(crudo, "imagen"), sku, raiz),
        cotizacion_automatica=automatica,
    )


def _extra(crudo, sku: str) -> Extra:
    if not isinstance(crudo, dict):
        raise ErrorDeCatalogo(f"{sku}: cada extra tiene que ser un objeto.")
    codigo = _texto(crudo, "codigo")
    return Extra(
        codigo=_normalizar(codigo),
        nombre=_texto(crudo, "nombre"),
        precio=_importe(crudo.get("precio"), f"{sku}: el precio del extra {codigo}"),
    )


def _descuento(crudo) -> Descuento:
    if not isinstance(crudo, dict) or not _entero_positivo(crudo.get("desde")):
        raise ErrorDeCatalogo("Cada descuento necesita 'desde' como entero positivo.")
    porcentaje = _importe(crudo.get("porcentaje"), "El porcentaje de descuento")
    if porcentaje >= 100:
        raise ErrorDeCatalogo("Un descuento tiene que ser menor a 100 %.")
    return Descuento(desde=crudo["desde"], porcentaje=porcentaje)


def _importe(valor, nombre: str) -> Decimal:
    # Los importes van como texto en el JSON: un float como 22.1 ya no es
    # exacto al leerlo, y en plata eso termina en un centavo de diferencia.
    if not isinstance(valor, str):
        raise ErrorDeCatalogo(f'{nombre} tiene que ser un texto como "22.00".')
    try:
        numero = Decimal(valor.strip())
    except InvalidOperation:
        raise ErrorDeCatalogo(f"{nombre} no es un número.") from None
    if not numero.is_finite() or numero <= 0:
        raise ErrorDeCatalogo(f"{nombre} tiene que ser positivo.")
    return numero


def _lista(datos: dict, campo: str) -> list:
    valor = datos.get(campo)
    if not isinstance(valor, list):
        raise ErrorDeCatalogo(f"'{campo}' tiene que ser una lista.")
    return valor


def _texto(datos: dict, campo: str) -> str:
    valor = datos.get(campo)
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorDeCatalogo(f"Falta el texto obligatorio '{campo}'.")
    return valor.strip()


def _entero_positivo(valor) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool) and valor > 0


def _normalizar(texto) -> str:
    """Compara sin tildes ni mayúsculas: "Número", "numero" y "NUMERO" son lo mismo."""
    descompuesto = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in descompuesto if not unicodedata.combining(c)).strip().casefold()


def _dinero(catalogo: Catalogo, valor: Decimal) -> str:
    simbolo = "US$" if catalogo.moneda == "USD" else catalogo.moneda
    return f"{simbolo} {valor.quantize(CENTAVOS)}"


def _porcentaje(valor: Decimal) -> str:
    return f"{valor.normalize():f} %"
