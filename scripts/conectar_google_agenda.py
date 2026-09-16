"""Conecta Google por OAuth Desktop + PKCE; no muestra tokens en la terminal."""

from __future__ import annotations

import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agente.config import (ErrorDeConfiguracion, _archivo_agenda, cargar_oauth_google,
                           guardar_conexion_agenda, variables_agenda_locales)

ALCANCE = "https://www.googleapis.com/auth/calendar.events"


def conectar(correo, negocio=""):
    valores = variables_agenda_locales(negocio)
    cliente = valores.get("AGENDA_GOOGLE_CLIENTE_ID", "")
    secreto = valores.get("AGENDA_GOOGLE_SECRETO", "")
    if not cliente or not secreto:
        raise ErrorDeConfiguracion("Importá primero un cliente OAuth Desktop con --credenciales datos/google-oauth.json.")
    estado, verificador = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    desafio = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
    resultado = {}

    class Retorno(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            # La URL incluye el código temporal: nunca se registra.
            pass

        def do_GET(self):
            consulta = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            valido = secrets.compare_digest(consulta.get("state", [""])[0], estado)
            if valido:
                resultado.update({k: v[0] for k, v in consulta.items()})
            self.send_response(200 if valido else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(("Podés cerrar esta ventana y volver a la terminal." if valido else "Solicitud inválida.").encode())

    with HTTPServer(("127.0.0.1", 0), Retorno) as servidor:
        servidor.timeout = 1
        retorno = f"http://127.0.0.1:{servidor.server_port}"
        parametros = {"client_id": cliente, "redirect_uri": retorno, "response_type": "code", "scope": ALCANCE + " openid email",
                      "state": estado, "code_challenge": desafio, "code_challenge_method": "S256",
                      "access_type": "offline", "prompt": "consent", "login_hint": correo}
        webbrowser.open("https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(parametros))
        print("Autorizá la cuenta en el navegador. Esperando hasta 5 minutos; no pegues códigos en el chat.", flush=True)
        limite = time.monotonic() + 300
        while not resultado and time.monotonic() < limite:
            servidor.handle_request()
    if not resultado.get("code"):
        raise ErrorDeConfiguracion("No se recibió autorización de Google.")
    datos = urllib.parse.urlencode({"client_id": cliente, "client_secret": secreto, "code": resultado["code"],
                                    "code_verifier": verificador, "redirect_uri": retorno,
                                    "grant_type": "authorization_code"}).encode()
    try:
        with urllib.request.urlopen("https://oauth2.googleapis.com/token", data=datos, timeout=20) as respuesta:
            tokens = json.load(respuesta)
    except urllib.error.URLError:
        raise ErrorDeConfiguracion("Google rechazó la conexión OAuth; revisá el cliente y volvé a autorizar.") from None
    if not tokens.get("refresh_token") or ALCANCE not in tokens.get("scope", "").split():
        raise ErrorDeConfiguracion("Google no concedió acceso offline y edición de eventos.")
    pedido = urllib.request.Request("https://openidconnect.googleapis.com/v1/userinfo",
                                    headers={"Authorization": "Bearer " + tokens["access_token"]})
    with urllib.request.urlopen(pedido, timeout=15) as respuesta:
        identidad = json.load(respuesta)
    if identidad.get("email", "").lower() != correo.lower() or identidad.get("email_verified") is not True:
        raise ErrorDeConfiguracion("La cuenta autorizada no coincide con el correo solicitado.")
    guardar_conexion_agenda({"AGENDA_GOOGLE_REFRESH_TOKEN": tokens["refresh_token"]}, negocio)
    print(f"Conexión guardada en {_archivo_agenda(negocio).name}, excluido de Git. "
          "La agenda de producción todavía no se activó.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credenciales", type=Path, help="JSON OAuth Desktop en una carpeta privada, como datos/.")
    parser.add_argument("--correo", required=True, help="Cuenta Google que se va a autorizar.")
    parser.add_argument("--negocio", default="", help="Negocio de sus reglas de agenda, por ejemplo "
                        "clinica-ejemplo. Guarda en .env.agenda.<negocio>.local para no pisar otro cliente. "
                        "Sin este dato usa .env.agenda.local.")
    args = parser.parse_args()
    try:
        if args.credenciales:
            cargar_oauth_google(args.credenciales, args.negocio)
        conectar(args.correo, args.negocio)
    except (ErrorDeConfiguracion, OSError, ValueError) as error:
        print(f"No se completó la conexión: {type(error).__name__}: "
              + (str(error) if isinstance(error, ErrorDeConfiguracion) else "revisá el archivo local."))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
