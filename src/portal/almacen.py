"""Dónde viven las fotos: una carpeta por negocio, fuera de Git y de la base.

La base guarda qué foto es de qué ítem; el archivo va a disco. Así la base
no se infla con imágenes y la foto que se publicó sigue igual aunque el
dueño suba otra (cada archivo tiene nombre propio y nunca se pisa).

Hoy es un volumen del servidor. Pasar a un almacenamiento compatible con S3
es reemplazar esta clase: nadie más sabe dónde está el archivo.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

MAXIMO_FOTO = 5 * 1024 * 1024  # el mismo tope que acepta WhatsApp para imágenes

# El tipo sale de los primeros bytes, no del nombre ni de lo que diga el
# navegador: cualquiera puede mandar un ejecutable llamado foto.png.
FIRMAS = {
    "image/jpeg": (b"\xff\xd8\xff", ".jpg"),
    "image/png": (b"\x89PNG\r\n\x1a\n", ".png"),
}

_CLAVE = re.compile(r"[a-z0-9][a-z0-9-]{1,40}/[0-9a-f]{32}\.(?:jpg|png)")
_CLIENTE = re.compile(r"[a-z0-9][a-z0-9-]{1,40}")


class FotoInvalida(ValueError):
    """El archivo no es una foto que el portal acepte. El mensaje es para la persona."""


@dataclass(frozen=True)
class ArchivoGuardado:
    id: str
    clave: str
    mime: str
    bytes: int
    sha256: str


def tipo_de_imagen(contenido: bytes) -> str:
    if not contenido:
        raise FotoInvalida("El archivo está vacío.")
    if len(contenido) > MAXIMO_FOTO:
        raise FotoInvalida("La foto pesa más de 5 MB. Achicala y probá de nuevo.")
    for mime, (firma, _) in FIRMAS.items():
        if contenido.startswith(firma):
            return mime
    raise FotoInvalida("Solo se aceptan fotos JPG o PNG.")


class Almacen:
    def __init__(self, carpeta: Path) -> None:
        self.carpeta = Path(carpeta).resolve()

    def guardar(self, cliente_id: str, contenido: bytes) -> ArchivoGuardado:
        if not _CLIENTE.fullmatch(cliente_id):
            raise FotoInvalida("Negocio inválido.")
        mime = tipo_de_imagen(contenido)
        identificador = uuid4().hex
        clave = f"{cliente_id}/{identificador}{FIRMAS[mime][1]}"
        ruta = self._ruta(clave)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        # Se escribe aparte y se renombra: un corte a mitad de camino no deja
        # una foto cortada con el nombre definitivo.
        temporal = ruta.with_name(ruta.name + ".tmp")
        temporal.write_bytes(contenido)
        temporal.replace(ruta)
        return ArchivoGuardado(
            id=identificador,
            clave=clave,
            mime=mime,
            bytes=len(contenido),
            sha256=hashlib.sha256(contenido).hexdigest(),
        )

    def leer(self, clave: str) -> bytes:
        return self._ruta(clave).read_bytes()

    def _ruta(self, clave: str) -> Path:
        # La clave sale de la base, pero igual se valida: una fila corrupta o
        # manipulada no tiene que poder leer cualquier archivo del servidor.
        if not _CLAVE.fullmatch(clave):
            raise FotoInvalida("Archivo inválido.")
        ruta = (self.carpeta / clave).resolve()
        if not ruta.is_relative_to(self.carpeta):
            raise FotoInvalida("Archivo inválido.")
        return ruta
