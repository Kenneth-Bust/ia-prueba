"""Verifica persistencia de la memoria demo entre procesos, con un modelo falso.

    python scripts/probar_memoria_demo.py

Usa únicamente POSTGRES_DSN de .env.demo.local. Crea una conversación sintética
y la elimina al terminar; nunca lee conversaciones de la agencia.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from psycopg.conninfo import conninfo_to_dict

from agente.agente import Agente
from agente.config import Config, RAIZ, variables_demo
from agente.memoria import postgres


class ModeloFalso(GenericFakeChatModel):
    def bind_tools(self, herramientas, **kwargs):
        return self


def configurar_agente() -> Agente:
    valores = variables_demo()
    dsn = valores.get("POSTGRES_DSN", "")
    datos = conninfo_to_dict(dsn)
    if datos.get("dbname") != "memoria_demo" or datos.get("user") != "bot_demo":
        raise ValueError("La prueba solo admite la base memoria_demo con el usuario bot_demo.")
    # No se construye ningún cliente de Gemini: el constructor normal del
    # agente lo haría aunque luego reemplazáramos su modelo.
    agente = Agente.__new__(Agente)
    agente.config = Config(
        proveedor="gemini", modelo="modelo-falso", api_key="sin-proveedor",
        max_tokens=100, memoria_mensajes=20, prompt_sistema=RAIZ / "prompts/demo.md",
        modo="produccion", postgres_dsn=dsn,
    )
    agente.modelo = ModeloFalso(messages=iter([AIMessage("Prueba de Cliente Demo.")]))
    agente.checkpointer = postgres(dsn)
    agente.grafo = agente._construir_grafo()
    return agente


def ejecutar_paso(paso: str, hilo: str) -> None:
    if not hilo.startswith("verificacion-demo-"):
        raise ValueError("La prueba necesita un identificador propio.")
    agente = configurar_agente()
    try:
        if paso == "guardar":
            agente.responder("Mi palabra de prueba es libreta-azul.", hilo)
        elif paso == "leer":
            historial = agente.historial(hilo)
            if len(historial) != 2 or historial[0].content != "Mi palabra de prueba es libreta-azul.":
                raise RuntimeError("No se recuperó el turno completo después de reiniciar.")
        elif paso == "limpiar":
            agente.olvidar(hilo)
        else:
            raise ValueError("Paso de prueba desconocido.")
    finally:
        agente.checkpointer._contexto_abierto.__exit__(None, None, None)


def main() -> int:
    if len(sys.argv) == 3:
        ejecutar_paso(sys.argv[1], sys.argv[2])
        return 0
    if len(sys.argv) != 1:
        raise ValueError("Ejecutá el script sin argumentos.")
    hilo = f"verificacion-demo-{uuid4().hex}"

    def paso(nombre):
        subprocess.run([sys.executable, str(Path(__file__).resolve()), nombre, hilo], check=True)

    try:
        paso("guardar")
        paso("leer")
        print("Memoria demo: el turno sobrevivió al cierre del primer proceso. Sin tokens de IA.")
    finally:
        paso("limpiar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
