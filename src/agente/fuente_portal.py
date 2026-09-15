"""Lectura autenticada del catálogo, con caché aislada y archivos verificados.

No usa las tablas de memoria. Una copia pertenece a una URL, una clave de
bot y un negocio esperado; cambiar cualquiera impide reutilizarla.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlsplit
from uuid import uuid4

from .canales.base import AdjuntoSaliente
from .config import RAIZ
from .promociones import FIRMAS_DE_IMAGEN, MAXIMO_IMAGEN

registro = logging.getLogger("agente.portal")
CARPETA_CACHE = RAIZ / "recursos" / "_portal_cache"
MAXIMO_CATALOGO = 5 * 1024 * 1024
MAXIMA_EDAD_CACHE = 300
ClienteHTTP = Callable[[str, str], bytes]


class ErrorDePortal(Exception):
    """No hay datos verificados que se puedan ofrecer."""


class PortalNoDisponible(ErrorDePortal):
    """Falla transitoria: solo permite consultar una copia reciente."""


class AccesoAlPortalRechazado(ErrorDePortal):
    """Una clave revocada no debe seguir accediendo mediante la caché."""


class SinRedirecciones(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ErrorDePortal("El portal redirigió la solicitud; revisá su configuración.")


def validar_origen(url: str) -> str:
    partes = urlsplit(url)
    local = partes.hostname in ("127.0.0.1", "localhost", "::1")
    if (
        not partes.hostname or partes.username or partes.password
        or partes.query or partes.fragment or partes.path.rstrip("/")
        or (partes.scheme != "https" and not (local and partes.scheme == "http"))
    ):
        raise ErrorDePortal("PORTAL_URL debe ser un origen HTTPS, sin ruta ni credenciales.")
    return url.rstrip("/")


def _pedir(metodo: str, url: str, clave_bot: str) -> bytes:
    pedido = urllib.request.Request(
        url, method=metodo, headers={"Authorization": f"Bearer {clave_bot}"}
    )
    try:
        with urllib.request.build_opener(SinRedirecciones).open(pedido, timeout=10) as respuesta:
            contenido = respuesta.read(MAXIMO_CATALOGO + 1)
            if len(contenido) > MAXIMO_CATALOGO:
                raise ErrorDePortal("La respuesta del portal supera 5 MB.")
            return contenido
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise AccesoAlPortalRechazado("El portal rechazó la clave del bot.") from None
        if error.code == 429 or error.code >= 500:
            raise PortalNoDisponible("El portal está temporalmente fuera de servicio.") from None
        raise ErrorDePortal(f"El portal respondió HTTP {error.code}.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise PortalNoDisponible("No se pudo conectar con el portal.") from None


def _guardar_atomico(ruta: Path, contenido: bytes) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    # Los turnos y herramientas pueden correr a la vez. Cada escritor necesita
    # su temporal propio, aunque ambos descarguen exactamente la misma foto.
    temporal = ruta.with_name(f"{uuid4().hex}.tmp")
    try:
        temporal.write_bytes(contenido)
        temporal.replace(ruta)
    finally:
        temporal.unlink(missing_ok=True)


def _validar_publicacion(respuesta: dict, negocio_id: str) -> dict:
    try:
        contenido = respuesta["contenido"]
        negocio = contenido["negocio"]["id"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,40}", negocio):
            raise ValueError
        if negocio_id and negocio != negocio_id:
            raise ErrorDePortal("La clave del portal pertenece a otro negocio.")
        if contenido.get("formato") != 1 or not isinstance(contenido["items"], list):
            raise ValueError
        if not isinstance(contenido["perfil"], dict) or not isinstance(contenido["reglas"], dict):
            raise ValueError
        canonico = json.dumps(contenido, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        if hashlib.sha256(canonico.encode()).hexdigest() != respuesta["huella"]:
            raise ValueError
        codigos = set()
        for item in contenido["items"]:
            sku = item["sku"]
            if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{0,31}", sku) or sku in codigos:
                raise ValueError
            codigos.add(sku)
        return contenido
    except (KeyError, TypeError, ValueError):
        raise ErrorDePortal("La publicación del portal tiene un formato o huella inválidos.") from None


class FuentePortal:
    def __init__(
        self, url: str, clave: str, *, negocio_id: str = "", linea: str = "",
        cache_dir: Path = CARPETA_CACHE, cliente_http: ClienteHTTP | None = None,
        reloj: Callable[[], float] = time.time,
    ):
        self.url = validar_origen(url)
        self.clave = clave
        self.negocio_id = negocio_id
        self.linea = linea
        self.http = cliente_http or (lambda metodo, url: _pedir(metodo, url, clave))
        self.reloj = reloj
        identidad = hashlib.sha256(f"{self.url}\0{clave}\0{negocio_id}".encode()).hexdigest()
        # 128 bits para el nombre del espacio; la clave nunca se guarda.
        # Evita exceder las rutas de Windows con nombres largos de proyecto.
        self.carpeta = Path(cache_dir) / identidad[:32]

    def leer(self, *, permitir_respaldo: bool = True) -> dict:
        archivo = self.carpeta / "catalogo.json"
        respaldo = False
        try:
            crudo = self.http("GET", self.url + "/api/bot/catalogo")
        except AccesoAlPortalRechazado:
            archivo.unlink(missing_ok=True)
            raise
        except PortalNoDisponible:
            # Solo una caída transitoria habilita respaldo. Un 401, 404 o una
            # respuesta inválida no debe resucitar datos retirados o ajenos.
            if not permitir_respaldo:
                raise
            try:
                copia = json.loads(archivo.read_text(encoding="utf-8"))
                edad = self.reloj() - copia["verificado_en"]
                if not 0 <= edad <= MAXIMA_EDAD_CACHE:
                    raise ValueError
                respuesta = copia["publicacion"]
                respaldo = True
            except (OSError, ValueError, KeyError, TypeError):
                raise ErrorDePortal("El portal no contesta y no hay una copia reciente.") from None
        else:
            try:
                if len(crudo) > MAXIMO_CATALOGO:
                    raise ValueError
                respuesta = json.loads(crudo)
            except (ValueError, TypeError):
                raise ErrorDePortal("El portal no devolvió un catálogo válido.") from None
        contenido = _validar_publicacion(respuesta, self.negocio_id)
        if not respaldo:
            try:
                _guardar_atomico(archivo, json.dumps({
                    "verificado_en": self.reloj(), "publicacion": respuesta,
                }, ensure_ascii=False).encode())
            except OSError:
                # La consulta en vivo sigue siendo válida aunque el disco no
                # permita guardar el respaldo; queda registrado para operación.
                registro.warning("No se pudo guardar la copia local del catálogo.")
        return contenido | {
            "_version": respuesta["version"], "_huella": respuesta["huella"],
            "_respaldo": respaldo,
        }

    def foto(self, contenido: dict, item: dict) -> AdjuntoSaliente | None:
        fotos = item.get("fotos") or []
        if not fotos:
            return None
        foto = fotos[0]
        mime = foto.get("mime")
        extension = {"image/jpeg": ".jpg", "image/png": ".png"}.get(mime)
        sha = foto.get("sha256", "")
        identificador = foto.get("id", "")
        if (
            not extension or not re.fullmatch(r"[0-9a-f]{64}", sha)
            or not re.fullmatch(r"[0-9a-f]{32}", identificador)
            or type(foto.get("bytes")) is not int or not 0 < foto["bytes"] <= MAXIMO_IMAGEN
        ):
            raise ErrorDePortal("La foto publicada tiene metadatos inválidos.")
        ruta = self.carpeta / f"{sha}{extension}"

        def coincide(datos: bytes) -> bool:
            return (
                len(datos) == foto["bytes"]
                and hashlib.sha256(datos).hexdigest() == sha
                and any(datos.startswith(firma) for firma in FIRMAS_DE_IMAGEN[mime])
            )

        if ruta.is_file() and ruta.stat().st_size <= MAXIMO_IMAGEN:
            datos = ruta.read_bytes()
        else:
            datos = b""
        if not coincide(datos):
            datos = self.http("GET", self.url + "/api/bot/fotos/" + quote(identificador, safe=""))
            if not coincide(datos):
                raise ErrorDePortal("La foto recibida no coincide con la publicación.")
            _guardar_atomico(ruta, datos)
        return AdjuntoSaliente(ruta=ruta, nombre=item["sku"] + extension, mime=mime, codigo=item["sku"])
