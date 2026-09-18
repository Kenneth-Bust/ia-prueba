"""Confirmaciones de agenda en el canal real con HTTP reemplazado."""

from copy import deepcopy

import pytest

from test_agenda import agenda, propuesta, cita, reservar
from test_chatwoot import ChatwootFalso, cliente, evento
from test_agente import agente_falso
from agente.agenda_modelo import ErrorDeAgenda
from agente.config import RAIZ


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


@pytest.mark.parametrize("texto", ["AGENDARME", "*Agendarme*", "agéndame", "  Sí, agendarme!  ",
                                  "Confirmar", "*CONFIRMAR*", "_Confirmar_", "**confirmar**",
                                  "`CONFIRMAR`", "“CONFIRMAR”", "  Sí, confirmo!  "])
def test_webhook_confirma_sin_usar_ia(agenda, texto):
    referencia = propuesta(agenda)
    agente = agente_falso([])
    agente.agenda = agenda
    agente.config.chatwoot_bandeja_id = "1"
    canal = CanalAgenda()
    entrada = evento(texto, conversacion=1)
    entrada.update(sender={"id": 1, "type": "contact"}, inbox={"id": 1})
    with cliente(canal, agente) as web:
        resultado = web.post("/chatwoot/secreto", json=entrada)
    assert resultado.status_code == 200
    assert agenda.google.creaciones == 1
    assert len(canal.envios()) == 1
    assert "Cita agendada" in canal.envios()[0]
    assert referencia not in canal.envios()[0]
    assert "Referencia:" not in canal.envios()[0]
    assert "CONFIRMO ASISTENCIA" not in canal.envios()[0]


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


def test_webhook_confirma_asistencia_sin_llamar_al_modelo(agenda):
    referencia = reservar(agenda)
    agente = agente_falso([])
    agente.agenda = agenda
    agente.config.chatwoot_bandeja_id = "1"
    canal = CanalAgenda()
    entrada = evento("Confirmo asistencia", conversacion=1)
    entrada.update(sender={"id": 1, "type": "contact"}, inbox={"id": 1})
    with cliente(canal, agente) as web:
        assert web.post("/chatwoot/secreto", json=entrada).status_code == 200
    assert cita(agenda, referencia)["asistencia"] == "confirmada"
    assert agenda.google.creaciones == 1
    assert any("Asistencia confirmada" in texto for texto in canal.envios())
    actual = cita(agenda, referencia)
    evento_google = agenda.google.eventos[(actual["calendario"], actual["evento_id"])]
    assert evento_google["summary"].startswith("✅ Confirmada —")


def test_salud_publica_estado_visible_y_recordatorios(agenda):
    agente = agente_falso([])
    agente.agenda = agenda
    agente.config.chatwoot_bandeja_id = "1"
    agente.config.agenda_reglas_ruta = RAIZ / "agendas/smarth_house.json"
    with cliente(CanalAgenda(), agente) as web:
        salud = web.get("/salud").json()
    assert salud["agenda_estado_calendario"] == "visible"
    assert salud["agenda_recordatorios_minutos"] == [1440, 30]


def test_plantilla_pide_asistencia_solo_en_el_recordatorio_cercano():
    canal = CanalAgenda(False)
    envio, contacto, cita = aviso()
    cita.update(asistencia="pendiente", asistencia_codigo="abcdef123456")
    canal.enviar_aviso_agenda(envio, contacto, cita, "actualizacion_cita", "es")
    parametros = canal.mensajes[-1]["template_params"]["processed_params"]["body"]
    assert parametros["2"] == "agendada"
    assert "CONFIRMO ASISTENCIA" not in parametros["5"]
    assert "abcdef123456" not in parametros["5"]
    assert parametros["4"] == "No requerida"
    envio.update(tipo="recordatorio-1440", pedir_asistencia=False)
    canal.enviar_aviso_agenda(envio, contacto, cita, "actualizacion_cita", "es")
    assert "CONFIRMO ASISTENCIA" not in canal.mensajes[-1]["content"]
    envio.update(tipo="recordatorio-30", pedir_asistencia=True)
    canal.enviar_aviso_agenda(envio, contacto, cita, "actualizacion_cita", "es")
    assert "CONFIRMO ASISTENCIA" in canal.mensajes[-1]["content"]
    cita["asistencia"] = "confirmada"
    canal.enviar_aviso_agenda(envio, contacto, cita, "actualizacion_cita", "es")
    assert "Tu asistencia ya está confirmada" in canal.mensajes[-1]["content"]
