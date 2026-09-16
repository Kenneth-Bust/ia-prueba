"""Confirmaciones de agenda en el canal real con HTTP reemplazado."""

from copy import deepcopy

import pytest

from test_agenda import agenda, propuesta, cita
from test_chatwoot import ChatwootFalso, cliente, evento
from test_agente import agente_falso
from agente.agenda_modelo import ErrorDeAgenda


class CanalAgenda(ChatwootFalso):
    def __init__(self, puede_responder=True):
        super().__init__()
        self.bandeja_id = "1"
        self.actual = {"id": 1, "inbox_id": 1, "can_reply": puede_responder, "meta": {"sender": {"id": 1}}}
        self.mensajes = []

    def _api(self, metodo, camino, datos=None):
        if metodo == "GET" and camino == "conversations/1":
            return deepcopy(self.actual)
        if metodo == "GET" and camino.endswith("/messages"):
            return {"payload": deepcopy(self.mensajes)}
        respuesta = super()._api(metodo, camino, datos)
        if metodo == "POST" and camino.endswith("/messages"):
            self.mensajes.append({**deepcopy(datos), "id": respuesta["id"]})
        return respuesta


def aviso():
    return ({"id": "envio-1", "conversacion": "1", "texto": "Cita confirmada", "tipo": "alta"},
            {"cuenta": "1", "bandeja": "1", "contacto": "1:1"},
            {"id": "cita-1", "inicio": 1790000000, "estado": "confirmada", "enlace": "https://meet.google.com/prueba"})


def test_ventana_cerrada_necesita_plantilla_sin_post():
    canal = CanalAgenda(False)
    with pytest.raises(ErrorDeAgenda, match="plantilla"):
        canal.enviar_aviso_agenda(*aviso(), "", "es")
    assert canal.envios() == []


def test_plantilla_utility_con_parametros_y_marca_persistente():
    canal = CanalAgenda(False)
    canal.enviar_aviso_agenda(*aviso(), "actualizacion_cita", "es")
    datos = canal.mensajes[0]
    assert datos["template_params"]["category"] == "UTILITY"
    assert len(datos["template_params"]["processed_params"]["body"]) == 5
    assert datos["content_attributes"]["agenda_envio_id"] == "envio-1"


def test_contacto_cambiado_no_recibe_aviso():
    canal = CanalAgenda()
    canal.actual["meta"]["sender"]["id"] = 2
    with pytest.raises(ErrorDeAgenda, match="destinatario"):
        canal.enviar_aviso_agenda(*aviso(), "", "es")
    assert canal.envios() == []


def test_recupera_post_por_marca_sin_enviar_otra_vez():
    canal = CanalAgenda()
    canal.enviar_aviso_agenda(*aviso(), "", "es")
    assert canal.enviar_aviso_agenda(*aviso(), "", "es", recuperar=True)["id"] == 99
    assert len(canal.envios()) == 1


def test_webhook_confirma_sin_usar_ia(agenda):
    referencia = propuesta(agenda)
    agente = agente_falso([])
    agente.agenda = agenda
    agente.config.chatwoot_bandeja_id = "1"
    canal = CanalAgenda()
    entrada = evento("CONFIRMAR " + referencia, conversacion=1)
    entrada.update(sender={"id": 1, "type": "contact"}, inbox={"id": 1})
    with cliente(canal, agente) as web:
        resultado = web.post("/chatwoot/secreto", json=entrada)
    assert resultado.status_code == 200
    assert agenda.google.creaciones == 1
    assert len(canal.envios()) == 1
    assert "Cita confirmada" in canal.envios()[0]


def test_webhook_otro_contacto_no_puede_confirmar_propuesta(agenda):
    referencia = propuesta(agenda)
    agente = agente_falso([])
    agente.agenda = agenda
    agente.config.chatwoot_bandeja_id = "1"
    canal = CanalAgenda()
    entrada = evento("CONFIRMAR " + referencia, conversacion=2)
    entrada.update(sender={"id": 2, "type": "contact"}, inbox={"id": 1})
    with cliente(canal, agente) as web:
        web.post("/chatwoot/secreto", json=entrada)
    assert agenda.google.creaciones == 0
