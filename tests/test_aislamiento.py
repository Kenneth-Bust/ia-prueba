"""Aislamiento de cuentas/bandejas, sin red ni tokens de proveedores."""

from copy import deepcopy
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from test_agente import agente_falso
from test_chatwoot import evento
from agente.canales.chatwoot import Chatwoot
from agente.config import AJUSTABLES, Config, ErrorDeConfiguracion, RAIZ
from agente.web.webhook import crear_app


def cliente_aislado(monkeypatch, cuenta="2", bandeja="6", respuestas=None):
    agente = agente_falso(respuestas or ["Soy Cliente Demo, una demostración."])
    agente.config = replace(
        agente.config,
        chatwoot_url="https://chatwoot.ejemplo.com",
        chatwoot_token="tecnico-falso",
        chatwoot_cuenta_id=cuenta,
        chatwoot_bandeja_id=bandeja,
        chatwoot_webhook_token="secreto-demo",
        buffer_segundos=0,
        ritmo_humano=False,
        prompt_sistema=RAIZ / "prompts/demo.md",
    )
    llamadas = []

    def api_falsa(canal, metodo, camino, datos=None):
        llamadas.append((canal.cuenta_id, metodo, camino, datos))
        return {"payload": []}

    monkeypatch.setattr(Chatwoot, "_api", api_falsa)
    return TestClient(crear_app(agente.config, agente=agente)), agente, llamadas


def evento_demo():
    crudo = evento("¿Qué vendés?")
    crudo["account"]["id"] = 2
    return crudo


@pytest.mark.parametrize("cambio", [
    {"account": {"id": 1}},
    {"account": None},
    {"account": {}},
    {"account": {"id": True}},
    {"account": {"id": [2]}},
    {"account": [2]},
    {"inbox": {"id": 7}},
    {"inbox": None},
    {"inbox": {"id": False}},
    {"inbox": [6]},
    {"conversation": {"id": 12, "account_id": 1, "labels": []}},
    {"conversation": {"id": 12, "inbox_id": 7, "labels": []}},
    {"inbox_id": 7},
])
def test_otro_origen_no_consulta_api_ni_modelo(monkeypatch, cambio):
    web, agente, llamadas = cliente_aislado(monkeypatch)
    crudo = evento_demo()
    crudo.update(cambio)
    with web:
        respuesta = web.post("/chatwoot/secreto-demo", json=crudo)
    assert respuesta.status_code == 200
    assert respuesta.json() == {"estado": "ignorado"}
    assert llamadas == []
    assert agente.historial("12") == []


@pytest.mark.parametrize("ubicacion", ["inbox", "conversation", "raiz"])
def test_acepta_el_id_de_bandeja_en_las_ubicaciones_de_chatwoot(monkeypatch, ubicacion):
    web, agente, llamadas = cliente_aislado(monkeypatch)
    crudo = evento_demo()
    crudo["account"]["id"] = "2"
    crudo.pop("inbox")
    if ubicacion == "inbox":
        crudo["inbox"] = {"id": "6"}
    elif ubicacion == "conversation":
        crudo["conversation"]["inbox_id"] = "6"
    else:
        crudo["inbox_id"] = "6"
    with web:
        respuesta = web.post("/chatwoot/secreto-demo", json=crudo)
    assert respuesta.json() == {"estado": "recibido"}
    assert agente.historial("12")[-1].content.startswith("Soy Cliente Demo")
    assert all(llamada[0] == "2" for llamada in llamadas)


def test_instalacion_actual_sin_bandeja_sigue_atendiendo_su_cuenta(monkeypatch):
    web, agente, llamadas = cliente_aislado(monkeypatch, cuenta="1", bandeja="")
    crudo = evento()
    crudo.pop("inbox")
    with web:
        assert web.post("/chatwoot/secreto-demo", json=crudo).json()["estado"] == "recibido"
    assert llamadas
    assert agente.historial("12")


def test_evento_ajeno_no_consume_el_identificador_del_mensaje(monkeypatch):
    web, agente, llamadas = cliente_aislado(monkeypatch)
    propio = evento_demo()
    ajeno = deepcopy(propio)
    ajeno["account"]["id"] = 1
    with web:
        assert web.post("/chatwoot/secreto-demo", json=ajeno).json()["estado"] == "ignorado"
        assert web.post("/chatwoot/secreto-demo", json=propio).json()["estado"] == "recibido"
        assert web.post("/chatwoot/secreto-demo", json=propio).json()["estado"] == "ignorado"
    assert len(agente.historial("12")) == 2
    assert len([llamada for llamada in llamadas if llamada[2].endswith("/messages")]) == 1


@pytest.mark.parametrize("cambio", [
    {"private": True},
    {"message_type": "outgoing"},
    {"conversation": {"id": 12, "labels": ["humano"]}},
])
def test_los_filtros_de_atencion_se_conservan_en_demo(monkeypatch, cambio):
    web, agente, llamadas = cliente_aislado(monkeypatch)
    crudo = evento_demo()
    crudo.update(cambio)
    with web:
        assert web.post("/chatwoot/secreto-demo", json=crudo).json()["estado"] == "ignorado"
    assert llamadas == []
    assert agente.historial("12") == []


@pytest.mark.parametrize("crudo", [[], "texto", 5, None])
def test_json_que_no_es_objeto_no_llega_al_canal(monkeypatch, crudo):
    import json
    web, _, llamadas = cliente_aislado(monkeypatch)
    with web:
        respuesta = web.post("/chatwoot/secreto-demo", content=json.dumps(crudo), headers={"Content-Type": "application/json"})
    assert respuesta.status_code == 400
    assert llamadas == []


@pytest.mark.parametrize("valor", ["0", "-1", "todas", "1.5", "true", "２"])
def test_id_de_bandeja_invalido_no_desactiva_el_filtro(monkeypatch, valor):
    monkeypatch.setenv("CHATWOOT_BANDEJA_ID", valor)
    monkeypatch.setenv("GOOGLE_API_KEY", "falsa")
    with pytest.raises(ErrorDeConfiguracion, match="CHATWOOT_BANDEJA_ID"):
        Config.desde_entorno(proveedor="gemini")


def test_bandeja_opcional_desde_config_no_es_ajustable_por_la_web(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "falsa")
    monkeypatch.delenv("CHATWOOT_BANDEJA_ID", raising=False)
    assert Config.desde_entorno(proveedor="gemini").chatwoot_bandeja_id == ""
    monkeypatch.setenv("CHATWOOT_BANDEJA_ID", " 006 ")
    assert Config.desde_entorno(proveedor="gemini").chatwoot_bandeja_id == "6"
    assert "CHATWOOT_BANDEJA_ID" not in AJUSTABLES


def test_dos_bots_con_el_mismo_id_de_conversacion_guardan_memorias_distintas(monkeypatch):
    web_demo, demo, _ = cliente_aislado(monkeypatch)
    web_agencia, agencia, _ = cliente_aislado(monkeypatch, cuenta="1", bandeja="", respuestas=["Soy la agencia."])
    with web_demo, web_agencia:
        web_demo.post("/chatwoot/secreto-demo", json=evento_demo())
        web_agencia.post("/chatwoot/secreto-demo", json=evento("Consulta de la agencia"))
    assert demo.historial("12")[0].content == "¿Qué vendés?"
    assert agencia.historial("12")[0].content == "Consulta de la agencia"
    assert demo.historial("12")[-1].content != agencia.historial("12")[-1].content
