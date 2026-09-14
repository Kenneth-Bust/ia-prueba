"""Administración del portal de catálogos: negocios, usuarios y claves de bot.

    python scripts/portal_admin.py crear-negocio smarth-house "Smarth House"
    python scripts/portal_admin.py crear-usuario --negocio smarth-house --correo dueno@ejemplo.com --nombre "Dueño" --rol administrador
    python scripts/portal_admin.py dar-acceso --negocio uniformes --correo dueno@ejemplo.com --rol empleado
    python scripts/portal_admin.py cambiar-clave --correo dueno@ejemplo.com
    python scripts/portal_admin.py cambiar-correo --correo viejo@ejemplo.com --nuevo nuevo@ejemplo.com
    python scripts/portal_admin.py clave-bot --negocio smarth-house --nombre agente-ia
    python scripts/portal_admin.py revocar-claves-bot --negocio smarth-house

Es la cuenta técnica de la agencia: no hay pantalla para esto a propósito.
Usa la misma base que el portal (PORTAL_DSN o .env.portal.local).

La contraseña se pide sin mostrarla. Con --generar se crea una al azar y se
guarda en .credenciales-portal.local (ignorado por Git). La clave de un bot
siempre va a ese archivo, para copiarla después a las variables de Coolify.
Ni una ni otra se imprimen: la terminal puede quedar en un historial o en
una captura.
"""

from __future__ import annotations

import argparse
import getpass
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from portal.config import ConfigPortal  # noqa: E402
from portal.modelo import DatosInvalidos, validar_correo, validar_negocio_id, validar_rol  # noqa: E402
from portal.postgres import RepositorioPostgres  # noqa: E402
from portal.repositorio import YaExiste  # noqa: E402
from portal.seguridad import ClaveDebil, hashear_clave, huella, nuevo_token, validar_clave_nueva  # noqa: E402

CREDENCIALES = RAIZ / ".credenciales-portal.local"


def guardar_credencial(descripcion: str, valor: str) -> None:
    momento = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with CREDENCIALES.open("a", encoding="utf-8") as archivo:
        archivo.write(f"# {momento} {descripcion}\n{valor}\n")


def pedir_clave(generar: bool, descripcion: str) -> str:
    if generar:
        clave = secrets.token_urlsafe(15)
        guardar_credencial(descripcion, clave)
        print(f"Contraseña generada y guardada en {CREDENCIALES.name}.")
        return clave
    clave = getpass.getpass("Contraseña nueva: ")
    if clave != getpass.getpass("Repetila: "):
        raise SystemExit("Las contraseñas no coinciden. No se cambió nada.")
    return validar_clave_nueva(clave)


def negocio_existente(repo: RepositorioPostgres, negocio: str) -> str:
    validar_negocio_id(negocio)
    if repo.cliente(negocio) is None:
        raise SystemExit(f"No existe el negocio {negocio}. Crealo primero con crear-negocio.")
    return negocio


def main() -> int:
    # La consola de Windows no siempre acepta tildes: un mensaje de éxito no
    # puede terminar en un error después de que el cambio ya se aplicó.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(description="Administración del portal de catálogos.")
    comandos = parser.add_subparsers(dest="comando", required=True)

    crear_negocio = comandos.add_parser("crear-negocio", help="Crea un negocio nuevo.")
    crear_negocio.add_argument("id", help="Identificador estable, por ejemplo smarth-house.")
    crear_negocio.add_argument("nombre", help="Nombre visible del negocio.")

    crear_usuario = comandos.add_parser("crear-usuario", help="Crea una cuenta y le da acceso a un negocio.")
    crear_usuario.add_argument("--negocio", required=True)
    crear_usuario.add_argument("--correo", required=True)
    crear_usuario.add_argument("--nombre", required=True)
    crear_usuario.add_argument("--rol", required=True, choices=("administrador", "empleado"))
    crear_usuario.add_argument("--generar", action="store_true", help="Genera la contraseña y la guarda en el archivo local.")

    dar_acceso = comandos.add_parser("dar-acceso", help="Da o cambia el acceso de una cuenta existente a un negocio.")
    dar_acceso.add_argument("--negocio", required=True)
    dar_acceso.add_argument("--correo", required=True)
    dar_acceso.add_argument("--rol", required=True, choices=("administrador", "empleado"))

    cambiar_clave = comandos.add_parser("cambiar-clave", help="Cambia la contraseña y cierra las sesiones abiertas.")
    cambiar_clave.add_argument("--correo", required=True)
    cambiar_clave.add_argument("--generar", action="store_true")

    cambiar_correo = comandos.add_parser("cambiar-correo", help="Cambia el correo con el que entra una cuenta. La contraseña queda igual.")
    cambiar_correo.add_argument("--correo", required=True, help="El correo actual.")
    cambiar_correo.add_argument("--nuevo", required=True, help="El correo nuevo.")

    clave_bot = comandos.add_parser("clave-bot", help="Crea la clave con la que un bot lee lo publicado.")
    clave_bot.add_argument("--negocio", required=True)
    clave_bot.add_argument("--nombre", required=True, help="Qué bot la usa, por ejemplo agente-ia.")

    revocar = comandos.add_parser("revocar-claves-bot", help="Anula todas las claves de bot de un negocio.")
    revocar.add_argument("--negocio", required=True)

    argumentos = parser.parse_args()
    config = ConfigPortal.desde_entorno()
    repo = RepositorioPostgres(config.dsn, maximo_conexiones=1)
    try:
        repo.migrar()
        return ejecutar(repo, argumentos)
    except (DatosInvalidos, ClaveDebil) as error:
        raise SystemExit(str(error)) from None
    finally:
        repo.cerrar()


def ejecutar(repo: RepositorioPostgres, argumentos: argparse.Namespace) -> int:
    comando = argumentos.comando

    if comando == "crear-negocio":
        negocio = validar_negocio_id(argumentos.id)
        nombre = argumentos.nombre.strip()
        if not nombre:
            raise SystemExit("El nombre del negocio no puede quedar vacío.")
        try:
            repo.crear_cliente(negocio, nombre)
        except YaExiste:
            raise SystemExit(f"Ya existe el negocio {negocio}. No se cambió nada.") from None
        repo.auditar(negocio, None, "agencia_crear_negocio", {})
        print(f"Negocio creado: {negocio} ({nombre}).")

    elif comando == "crear-usuario":
        negocio = negocio_existente(repo, argumentos.negocio)
        correo = validar_correo(argumentos.correo)
        rol = validar_rol(argumentos.rol)
        if repo.usuario_por_correo(correo) is not None:
            raise SystemExit("Ya hay una cuenta con ese correo. Usá dar-acceso para sumarle un negocio.")
        clave = pedir_clave(argumentos.generar, f"portal: {correo}")
        usuario = repo.crear_usuario(correo, argumentos.nombre.strip() or correo, hashear_clave(clave))
        repo.dar_acceso(usuario, negocio, rol)
        repo.auditar(negocio, None, "agencia_crear_usuario", {"correo": correo, "rol": rol})
        print(f"Cuenta creada: {correo}, {rol} de {negocio}.")

    elif comando == "dar-acceso":
        negocio = negocio_existente(repo, argumentos.negocio)
        correo = validar_correo(argumentos.correo)
        usuario = repo.usuario_por_correo(correo)
        if usuario is None:
            raise SystemExit("No hay una cuenta con ese correo. Creala con crear-usuario.")
        repo.dar_acceso(usuario["id"], negocio, validar_rol(argumentos.rol))
        repo.auditar(negocio, None, "agencia_dar_acceso", {"correo": correo, "rol": argumentos.rol})
        print(f"Acceso listo: {correo}, {argumentos.rol} de {negocio}.")

    elif comando == "cambiar-clave":
        correo = validar_correo(argumentos.correo)
        usuario = repo.usuario_por_correo(correo)
        if usuario is None:
            raise SystemExit("No hay una cuenta con ese correo.")
        clave = pedir_clave(argumentos.generar, f"portal: {correo} (clave nueva)")
        repo.cambiar_clave(usuario["id"], hashear_clave(clave))
        # Si la contraseña se cambió porque alguien más la sabía, su sesión
        # abierta tampoco tiene que seguir sirviendo.
        repo.borrar_sesiones_de(usuario["id"])
        print(f"Contraseña cambiada para {correo}. Se cerraron sus sesiones abiertas.")

    elif comando == "cambiar-correo":
        viejo = validar_correo(argumentos.correo)
        nuevo = validar_correo(argumentos.nuevo)
        usuario = repo.usuario_por_correo(viejo)
        if usuario is None:
            raise SystemExit("No hay una cuenta con ese correo.")
        try:
            repo.cambiar_correo(usuario["id"], nuevo)
        except YaExiste:
            raise SystemExit("Ya hay otra cuenta con el correo nuevo. No se cambió nada.") from None
        # Queda en la actividad de cada negocio al que accede, para que el
        # dueño vea con qué correo se entra ahora.
        for acceso in repo.accesos(usuario["id"]):
            repo.auditar(acceso["cliente_id"], None, "agencia_cambiar_correo", {"de": viejo, "a": nuevo})
        print(f"Correo cambiado: {viejo} pasa a {nuevo}. La contraseña es la misma.")

    elif comando == "clave-bot":
        negocio = negocio_existente(repo, argumentos.negocio)
        token = nuevo_token()
        repo.crear_clave_bot(huella(token), negocio, argumentos.nombre.strip())
        guardar_credencial(f"clave de bot {negocio} / {argumentos.nombre.strip()}", token)
        repo.auditar(negocio, None, "agencia_clave_bot", {"nombre": argumentos.nombre.strip()})
        print(f"Clave de bot creada para {negocio} y guardada en {CREDENCIALES.name}.")

    elif comando == "revocar-claves-bot":
        negocio = negocio_existente(repo, argumentos.negocio)
        cantidad = repo.revocar_claves_bot(negocio)
        repo.auditar(negocio, None, "agencia_revocar_claves_bot", {"cantidad": cantidad})
        print(f"Claves de bot revocadas en {negocio}: {cantidad}.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
