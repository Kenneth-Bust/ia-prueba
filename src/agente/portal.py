"""El bot leyendo su catálogo del portal, en vez de un archivo del repo.

Ver `docs/portal.md`. Un negocio carga sus promociones (y, más adelante, su
catálogo completo) en `catalogos.automaticnic.online`; este módulo es el lado
del bot: pide `/api/bot/catalogo` con su propia clave, valida lo que llega
igual que `promociones.py` valida el JSON local, y arma la misma clase de
respuesta que ya sabe mandar `agente.py` (texto + adjunto de imagen).

**Qué se guarda en el prompt y qué se lee del portal.** El precio, la
moneda y la fecha límite son datos del negocio: vienen del portal y pueden
cambiar sin tocar código. Cómo se vende —qué incluye el plan, el límite de
conversaciones, el tono— es language de ventas cuidada, y sigue viviendo en
`prompts/sistema.md` como texto fijo: no se inventa a partir de una
descripción libre.

**Qué pasa si el portal no contesta.** Se guarda en disco la última
respuesta buena (`_portal_cache/`, dentro de `recursos/`, mismo lugar donde
ya viven las imágenes aprobadas). Si el portal falla, se usa esa copia en
vez de dejar al bot sin promociones. Esa carpeta se llena en runtime y no
sobrevive un redeploy (recursos/ se copia una sola vez al construir la
imagen) — alcanza para una caída de unos minutos, que es el caso que
importa; una caída de días la nota el negocio de otra forma.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Callable

from langchain_core.tools import tool

from .canales.base import AdjuntoSaliente
from .config import RAIZ
from .promociones import (
    FIRMAS_DE_IMAGEN,
    MAXIMO_IMAGEN,
    artefacto_de_adjunto,
    hoy_en_nicaragua,
)

registro = logging.getLogger("agente.portal")

MAXIMO_PROMOCIONES = 3
TIEMPO_DE_ESPERA = 10
CARPETA_CACHE = RAIZ / "recursos" / "_portal_cache"

ClienteHTTP = Callable[[str, str], bytes]


class ErrorDePortal(Exception):
    """El portal no contestó o lo que devolvió no se puede usar."""


@dataclass(frozen=True)
class PromocionDelPortal:
    codigo: str
    titulo: str
    precio: str
    moneda: str
    unidad: str
    descripcion: str
    vigente_hasta: date | None
    imagen: AdjuntoSaliente | None


def _pedir(metodo: str, url: str, clave_bot: str) -> bytes:
    """Un GET al portal, con la clave del bot. Errores de red → ErrorDePortal."""
    pedido = urllib.request.Request(
        url, method=metodo, headers={"Authorization": f"Bearer {clave_bot}"}
    )
    try:
        with urllib.request.urlopen(pedido, timeout=TIEMPO_DE_ESPERA) as respuesta:
            return respuesta.read()
    except urllib.error.HTTPError as error:
        raise ErrorDePortal(f"{url}: el portal respondió {error.code}.") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ErrorDePortal(f"{url}: no se pudo conectar con el portal ({error}).") from error


def _archivo_cache(cliente_id: str, cache_dir: Path) -> Path:
    return cache_dir / cliente_id / "catalogo.json"


def _catalogo_del_portal(
    url_base: str, clave_bot: str, cache_dir: Path, cliente_http: ClienteHTTP
) -> dict:
    """El `contenido` publicado. Si falla, la última copia buena en disco."""
    try:
        crudo = cliente_http("GET", f"{url_base.rstrip('/')}/api/bot/catalogo")
        respuesta = json.loads(crudo.decode("utf-8"))
        contenido = respuesta["contenido"]
    except Exception as error:
        registro.warning("No se pudo consultar el portal, se busca la última copia: %s", error)
        cliente_id = _cliente_de(cache_dir)
        archivo = _archivo_cache(cliente_id, cache_dir) if cliente_id else None
        if archivo is None or not archivo.exists():
            raise ErrorDePortal("El portal no contestó y no hay una copia guardada.") from error
        return json.loads(archivo.read_text(encoding="utf-8"))

    archivo = _archivo_cache(contenido["negocio"]["id"], cache_dir)
    archivo.parent.mkdir(parents=True, exist_ok=True)
    # Aparte y con reemplazo: un corte a mitad de escritura no deja la copia
    # de respaldo a medio escribir, que sería peor que no tener ninguna.
    temporal = archivo.with_suffix(".tmp")
    temporal.write_text(json.dumps(contenido, ensure_ascii=False), encoding="utf-8")
    temporal.replace(archivo)
    return contenido


def _cliente_de(cache_dir: Path) -> str | None:
    """El negocio de esta clave, a partir de la última copia guardada.

    Cada bot atiende un solo negocio, así que tiene que haber como mucho una
    carpeta guardada. Si hay más de una (o ninguna), no se adivina: sin este
    dato no se puede armar la ruta del archivo de respaldo.
    """
    if not cache_dir.is_dir():
        return None
    candidatos = sorted(cache_dir.glob("*/catalogo.json"))
    return candidatos[0].parent.name if len(candidatos) == 1 else None


def promociones_del_portal(
    url_base: str,
    clave_bot: str,
    *,
    cache_dir: Path = CARPETA_CACHE,
    hoy: date | None = None,
    cliente_http: ClienteHTTP | None = None,
) -> list[PromocionDelPortal]:
    """Las promociones vigentes hoy, tal como las publicó el negocio."""
    hoy = hoy or hoy_en_nicaragua()
    http = cliente_http or (lambda metodo, url: _pedir(metodo, url, clave_bot))
    contenido = _catalogo_del_portal(url_base, clave_bot, cache_dir, http)

    vigentes = []
    for item in contenido.get("items") or []:
        if item.get("tipo") != "promocion" or item.get("precio") is None:
            continue
        desde = date.fromisoformat(item["vigente_desde"]) if item.get("vigente_desde") else None
        hasta = date.fromisoformat(item["vigente_hasta"]) if item.get("vigente_hasta") else None
        if (desde and hoy < desde) or (hasta and hoy > hasta):
            continue
        try:
            precio = Decimal(item["precio"])
            if not precio.is_finite() or precio <= 0:
                raise ValueError
        except (KeyError, ValueError):
            registro.warning("Promoción %s con precio inválido, se omite.", item.get("sku"))
            continue

        fotos = item.get("fotos") or []
        imagen = None
        if fotos:
            try:
                imagen = _foto_aprobada(
                    url_base, clave_bot, contenido["negocio"]["id"], item["sku"], fotos[0], cache_dir, http
                )
            except ErrorDePortal as error:
                registro.warning("No se pudo traer la foto de %s: %s", item["sku"], error)

        vigentes.append(
            PromocionDelPortal(
                codigo=item["sku"],
                titulo=item["nombre"],
                precio=item["precio"],
                moneda=item.get("moneda", "USD"),
                unidad=item.get("unidad", ""),
                descripcion=item.get("descripcion", ""),
                vigente_hasta=hasta,
                imagen=imagen,
            )
        )

    return vigentes[:MAXIMO_PROMOCIONES]


def _foto_aprobada(
    url_base: str,
    clave_bot: str,
    cliente_id: str,
    sku: str,
    foto: dict,
    cache_dir: Path,
    http: ClienteHTTP,
) -> AdjuntoSaliente:
    """Baja la foto si hace falta y la deja como un archivo local aprobado.

    Se guarda una vez por sha256: si el negocio no cambió la foto, las
    consultas siguientes la sirven del disco sin volver a pedirla.
    """
    mime = foto.get("mime")
    extension = {"image/jpeg": ".jpg", "image/png": ".png"}.get(mime)
    if extension is None:
        raise ErrorDePortal(f"tipo de imagen no admitido: {mime!r}.")

    carpeta = cache_dir / cliente_id
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{sku}-{foto['sha256'][:16]}{extension}"

    if not ruta.exists():
        contenido = http("GET", f"{url_base.rstrip('/')}/api/bot/fotos/{foto['id']}")
        if len(contenido) > MAXIMO_IMAGEN:
            raise ErrorDePortal(f"{sku}: la foto supera 5 MB.")
        firma = contenido[:8]
        if not any(firma.startswith(prefijo) for prefijo in FIRMAS_DE_IMAGEN.get(mime, ())):
            raise ErrorDePortal(f"{sku}: el contenido de la foto no coincide con su tipo.")
        temporal = ruta.with_suffix(ruta.suffix + ".tmp")
        temporal.write_bytes(contenido)
        temporal.replace(ruta)

    return AdjuntoSaliente(ruta=ruta, nombre=ruta.name, mime=mime, codigo=sku)


def _texto_para_modelo(promocion: PromocionDelPortal) -> str:
    moneda = "US$" if promocion.moneda == "USD" else ("C$" if promocion.moneda == "NIO" else promocion.moneda)
    partes = [f"Promoción vigente {promocion.codigo}: {promocion.titulo}. {moneda} {promocion.precio}"]
    if promocion.unidad:
        partes.append(f" {promocion.unidad}")
    partes.append(".")
    if promocion.descripcion:
        partes.append(f" {promocion.descripcion}")
    if promocion.vigente_hasta:
        partes.append(f" Vigente hasta el {promocion.vigente_hasta.strftime('%d/%m/%Y')}.")
    if promocion.imagen:
        partes.append(" La imagen aprobada se adjuntará automáticamente.")
    return "".join(partes)


def crear_herramienta_promociones_portal(
    url_base: str,
    clave_bot: str,
    *,
    cache_dir: Path = CARPETA_CACHE,
    hoy_para_pruebas: date | None = None,
    cliente_http: ClienteHTTP | None = None,
):
    """Misma herramienta `promociones_disponibles`, con el portal como fuente.

    El nombre y el contrato son iguales a `promociones.crear_herramienta_
    promociones`: el prompt que ya dice "usá la herramienta promociones_
    disponibles" no se entera de dónde viene el dato.
    """

    @tool("promociones_disponibles", response_format="content_and_artifact")
    def promociones_disponibles() -> tuple[str, dict]:
        """Consulta las promociones comerciales que están vigentes ahora.

        Usala siempre que una persona pregunte qué promociones, ofertas o
        descuentos hay disponibles. El resultado trae el precio y la fecha
        límite autorizados, y el sistema adjunta automáticamente la imagen
        correcta. No inventes promociones ni uses como vigente una oferta
        del historial.
        """
        try:
            promociones = promociones_del_portal(
                url_base, clave_bot, cache_dir=cache_dir, hoy=hoy_para_pruebas, cliente_http=cliente_http
            )
        except Exception:
            registro.exception("No se pudo consultar el portal de catálogos")
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

        return (
            "\n\n".join(_texto_para_modelo(p) for p in promociones),
            {"adjuntos": [artefacto_de_adjunto(p.imagen) for p in promociones if p.imagen]},
        )

    return promociones_disponibles
