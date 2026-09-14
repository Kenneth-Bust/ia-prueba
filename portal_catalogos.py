"""Levanta el portal de catálogos.

    python portal_catalogos.py

En tu computadora abrí http://127.0.0.1:8010. Lee `.env.portal.local`; en el
servidor, las variables las pone Coolify. Al arrancar prepara la base: solo
crea las tablas que falten, no borra nada.

Los negocios, usuarios y claves de bot se crean con `scripts/portal_admin.py`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))


def main() -> None:
    # Que las tildes no rompan la consola de Windows.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    import uvicorn

    from portal.almacen import Almacen
    from portal.app import crear_app
    from portal.config import ConfigPortal
    from portal.postgres import RepositorioPostgres

    config = ConfigPortal.desde_entorno()
    repo = RepositorioPostgres(config.dsn)
    repo.migrar()
    app = crear_app(repo, Almacen(config.carpeta_archivos), config)

    print(f"\n  Portal de catálogos:  http://{config.host}:{config.puerto}\n")
    uvicorn.run(
        app,
        host=config.host,
        port=config.puerto,
        # Detrás del proxy de Coolify, la dirección real de quien entra llega
        # en X-Forwarded-For. Solo se le cree a los proxies de PORTAL_PROXIES.
        proxy_headers=True,
        forwarded_allow_ips=os.getenv("PORTAL_PROXIES", "127.0.0.1"),
        log_level="info",
    )


if __name__ == "__main__":
    main()
