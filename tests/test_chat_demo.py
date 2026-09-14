"""Pruebas del chat local de la demo; no llaman a Chatwoot ni a Gemini."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import chat_demo  # noqa: E402

PERMITIDO = {"X-Chat-Demo": "1"}


class DemoFalsa:
    """La bandeja de mentira: anota lo que se mandó y no toca la red."""

    def __init__(self) -> None:
        self.enviados: list[str] = []

    def nueva_conversacion(self) -> int:
        return 7

    def enviar(self, texto: str) -> None:
        self.enviados.append(texto)

    def mensajes(self):
        return 7, []

    def foto(self, mensaje_id: int, adjunto_id: int):
        raise LookupError("La foto no pertenece a esta conversación.")


def cliente(demo=None, base_url="http://127.0.0.1:8765") -> TestClient:
    return TestClient(chat_demo.crear_app(demo or DemoFalsa()), base_url=base_url)


def test_solo_muestra_lo_que_ve_el_cliente():
    payload = [
        {
            "id": 3,
            "message_type": 1,
            "content": "Acá tenés la foto",
            "attachments": [{"id": 9, "file_type": "image"}, {"id": 10, "file_type": "file"}],
        },
        {"id": 1, "message_type": 0, "content": "Quiero ver el azul"},
        {"id": 2, "message_type": 1, "content": "nota del equipo", "private": True},
        {"id": 4, "message_type": 2, "content": "Conversación resuelta"},
        {"id": 5, "message_type": 1, "content": ""},
    ]

    assert chat_demo.mensajes_para_pantalla(payload) == [
        {"id": 1, "autor": "cliente", "texto": "Quiero ver el azul", "fotos": []},
        {
            "id": 3,
            "autor": "negocio",
            "texto": "Acá tenés la foto",
            "fotos": [{"mensaje": 3, "adjunto": 9}],
        },
    ]


def test_otra_pagina_del_navegador_no_puede_escribir_en_la_demo():
    """Sin el header propio, un sitio cualquiera gastaría Gemini desde tu navegador."""
    demo = DemoFalsa()

    respuesta = cliente(demo).post("/api/mensaje", json={"texto": "hola"})

    assert respuesta.status_code == 403
    assert demo.enviados == []


def test_rechaza_un_host_que_no_es_esta_computadora():
    respuesta = cliente(base_url="http://sitio-ajeno.example").get("/")

    assert respuesta.status_code == 400


def test_con_el_header_envia_el_mensaje_sin_espacios_de_mas():
    demo = DemoFalsa()

    respuesta = cliente(demo).post("/api/mensaje", json={"texto": "  hola  "}, headers=PERMITIDO)

    assert respuesta.status_code == 200
    assert demo.enviados == ["hola"]


def test_un_mensaje_demasiado_largo_no_sale():
    demo = DemoFalsa()

    respuesta = cliente(demo).post(
        "/api/mensaje", json={"texto": "x" * (chat_demo.LARGO_MAXIMO + 1)}, headers=PERMITIDO
    )

    assert respuesta.status_code == 422
    assert demo.enviados == []


def test_una_foto_de_otra_conversacion_devuelve_404():
    respuesta = cliente().get("/api/foto/1/2", headers=PERMITIDO)

    assert respuesta.status_code == 404
