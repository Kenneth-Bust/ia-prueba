"""Catálogo pequeño de promociones con imágenes aprobadas.

Gemini entiende la consulta, pero esta pieza decide qué promoción está
vigente y qué archivo le corresponde. La ruta nunca sale de texto libre del
modelo: viene del catálogo configurado y se valida contra ``recursos/``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

from .canales.base import AdjuntoSaliente
from .config import RAIZ

registro = logging.getLogger("agente.promociones")

MAXIMO_PROMOCIONES = 3
MAXIMO_IMAGEN = 5 * 1024 * 1024
MIME_POR_EXTENSION = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}
FIRMAS_DE_IMAGEN = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}


class ErrorDeCatalogo(Exception):
    """El catálogo no cumple el formato o apunta a un archivo inseguro."""


@dataclass(frozen=True)
class Promocion:
    codigo: str
    titulo: str
    precio_mensual: str
    moneda: str
    limite_conversaciones: int
    incluye: tuple[str, ...]
    vigente_desde: date
    vigente_hasta: date
    condicion_tarifa: str
    llamada_a_la_accion: str
    imagen: AdjuntoSaliente


def promociones_vigentes(
    ruta_catalogo: Path,
    hoy: date | None = None,
    raiz: Path = RAIZ,
) -> list[Promocion]:
    """Lee y valida las promociones activas para la fecha indicada."""
    hoy = hoy or datetime.now(ZoneInfo("America/Managua")).date()
    datos = _leer_json(ruta_catalogo)
    crudas = datos.get("promociones")
    if not isinstance(crudas, list):
        raise ErrorDeCatalogo("El catálogo necesita una lista 'promociones'.")

    vigentes: list[Promocion] = []
    for cruda in crudas:
        promocion = _convertir(cruda, raiz)
        if (
            cruda.get("activa") is True
            and promocion.vigente_desde <= hoy <= promocion.vigente_hasta
        ):
            vigentes.append(promocion)

    return vigentes[:MAXIMO_PROMOCIONES]


def crear_herramienta_promociones(
    ruta_catalogo: Path,
    *,
    raiz: Path = RAIZ,
    hoy_para_pruebas: date | None = None,
):
    """Crea la herramienta atada al catálogo de esta aplicación."""

    @tool("promociones_disponibles", response_format="content_and_artifact")
    def promociones_disponibles() -> tuple[str, dict]:
        """Consulta las promociones comerciales que están vigentes ahora.

        Usala siempre que una persona pregunte qué promociones, ofertas o
        descuentos hay disponibles. El resultado trae las condiciones
        autorizadas y el sistema adjunta automáticamente la imagen correcta.
        No inventes promociones ni uses como vigente una oferta del historial.
        """
        try:
            promociones = promociones_vigentes(
                ruta_catalogo, hoy=hoy_para_pruebas, raiz=raiz
            )
        except Exception as error:
            # Una falla del catálogo no debe cortar toda la conversación. Se
            # registra el detalle técnico y el modelo recibe una instrucción
            # segura: no ofrecer información que no pudimos validar.
            registro.exception("No se pudo consultar el catálogo de promociones")
            return (
                "No se pudo validar el catálogo de promociones. No afirmes "
                "que hay una oferta vigente ni que enviaste una imagen; "
                "ofrecé pasar la consulta al equipo.",
                {"adjuntos": []},
            )

        if not promociones:
            return (
                "No hay promociones vigentes registradas para la fecha actual. "
                "No reutilices ofertas anteriores; ofrecé confirmar con el equipo.",
                {"adjuntos": []},
            )

        bloques = [_texto_para_modelo(promocion) for promocion in promociones]
        return (
            "\n\n".join(bloques),
            {
                "adjuntos": [
                    {
                        "tipo": "archivo_aprobado",
                        "ruta": str(promocion.imagen.ruta),
                        "nombre": promocion.imagen.nombre,
                        "mime": promocion.imagen.mime,
                        "codigo": promocion.imagen.codigo,
                    }
                    for promocion in promociones
                ]
            },
        )

    return promociones_disponibles


def _leer_json(ruta: Path) -> dict:
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ErrorDeCatalogo("No existe el catálogo configurado.") from None
    except json.JSONDecodeError as error:
        raise ErrorDeCatalogo(f"El catálogo no es JSON válido: {error.msg}.") from None
    if not isinstance(datos, dict):
        raise ErrorDeCatalogo("La raíz del catálogo tiene que ser un objeto.")
    return datos


def _convertir(cruda, raiz: Path) -> Promocion:
    if not isinstance(cruda, dict):
        raise ErrorDeCatalogo("Cada promoción tiene que ser un objeto.")

    codigo = _texto_obligatorio(cruda, "codigo")
    desde = _fecha(cruda, "vigente_desde", codigo)
    hasta = _fecha(cruda, "vigente_hasta", codigo)
    if hasta < desde:
        raise ErrorDeCatalogo(f"{codigo}: la fecha final es anterior a la inicial.")

    limite = cruda.get("limite_conversaciones")
    if isinstance(limite, bool) or not isinstance(limite, int) or limite <= 0:
        raise ErrorDeCatalogo(f"{codigo}: 'limite_conversaciones' debe ser positivo.")

    precio = _texto_obligatorio(cruda, "precio_mensual")
    try:
        numero = Decimal(precio)
        if not numero.is_finite() or numero <= 0:
            raise InvalidOperation
    except InvalidOperation:
        raise ErrorDeCatalogo(
            f"{codigo}: 'precio_mensual' debe ser un número positivo."
        ) from None

    incluye = cruda.get("incluye")
    if not isinstance(incluye, list) or not incluye or not all(
        isinstance(item, str) and item.strip() for item in incluye
    ):
        raise ErrorDeCatalogo(f"{codigo}: 'incluye' necesita textos válidos.")

    imagen = _imagen(cruda, codigo, raiz)
    return Promocion(
        codigo=codigo,
        titulo=_texto_obligatorio(cruda, "titulo"),
        precio_mensual=precio,
        moneda=_texto_obligatorio(cruda, "moneda"),
        limite_conversaciones=limite,
        incluye=tuple(item.strip() for item in incluye),
        vigente_desde=desde,
        vigente_hasta=hasta,
        condicion_tarifa=_texto_obligatorio(cruda, "condicion_tarifa"),
        llamada_a_la_accion=_texto_obligatorio(cruda, "llamada_a_la_accion"),
        imagen=imagen,
    )


def _imagen(cruda: dict, codigo: str, raiz: Path) -> AdjuntoSaliente:
    relativa = Path(_texto_obligatorio(cruda, "imagen"))
    if relativa.is_absolute():
        raise ErrorDeCatalogo(f"{codigo}: la imagen debe usar una ruta relativa.")

    raiz = raiz.resolve()
    recursos = (raiz / "recursos").resolve()
    ruta = (raiz / relativa).resolve()
    if not ruta.is_relative_to(recursos):
        raise ErrorDeCatalogo(f"{codigo}: la imagen tiene que estar dentro de recursos/.")
    if not ruta.is_file():
        raise ErrorDeCatalogo(f"{codigo}: no existe la imagen registrada.")

    mime = MIME_POR_EXTENSION.get(ruta.suffix.lower())
    if mime is None:
        raise ErrorDeCatalogo(f"{codigo}: la imagen debe ser JPEG o PNG.")
    if ruta.stat().st_size > MAXIMO_IMAGEN:
        raise ErrorDeCatalogo(f"{codigo}: la imagen supera 5 MB.")
    firma = ruta.read_bytes()[:8]
    if not any(firma.startswith(prefijo) for prefijo in FIRMAS_DE_IMAGEN[mime]):
        raise ErrorDeCatalogo(
            f"{codigo}: el contenido de la imagen no coincide con su extensión."
        )

    return AdjuntoSaliente(
        ruta=ruta,
        nombre=ruta.name,
        mime=mime,
        codigo=codigo,
    )


def _texto_obligatorio(datos: dict, campo: str) -> str:
    valor = datos.get(campo)
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorDeCatalogo(f"Falta el texto obligatorio '{campo}'.")
    return valor.strip()


def _fecha(datos: dict, campo: str, codigo: str) -> date:
    try:
        return date.fromisoformat(_texto_obligatorio(datos, campo))
    except ValueError:
        raise ErrorDeCatalogo(f"{codigo}: '{campo}' debe usar AAAA-MM-DD.") from None


def _texto_para_modelo(promocion: Promocion) -> str:
    moneda = "US$" if promocion.moneda == "USD" else promocion.moneda
    incluye = ", ".join(promocion.incluye)
    limite = f"{promocion.limite_conversaciones:,}".replace(",", ".")
    return (
        f"Promoción vigente {promocion.codigo}: {promocion.titulo}. "
        f"{moneda} {promocion.precio_mensual} al mes, hasta "
        f"{limite} conversaciones mensuales. "
        f"Incluye: {incluye}. Vigente hasta el "
        f"{promocion.vigente_hasta.strftime('%d/%m/%Y')}. "
        f"Condición: {promocion.condicion_tarifa}. "
        f"Siguiente paso: {promocion.llamada_a_la_accion}. "
        "La imagen aprobada se adjuntará automáticamente."
    )
