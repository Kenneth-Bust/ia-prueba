"""Despliegue compartido por Codex, Claude y operadores humanos.

    python scripts/desplegar.py comprobar
    python scripts/desplegar.py desplegar
    python scripts/desplegar.py estado ID --commit SHA

Solo administra el despliegue de agente-ia / main. No modifica la
configuración del servidor, las etiquetas de Chatwoot ni la memoria.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from agente.config import ConfigDespliegue, ErrorDeConfiguracion

COOLIFY = "https://appcoolify.automaticnic.online/api/v1"
APLICACION = "inuqmphtxqxzzrw3pyp724kk"
REPOSITORIO = "Kenneth-Bust/ia-prueba"
SALUD = "https://agente.automaticnic.online/salud"


class ErrorDespliegue(Exception):
    """El despliegue no se pudo comprobar o completar."""


class ErrorHTTP(ErrorDespliegue):
    def __init__(self, codigo):
        self.codigo = codigo
        mensajes = {
            401: "Coolify rechazó el token: revisá que esté completo y vigente.",
            403: "Coolify denegó el acceso: revisá permisos, equipo, API Access y Allowed IPs. Para lectura podés usar COOLIFY_READ_TOKEN.",
            404: "Coolify no encontró el recurso: revisá el equipo del token.",
        }
        super().__init__(mensajes.get(codigo, f"Coolify respondió HTTP {codigo}."))


class SinRedirecciones(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Una redirección no debe reenviar el Bearer a otro destino.
        raise ErrorDespliegue("El servidor redirigió la solicitud; revisá la URL antes de continuar.")


def pedir(url: str, token: str = "", metodo: str = "GET", datos=None) -> dict:
    headers = {"Accept": "application/json", "Cache-Control": "no-cache"}
    if token:
        if not url.startswith(COOLIFY + "/"):
            raise ErrorDespliegue("La credencial solo puede enviarse a la API de Coolify configurada.")
        headers["Authorization"] = f"Bearer {token}"
    cuerpo = None
    if datos is not None:
        cuerpo = json.dumps(datos).encode("utf-8")
        headers["Content-Type"] = "application/json"
    pedido = urllib.request.Request(url, data=cuerpo, headers=headers, method=metodo)
    cliente = urllib.request.build_opener(
        SinRedirecciones(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    try:
        with cliente.open(pedido, timeout=20) as respuesta:
            resultado = json.load(respuesta)
    except urllib.error.HTTPError as error:
        # No imprimir cuerpos, URLs del error ni logs: pueden incluir secretos.
        raise ErrorHTTP(error.code) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ErrorDespliegue(
            "Falló la conexión. Si estabas desplegando, comprobá el historial "
            "antes de repetir: la solicitud puede haber sido aceptada."
        ) from None
    except (ValueError, UnicodeError):
        raise ErrorDespliegue("El servidor no devolvió JSON válido.") from None
    if not isinstance(resultado, dict):
        raise ErrorDespliegue("El servidor devolvió una respuesta inesperada.")
    return resultado


def git(*argumentos: str) -> str:
    resultado = subprocess.run(
        ["git", *argumentos], cwd=RAIZ, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30,
    )
    if resultado.returncode:
        raise ErrorDespliegue("No se pudo comprobar Git; revisá el acceso al repositorio.")
    return resultado.stdout.strip()


def comprobar_revision() -> str:
    if git("branch", "--show-current") != "main":
        raise ErrorDespliegue("Este comando solo despliega desde la rama main.")
    if git("status", "--porcelain"):
        raise ErrorDespliegue("Hay cambios locales pendientes. Revisalos, probalos y subilos antes de desplegar.")
    revision = git("rev-parse", "HEAD")
    remota = git("ls-remote", "origin", "refs/heads/main").split()
    if not remota or remota[0] != revision:
        raise ErrorDespliegue("HEAD no coincide con main en GitHub. No se desplegó nada.")
    return revision


def comprobar_aplicacion(config: ConfigDespliegue, revision: str) -> None:
    app = pedir(f"{COOLIFY}/applications/{APLICACION}", config.token_lectura)
    repo = str(app.get("git_repository", "")).removesuffix(".git")
    repo = repo.removeprefix("https://github.com/").removeprefix("git@github.com:")
    if (
        app.get("uuid") != APLICACION
        or app.get("name") != "agente-ia"
        or repo != REPOSITORIO
        or app.get("git_branch") != "main"
    ):
        raise ErrorDespliegue("La aplicación no coincide con agente-ia, su repositorio y main. Revisá Coolify.")
    if app.get("git_commit_sha") not in (None, "", "HEAD", revision):
        raise ErrorDespliegue("Coolify tiene un commit fijado distinto del revisado.")


def iniciar(config: ConfigDespliegue) -> str:
    try:
        respuesta = pedir(f"{COOLIFY}/deploy", config.token, "POST", {"uuid": APLICACION})
    except ErrorHTTP as error:
        if error.codigo != 405:
            raise
        # Versiones anteriores de Coolify exponen este mismo endpoint por GET.
        # Solo se cambia de método ante 405, nunca después de un timeout.
        respuesta = pedir(f"{COOLIFY}/deploy?uuid={APLICACION}", config.token)
    despliegues = respuesta.get("deployments") or []
    if (
        not isinstance(despliegues, list)
        or len(despliegues) != 1
        or not isinstance(despliegues[0], dict)
        or despliegues[0].get("resource_uuid") != APLICACION
    ):
        raise ErrorDespliegue("La respuesta no identifica un único despliegue de agente-ia. Revisá el historial antes de repetir.")
    identificador = str(despliegues[0].get("deployment_uuid", ""))
    if not re.fullmatch(r"[A-Za-z0-9_-]+", identificador):
        raise ErrorDespliegue("Falta un identificador válido de despliegue; comprobá el historial.")
    return identificador


def estado(config: ConfigDespliegue, identificador: str, revision: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", identificador):
        raise ErrorDespliegue("Identificador de despliegue inválido.")
    if not re.fullmatch(r"[a-fA-F0-9]{40}", revision):
        raise ErrorDespliegue("Indicá el commit completo esperado con --commit.")
    resultado = pedir(f"{COOLIFY}/deployments/{identificador}", config.token_lectura)
    if resultado.get("deployment_uuid") != identificador:
        raise ErrorDespliegue("Coolify devolvió otro despliegue.")
    actual = str(resultado.get("status", "desconocido")).lower()
    if actual in ("failed", "cancelled", "canceled"):
        raise ErrorDespliegue(f"El despliegue terminó con estado {actual}. Revisá sus logs en Coolify.")
    if actual in ("finished", "success"):
        if resultado.get("commit") != revision:
            raise ErrorDespliegue("El commit desplegado no coincide con el esperado.")
        # Se compara con el archivo de ESE commit, aunque otro agente ya haya
        # empezado a trabajar en una revisión posterior del repositorio.
        texto = git("show", f"{revision}:prompts/sistema.md")
        esperado = hashlib.sha256(texto.encode("utf-8")).hexdigest()
        salud = pedir(SALUD)
        if salud.get("estado") != "ok" or salud.get("prompt_sha256") != esperado:
            raise ErrorDespliegue("Coolify terminó, pero la salud pública o el prompt todavía no coinciden. Volvé a consultar estado; no repitas Deploy.")
    return actual


def main(argumentos=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("accion", choices=("comprobar", "desplegar", "estado"))
    parser.add_argument("identificador", nargs="?")
    parser.add_argument("--commit", default="")
    args = parser.parse_args(argumentos)
    try:
        config = ConfigDespliegue.desde_entorno()
        if args.accion == "estado":
            actual = estado(config, args.identificador or "", args.commit)
            print(f"Estado: {actual}")
            return 0 if actual in ("finished", "success") else 2

        revision = comprobar_revision()
        comprobar_aplicacion(config, revision)
        print(f"Aplicación y lectura verificadas: agente-ia / main / {revision}", flush=True)
        if args.accion == "comprobar":
            print("No se inició ningún despliegue. El permiso Deploy se comprueba al ejecutarlo.")
            return 0

        pruebas = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=RAIZ)
        if pruebas.returncode:
            raise ErrorDespliegue("Las pruebas fallaron. No se desplegó nada.")
        if comprobar_revision() != revision:
            raise ErrorDespliegue("El código cambió durante las pruebas. Volvé a comprobarlo.")
        identificador = iniciar(config)
        print(f"Despliegue aceptado: {identificador}", flush=True)
        print(f"Para seguirlo: python scripts/desplegar.py estado {identificador} --commit {revision}", flush=True)
        anterior = None
        for _ in range(30):
            actual = estado(config, identificador, revision)
            if actual != anterior:
                print(f"Estado: {actual}", flush=True)
                anterior = actual
            if actual in ("finished", "success"):
                print("Despliegue verificado: commit esperado, servicio sano y prompt correcto.")
                return 0
            time.sleep(10)
        raise ErrorDespliegue("Sigue pendiente después de cinco minutos. Usá el comando estado; no se canceló ni se repitió el despliegue.")
    except (ErrorDeConfiguracion, ErrorDespliegue, subprocess.TimeoutExpired, OSError) as error:
        if isinstance(error, (subprocess.TimeoutExpired, OSError)):
            print("Error local: comprobá que Git y Python estén disponibles.", file=sys.stderr)
        else:
            print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
