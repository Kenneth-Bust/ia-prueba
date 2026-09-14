"""Configuración del portal: variables del servidor o `.env.portal.local`.

No usa el `.env` del proyecto. Ese archivo es del bot de la agencia y trae
sus claves; el portal lee solo lo suyo (ver `portal/__init__.py`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

RAIZ = Path(__file__).resolve().parents[2]
ARCHIVO_LOCAL = RAIZ / ".env.portal.local"


class ErrorDeConfiguracion(Exception):
    """Falta una variable del portal o está mal puesta."""


@dataclass(frozen=True)
class ConfigPortal:
    dsn: str = field(repr=False)
    carpeta_archivos: Path
    # En el servidor va con HTTPS y la cookie sale marcada Secure. En tu
    # computadora, con http://127.0.0.1, se apaga desde .env.portal.local.
    cookie_segura: bool = True
    host: str = "127.0.0.1"
    puerto: int = 8010
    # Si hay lista, el portal rechaza cualquier otro Host. En tu computadora
    # frena a una página que apunte un dominio propio a 127.0.0.1 para hablar
    # con el portal desde tu navegador (DNS rebinding).
    hosts_permitidos: tuple[str, ...] = ()

    @classmethod
    def desde_entorno(cls, archivo: Path = ARCHIVO_LOCAL) -> "ConfigPortal":
        # El entorno gana: en Coolify las variables las pone el servidor y el
        # archivo local ni siquiera entra en la imagen.
        locales = dotenv_values(archivo, interpolate=False) if archivo.exists() else {}

        def valor(nombre: str, por_defecto: str = "") -> str:
            return (os.getenv(nombre) or locales.get(nombre) or por_defecto).strip()

        dsn = valor("PORTAL_DSN")
        if not dsn:
            raise ErrorDeConfiguracion(
                "Falta PORTAL_DSN. Guardalo en .env.portal.local o en las "
                "variables del servidor; no lo pegues en el chat."
            )

        carpeta = Path(valor("PORTAL_ARCHIVOS", "datos/portal"))
        if not carpeta.is_absolute():
            carpeta = RAIZ / carpeta

        texto_puerto = valor("PUERTO", "8010")
        if not texto_puerto.isdecimal() or not 0 < int(texto_puerto) < 65536:
            raise ErrorDeConfiguracion(f"PUERTO tiene que ser un número de puerto, no '{texto_puerto}'.")
        puerto = int(texto_puerto)

        host = valor("PORTAL_HOST", "127.0.0.1")
        hosts = tuple(
            h.strip().lower() for h in valor("PORTAL_HOSTS").split(",") if h.strip()
        )
        if not hosts and host == "127.0.0.1":
            hosts = (f"127.0.0.1:{puerto}", f"localhost:{puerto}")

        return cls(
            dsn=dsn,
            carpeta_archivos=carpeta,
            cookie_segura=valor("PORTAL_COOKIE_SEGURA", "true").lower()
            in ("1", "true", "si", "sí", "on", "yes"),
            host=host,
            puerto=puerto,
            hosts_permitidos=hosts,
        )
