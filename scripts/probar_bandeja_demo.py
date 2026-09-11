"""Envía UNA consulta sintética a la bandeja API demo. Puede consumir Gemini.

    python scripts/probar_bandeja_demo.py

Antes de crear nada, comprueba cuenta, permisos del usuario y tipo de bandeja.
No admite la cuenta 1, usuarios SuperAdmin ni bandejas WhatsApp.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agente.config import variables_demo


def validar_destino(valores: dict, consultar) -> tuple[str, int]:
    """Resuelve el destino sin crear contactos, conversaciones ni mensajes."""
    for clave in ("CHATWOOT_URL", "CHATWOOT_TOKEN", "CHATWOOT_CUENTA_ID", "CHATWOOT_BANDEJA_ID"):
        if not valores.get(clave, "").strip():
            raise ValueError(f"Completá {clave} en .env.demo.local.")
    cuenta = str(int(valores["CHATWOOT_CUENTA_ID"]))
    bandeja = int(valores["CHATWOOT_BANDEJA_ID"])
    if int(cuenta) <= 1 or bandeja <= 0:
        raise ValueError("La prueba no puede usar la cuenta de tu agencia ni un ID vacío.")
    if not valores["CHATWOOT_URL"].startswith("https://"):
        raise ValueError("La conexión de prueba necesita HTTPS.")

    perfil = consultar("GET", "/api/v1/profile")
    cuentas = perfil.get("accounts", [])
    if perfil.get("type") == "SuperAdmin" or len(cuentas) != 1:
        raise ValueError("Usá el usuario técnico exclusivo del demo, nunca el SuperAdmin.")
    if str(cuentas[0].get("id")) != cuenta or cuentas[0].get("name") != "Cliente Demo":
        raise ValueError("La credencial no pertenece exclusivamente a Cliente Demo.")
    prefijo = f"/api/v1/accounts/{cuenta}"
    datos = consultar("GET", f"{prefijo}/inboxes")
    encontrada = next((b for b in datos.get("payload", []) if b.get("id") == bandeja), None)
    if not encontrada or encontrada.get("channel_type") != "Channel::Api" or encontrada.get("name") != "Pruebas Demo":
        raise ValueError("El destino tiene que ser la bandeja API Pruebas Demo.")
    return prefijo, bandeja


def ejecutar(valores: dict, consultar) -> int:
    prefijo, bandeja = validar_destino(valores, consultar)
    creado = consultar("POST", f"{prefijo}/contacts", {
        "inbox_id": bandeja,
        "name": "Prueba sintética de Cliente Demo",
        "identifier": f"piloto-demo-{uuid4().hex}",
    })
    datos = creado.get("payload", creado)
    contacto = datos[0] if isinstance(datos, list) else datos.get("contact", datos)
    vinculos = contacto.get("contact_inboxes", [])
    vinculo = next((v for v in vinculos if v.get("inbox", {}).get("id") == bandeja), None)
    if not vinculo and isinstance(datos, dict):
        vinculo = datos.get("contact_inbox")
    if not vinculo or not vinculo.get("source_id") or not contacto.get("id"):
        raise RuntimeError("Chatwoot creó el contacto pero no informó su vínculo con la bandeja. No se envió ningún mensaje.")
    conversacion = consultar("POST", f"{prefijo}/conversations", {
        "source_id": vinculo["source_id"],
        "inbox_id": bandeja,
        "contact_id": contacto["id"],
        "status": "open",
    })
    identificador = int(conversacion["id"])
    # No reintentamos este POST: una respuesta de red perdida no significa
    # que Chatwoot no lo recibió, y repetirlo podría consumir el modelo otra vez.
    consultar("POST", f"{prefijo}/conversations/{identificador}/messages", {
        "content": "¿Cómo te llamás y cuánto cuesta la libreta azul?",
        "message_type": "incoming",
        "private": False,
    })
    print(f"Una consulta enviada a la conversación demo {identificador}. Esperando respuesta…", flush=True)
    for _ in range(15):
        datos = consultar("GET", f"{prefijo}/conversations/{identificador}/messages")
        salientes = [m for m in datos.get("payload", []) if m.get("message_type") in (1, "outgoing") and not m.get("private")]
        if salientes:
            print("Respuesta recibida; revisá en Chatwoot que indique Cliente Demo, demostración y US$ 5.")
            return identificador
        time.sleep(3)
    raise RuntimeError(f"No apareció una respuesta en 45 segundos. Revisá la conversación {identificador} y los logs; no se reenvió la consulta.")


def main() -> int:
    valores = variables_demo()

    def consultar(metodo, camino, datos=None):
        pedido = urllib.request.Request(
            valores.get("CHATWOOT_URL", "").rstrip("/") + camino,
            data=json.dumps(datos).encode("utf-8") if datos is not None else None,
            method=metodo,
            headers={"api_access_token": valores.get("CHATWOOT_TOKEN", ""), "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(pedido, timeout=15) as respuesta:
            return json.load(respuesta)

    ejecutar(valores, consultar)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
