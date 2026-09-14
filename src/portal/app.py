"""La web del portal y la entrada para los bots.

Dos puertas, con autenticaciones distintas a propósito:

- `/api/...` es para personas: cookie de sesión, y el negocio sale de la
  sesión, nunca de lo que mande el navegador.
- `/api/bot/...` es para los bots: una clave por negocio en la cabecera
  Authorization, sin cookies. Solo ve lo **publicado** de ese negocio.

Los endpoints son `def` y no `async def`: el repositorio bloquea (psycopg),
y FastAPI corre los `def` en hilos aparte sin trabar al resto.

Este archivo **no** usa `from __future__ import annotations`: los tipos
`Sesion` y `Administrador` se arman adentro de `crear_app()`, y FastAPI no
puede resolverlos si las anotaciones quedan como texto. Sin eso, toma la
sesión por un campo del cuerpo y responde 422 a todo.
"""

import logging
import re
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi import Path as ParametroDeRuta
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from .almacen import MAXIMO_FOTO, Almacen, FotoInvalida
from .config import ConfigPortal
from .modelo import (
    FORMAS_DE_PAGO,
    MAXIMO_FOTOS_POR_ITEM,
    MONEDAS,
    TIPOS,
    DatosInvalidos,
    armar_contenido,
    huella_de,
    validar_ajustes,
    validar_correo,
    validar_item,
    validar_perfil,
)
from .repositorio import Repositorio, YaExiste
from .seguridad import LimiteDeIntentos, clave_de_relleno, huella, nuevo_token, verificar_clave

ESTATICOS = Path(__file__).parent / "static"
ARCHIVOS_ESTATICOS = ("portal.css", "portal.js")
COOKIE = "portal_sesion"
DURACION_SESION = timedelta(hours=12)
_ID_DE_FOTO = re.compile(r"[0-9a-f]{32}")

registro = logging.getLogger("portal")

# Sin scripts ni estilos en línea: si alguien lograra colar HTML en un
# nombre de producto, el navegador igual se negaría a ejecutarlo.
CABECERAS_DE_SEGURIDAD = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' blob:; script-src 'self'; "
        "style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
}

Id = Annotated[int, ParametroDeRuta(ge=1, le=2**63 - 1)]
Cuerpo = Annotated[dict, Body()]


def crear_app(
    repo: Repositorio,
    almacen: Almacen,
    config: ConfigPortal,
    reloj=lambda: datetime.now(timezone.utc),
) -> FastAPI:
    """Arma el portal. Los tests le pasan un repositorio en memoria."""
    app = FastAPI(title="Portal de catálogos", docs_url=None, redoc_url=None, openapi_url=None)

    # Por correo, pocos fallos. Por dirección, más: detrás del proxy de
    # Coolify varias personas pueden compartirla si no llega la real.
    intentos_por_correo = LimiteDeIntentos(maximo=5)
    intentos_por_direccion = LimiteDeIntentos(maximo=20)

    # -- Protecciones comunes ---------------------------------------------------

    @app.middleware("http")
    async def proteger(request: Request, call_next):
        ruta = request.url.path
        host = (request.headers.get("host") or "").lower()
        # /salud queda afuera: el chequeo de Coolify entra por localhost.
        if config.hosts_permitidos and ruta != "/salud" and host not in config.hosts_permitidos:
            return JSONResponse({"error": "Dirección no permitida."}, status_code=400)

        if (
            ruta.startswith("/api/")
            and not ruta.startswith("/api/bot/")
            and request.method not in ("GET", "HEAD")
            and request.headers.get("x-portal") != "1"
        ):
            # Otra página no puede agregar esta cabecera sin permiso de CORS,
            # que el portal no da. Con la cookie SameSite=Strict, cierra la
            # puerta a que un sitio ajeno haga cambios en nombre de alguien.
            return JSONResponse({"error": "Pedido rechazado."}, status_code=403)

        respuesta = await call_next(request)
        for nombre, valor in CABECERAS_DE_SEGURIDAD.items():
            respuesta.headers.setdefault(nombre, valor)
        if ruta.startswith("/api/"):
            respuesta.headers.setdefault("Cache-Control", "no-store")
        return respuesta

    @app.exception_handler(DatosInvalidos)
    @app.exception_handler(FotoInvalida)
    async def datos_invalidos(request: Request, error: ValueError):
        return JSONResponse({"error": str(error)}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def error_http(request: Request, error: StarletteHTTPException):
        return JSONResponse({"error": error.detail}, status_code=error.status_code, headers=error.headers)

    @app.exception_handler(RequestValidationError)
    async def formato_invalido(request: Request, error: RequestValidationError):
        return JSONResponse({"error": "El pedido no tiene el formato esperado."}, status_code=422)

    # -- Quién pide -------------------------------------------------------------

    def sesion_actual(request: Request) -> dict:
        token = request.cookies.get(COOKIE)
        if not token:
            raise HTTPException(401, "Iniciá sesión.")
        sesion = repo.sesion(huella(token), reloj())
        if sesion is None:
            raise HTTPException(401, "Tu sesión venció. Iniciá sesión de nuevo.")
        return sesion

    def administrador(sesion: Annotated[dict, Depends(sesion_actual)]) -> dict:
        if sesion["rol"] != "administrador":
            raise HTTPException(
                403, "Tu usuario es de consulta: los cambios los hace el administrador del negocio."
            )
        return sesion

    def negocio_del_bot(request: Request) -> str:
        esquema, _, token = request.headers.get("authorization", "").partition(" ")
        if esquema.lower() != "bearer" or not token.strip():
            raise HTTPException(401, "Falta la clave del bot.")
        cliente_id = repo.cliente_de_clave_bot(huella(token.strip()))
        if cliente_id is None:
            raise HTTPException(401, "Clave de bot inválida.")
        return cliente_id

    Sesion = Annotated[dict, Depends(sesion_actual)]
    Administrador = Annotated[dict, Depends(administrador)]

    # -- Página y salud -----------------------------------------------------------

    @app.get("/salud")
    def salud() -> dict:
        return {"estado": "ok"}

    @app.get("/favicon.ico")
    def sin_icono() -> Response:
        # Todavía no hay ícono propio; sin esto cada visita deja un 404 en la consola.
        return Response(status_code=204)

    @app.get("/")
    def pagina() -> FileResponse:
        return FileResponse(ESTATICOS / "portal.html", headers={"Cache-Control": "no-cache"})

    @app.get("/estaticos/{nombre}")
    def estatico(nombre: str) -> FileResponse:
        if nombre not in ARCHIVOS_ESTATICOS:
            raise HTTPException(404, "No existe.")
        return FileResponse(ESTATICOS / nombre, headers={"Cache-Control": "no-cache"})

    # -- Sesión ---------------------------------------------------------------------

    @app.post("/api/entrar")
    def entrar(datos: Cuerpo, request: Request) -> JSONResponse:
        correo_crudo = datos.get("correo")
        clave = datos.get("clave") if isinstance(datos.get("clave"), str) else ""
        por_correo = "correo:" + (correo_crudo.strip().lower()[:254] if isinstance(correo_crudo, str) else "")
        por_direccion = "ip:" + (request.client.host if request.client else "desconocida")
        if intentos_por_correo.bloqueado(por_correo) or intentos_por_direccion.bloqueado(por_direccion):
            raise HTTPException(429, "Demasiados intentos. Esperá 15 minutos y probá de nuevo.")

        try:
            correo = validar_correo(correo_crudo)
        except DatosInvalidos:
            correo = ""
        usuario = repo.usuario_por_correo(correo) if correo else None
        # Sin usuario se verifica igual contra un hash de relleno: el tiempo
        # de respuesta no delata qué correos tienen cuenta.
        coincide = verificar_clave(clave, usuario["clave_hash"] if usuario else clave_de_relleno())
        accesos = repo.accesos(usuario["id"]) if usuario and coincide and usuario["activo"] else []
        if not accesos:
            intentos_por_correo.registrar_fallo(por_correo)
            intentos_por_direccion.registrar_fallo(por_direccion)
            raise HTTPException(401, "El correo o la contraseña no coinciden.")

        intentos_por_correo.olvidar(por_correo)
        token = nuevo_token()
        repo.crear_sesion(huella(token), usuario["id"], accesos[0]["cliente_id"], reloj() + DURACION_SESION)
        repo.auditar(accesos[0]["cliente_id"], usuario["id"], "entrar", {})

        respuesta = JSONResponse(_datos_de_sesion(repo.sesion(huella(token), reloj()), accesos))
        respuesta.set_cookie(
            COOKIE,
            token,
            max_age=int(DURACION_SESION.total_seconds()),
            httponly=True,
            secure=config.cookie_segura,
            samesite="strict",
            path="/",
        )
        return respuesta

    @app.post("/api/salir")
    def salir(request: Request) -> JSONResponse:
        token = request.cookies.get(COOKIE)
        if token:
            repo.borrar_sesion(huella(token))
        respuesta = JSONResponse({"estado": "ok"})
        respuesta.delete_cookie(COOKIE, path="/", secure=config.cookie_segura, httponly=True, samesite="strict")
        return respuesta

    @app.get("/api/sesion")
    def ver_sesion(sesion: Sesion) -> dict:
        return _datos_de_sesion(sesion, repo.accesos(sesion["usuario_id"]))

    @app.post("/api/sesion/negocio")
    def cambiar_negocio(datos: Cuerpo, sesion: Sesion) -> dict:
        accesos = repo.accesos(sesion["usuario_id"])
        if not any(acceso["cliente_id"] == datos.get("negocio") for acceso in accesos):
            raise HTTPException(404, "No tenés acceso a ese negocio.")
        repo.cambiar_negocio_de_sesion(sesion["huella"], datos["negocio"])
        return _datos_de_sesion(repo.sesion(sesion["huella"], reloj()), accesos)

    # -- Mi negocio y reglas de precio -----------------------------------------------

    @app.get("/api/perfil")
    def ver_perfil(sesion: Administrador) -> dict:
        return repo.perfil(sesion["cliente_id"])

    @app.put("/api/perfil")
    def guardar_perfil(datos: Cuerpo, sesion: Administrador) -> dict:
        perfil = validar_perfil(datos)
        repo.guardar_perfil(sesion["cliente_id"], perfil, sesion["usuario_id"])
        repo.auditar(sesion["cliente_id"], sesion["usuario_id"], "guardar_mi_negocio", {})
        return perfil

    @app.get("/api/ajustes")
    def ver_ajustes(sesion: Administrador) -> dict:
        return repo.ajustes(sesion["cliente_id"])

    @app.put("/api/ajustes")
    def guardar_ajustes(datos: Cuerpo, sesion: Administrador) -> dict:
        ajustes = validar_ajustes(datos)
        repo.guardar_ajustes(sesion["cliente_id"], ajustes, sesion["usuario_id"])
        repo.auditar(sesion["cliente_id"], sesion["usuario_id"], "guardar_reglas", {})
        return ajustes

    # -- Ítems ------------------------------------------------------------------------------

    def fotos_por_item(cliente_id: str) -> dict[int, list[dict]]:
        agrupadas: dict[int, list[dict]] = {}
        for foto in repo.fotos_vigentes(cliente_id):
            agrupadas.setdefault(foto["item_id"], []).append(
                {"id": foto["id"], "mime": foto["mime"], "bytes": foto["bytes"]}
            )
        return agrupadas

    @app.get("/api/items")
    def listar_items(sesion: Administrador) -> list[dict]:
        fotos = fotos_por_item(sesion["cliente_id"])
        return [item | {"fotos": fotos.get(item["id"], [])} for item in repo.items(sesion["cliente_id"])]

    @app.post("/api/items", status_code=201)
    def crear_item(datos: Cuerpo, sesion: Administrador) -> dict:
        item = validar_item(datos)
        try:
            creado = repo.crear_item(sesion["cliente_id"], item)
        except YaExiste:
            raise DatosInvalidos(f"Ya hay un ítem con el código {item['sku']}.") from None
        repo.auditar(sesion["cliente_id"], sesion["usuario_id"], "crear_item", {"sku": item["sku"]})
        return creado | {"fotos": []}

    @app.put("/api/items/{item_id}")
    def actualizar_item(item_id: Id, datos: Cuerpo, sesion: Administrador) -> dict:
        actual = repo.item(sesion["cliente_id"], item_id)
        if actual is None:
            raise HTTPException(404, "No existe ese ítem.")
        item = validar_item(datos, sku_actual=actual["sku"])
        actualizado = repo.actualizar_item(sesion["cliente_id"], item_id, item)
        if actualizado is None:
            raise HTTPException(404, "No existe ese ítem.")
        repo.auditar(sesion["cliente_id"], sesion["usuario_id"], "editar_item", {"sku": actual["sku"]})
        return actualizado | {"fotos": fotos_por_item(sesion["cliente_id"]).get(item_id, [])}

    @app.delete("/api/items/{item_id}")
    def borrar_item(item_id: Id, sesion: Administrador) -> dict:
        actual = repo.item(sesion["cliente_id"], item_id)
        if actual is None or not repo.borrar_item(sesion["cliente_id"], item_id):
            raise HTTPException(404, "No existe ese ítem.")
        repo.auditar(sesion["cliente_id"], sesion["usuario_id"], "borrar_item", {"sku": actual["sku"]})
        return {"estado": "ok"}

    # -- Fotos ----------------------------------------------------------------------------

    @app.post("/api/items/{item_id}/fotos", status_code=201)
    async def subir_foto(item_id: Id, request: Request, sesion: Administrador) -> dict:
        largo = request.headers.get("content-length", "")
        if largo.isdecimal() and int(largo) > MAXIMO_FOTO:
            raise HTTPException(413, "La foto pesa más de 5 MB. Achicala y probá de nuevo.")
        contenido = bytearray()
        # Se corta apenas pasa el tope: sin esto, un archivo enorme entraría
        # entero en memoria antes de rechazarlo.
        async for trozo in request.stream():
            contenido.extend(trozo)
            if len(contenido) > MAXIMO_FOTO:
                raise HTTPException(413, "La foto pesa más de 5 MB. Achicala y probá de nuevo.")
        return await run_in_threadpool(guardar_foto, sesion, item_id, bytes(contenido))

    def guardar_foto(sesion: dict, item_id: int, contenido: bytes) -> dict:
        cliente_id = sesion["cliente_id"]
        if repo.item(cliente_id, item_id) is None:
            raise HTTPException(404, "No existe ese ítem.")
        if len(fotos_por_item(cliente_id).get(item_id, [])) >= MAXIMO_FOTOS_POR_ITEM:
            raise DatosInvalidos(
                f"Cada ítem admite hasta {MAXIMO_FOTOS_POR_ITEM} fotos. Quitá una para subir otra."
            )
        guardado = almacen.guardar(cliente_id, contenido)
        try:
            foto = repo.agregar_foto(cliente_id, item_id, asdict(guardado))
        except LookupError:
            raise HTTPException(404, "No existe ese ítem.") from None
        repo.auditar(cliente_id, sesion["usuario_id"], "subir_foto", {"item_id": item_id, "foto": foto["id"]})
        return {"id": foto["id"], "mime": foto["mime"], "bytes": foto["bytes"]}

    @app.delete("/api/items/{item_id}/fotos/{foto_id}")
    def quitar_foto(item_id: Id, foto_id: str, sesion: Administrador) -> dict:
        if not _ID_DE_FOTO.fullmatch(foto_id) or not repo.retirar_foto(sesion["cliente_id"], item_id, foto_id):
            raise HTTPException(404, "No existe esa foto.")
        repo.auditar(sesion["cliente_id"], sesion["usuario_id"], "quitar_foto", {"item_id": item_id, "foto": foto_id})
        return {"estado": "ok"}

    def respuesta_de_foto(cliente_id: str, foto_id: str) -> Response:
        foto = repo.foto(cliente_id, foto_id) if _ID_DE_FOTO.fullmatch(foto_id) else None
        if foto is None:
            raise HTTPException(404, "No existe esa foto.")
        try:
            contenido = almacen.leer(foto["clave"])
        except (OSError, FotoInvalida) as error:
            registro.error("[%s] no se pudo leer la foto %s: %s", cliente_id, foto_id, error)
            raise HTTPException(404, "La foto no está disponible.") from None
        # Una foto nunca cambia de contenido (cada archivo tiene id propio),
        # así que el navegador y el bot pueden guardarla sin preguntar.
        return Response(
            contenido,
            media_type=foto["mime"],
            headers={"Cache-Control": "private, max-age=86400", "Content-Disposition": "inline"},
        )

    @app.get("/api/fotos/{foto_id}")
    def ver_foto(foto_id: str, sesion: Sesion) -> Response:
        return respuesta_de_foto(sesion["cliente_id"], foto_id)

    # -- Publicar ---------------------------------------------------------------------------

    def borrador(cliente_id: str) -> tuple[dict, str]:
        contenido = armar_contenido(
            repo.cliente(cliente_id),
            repo.perfil(cliente_id),
            repo.ajustes(cliente_id),
            repo.items(cliente_id),
            repo.fotos_vigentes(cliente_id),
        )
        return contenido, huella_de(contenido)

    @app.get("/api/estado")
    def estado(sesion: Administrador) -> dict:
        _, huella_actual = borrador(sesion["cliente_id"])
        ultima = repo.ultima_publicacion(sesion["cliente_id"])
        return {
            "cambios_sin_publicar": ultima is None or ultima["huella"] != huella_actual,
            "historial": repo.publicaciones(sesion["cliente_id"], 10),
        }

    @app.post("/api/publicar")
    def publicar(sesion: Administrador) -> dict:
        contenido, huella_actual = borrador(sesion["cliente_id"])
        ultima = repo.ultima_publicacion(sesion["cliente_id"])
        if ultima is not None and ultima["huella"] == huella_actual:
            return {"sin_cambios": True, "version": ultima["version"]}
        publicacion = repo.publicar(sesion["cliente_id"], contenido, huella_actual, sesion["usuario_id"])
        repo.auditar(sesion["cliente_id"], sesion["usuario_id"], "publicar", {"version": publicacion["version"]})
        return {"sin_cambios": False, "version": publicacion["version"]}

    @app.get("/api/publicado")
    def publicado(sesion: Sesion) -> dict:
        """Lo que ve el bot hoy. Es lo único que ve un empleado."""
        ultima = repo.ultima_publicacion(sesion["cliente_id"])
        if ultima is None:
            return {"publicacion": None}
        return {"publicacion": {k: ultima[k] for k in ("version", "publicada_en", "publicada_por", "contenido")}}

    @app.get("/api/actividad")
    def actividad(sesion: Administrador) -> list[dict]:
        return [
            {"accion": fila["accion"], "en": fila["en"], "detalle": fila["detalle"]}
            for fila in repo.auditoria(sesion["cliente_id"], 30)
        ]

    # -- Para los bots ------------------------------------------------------------------------

    @app.get("/api/bot/catalogo")
    def catalogo_para_bot(request: Request, cliente_id: Annotated[str, Depends(negocio_del_bot)]) -> Response:
        ultima = repo.ultima_publicacion(cliente_id)
        if ultima is None:
            raise HTTPException(404, "El negocio todavía no publicó su catálogo.")
        etiqueta = f'"{ultima["huella"]}"'
        # El bot pregunta seguido; si no cambió nada, no viaja el catálogo.
        if request.headers.get("if-none-match") == etiqueta:
            return Response(status_code=304, headers={"ETag": etiqueta})
        return JSONResponse(
            {k: ultima[k] for k in ("version", "publicada_en", "huella", "contenido")},
            headers={"ETag": etiqueta},
        )

    @app.get("/api/bot/fotos/{foto_id}")
    def foto_para_bot(foto_id: str, cliente_id: Annotated[str, Depends(negocio_del_bot)]) -> Response:
        return respuesta_de_foto(cliente_id, foto_id)

    return app


def _datos_de_sesion(sesion: dict, accesos: list[dict]) -> dict:
    return {
        "usuario": {"nombre": sesion["nombre"], "correo": sesion["correo"]},
        "negocio": {"id": sesion["cliente_id"], "nombre": sesion["negocio"]},
        "rol": sesion["rol"],
        "negocios": [
            {"id": acceso["cliente_id"], "nombre": acceso["nombre"], "rol": acceso["rol"]}
            for acceso in accesos
        ],
        "listas": {"tipos": TIPOS, "monedas": MONEDAS, "formas_de_pago": FORMAS_DE_PAGO},
    }
