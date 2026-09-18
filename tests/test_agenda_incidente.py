"""Regresiones del chat del 17/09: formato, reloj, estado real y avisos."""

from dataclasses import replace
from datetime import datetime
import json

import pytest
from langchain_core.messages import AIMessage, SystemMessage

from test_agenda import agenda, reservar, cita, propuesta
from test_agente import agente_falso, ModeloFalso
from test_agenda_chatwoot import CanalAgenda
from test_chatwoot import cliente, evento
from agente.agenda import Agenda, CONFIRMACION, ASISTENCIA, normalizar_comando_agenda


@pytest.mark.parametrize("texto", ["no confirmar", "no confirmo", "¿confirmar?", "confirmar mañana",
                                  "confirmar pero a las cuatro", "sí", "hoy está bien",
                                  "*no confirmar*", "~CONFIRMAR~", "CONFIRMAR\nmejor a las cuatro"])
def test_normalizar_no_convierte_una_duda_o_cambio_en_autorizacion(texto):
    assert not CONFIRMACION.fullmatch(normalizar_comando_agenda(texto))


@pytest.mark.parametrize("texto", ["_Confirmo asistencia_", "**CONFIRMO ASISTENCIA**", "sí, confirmo mi asistencia"])
def test_asistencia_con_formato_sigue_siendo_explicita(texto):
    assert ASISTENCIA.fullmatch(normalizar_comando_agenda(texto))


def test_reserva_no_pide_asistencia_y_recordatorio_la_pide_solo_a_30_minutos(agenda):
    referencia = reservar(agenda)
    inicio = cita(agenda, referencia)["inicio"]
    canal = CanalAgenda()
    agenda.enviar_pendientes(canal)
    assert len(canal.envios()) == 1
    assert "CONFIRMO ASISTENCIA" not in canal.envios()[0]
    agenda.reloj_prueba[0] = inicio - 86400
    agenda.enviar_pendientes(canal)
    assert len(canal.envios()) == 2
    assert "CONFIRMO ASISTENCIA" not in canal.envios()[-1]
    agenda.reloj_prueba[0] = inicio - 3600
    agenda.enviar_pendientes(canal)
    assert len(canal.envios()) == 2
    agenda.reloj_prueba[0] = inicio - 1800
    agenda.enviar_pendientes(canal)
    agenda.enviar_pendientes(canal)
    assert len(canal.envios()) == 3
    assert "CONFIRMO ASISTENCIA" in canal.envios()[-1]


def test_asistencia_ya_confirmada_no_se_vuelve_a_pedir_a_30_minutos(agenda):
    referencia = reservar(agenda)
    canal = CanalAgenda()
    agenda.enviar_pendientes(canal)
    agenda.confirmar_asistencia("1")
    agenda.reloj_prueba[0] = cita(agenda, referencia)["inicio"] - 1800
    agenda.enviar_pendientes(canal)
    assert "Tu asistencia ya está confirmada" in canal.envios()[-1]
    assert not any("CONFIRMO ASISTENCIA" in texto for texto in canal.envios())


def test_citas_existentes_cambian_el_aviso_de_60_a_30_sin_duplicar_alta(agenda):
    agenda.reglas = replace(agenda.reglas, recordatorios_minutos=(1440, 60))
    referencia = reservar(agenda)
    canal = CanalAgenda()
    agenda.enviar_pendientes(canal)
    nueva = Agenda(replace(agenda.reglas, recordatorios_minutos=(1440, 30)),
                   agenda.repo, agenda.google, agenda.reloj)
    agenda.reloj_prueba[0] = cita(agenda, referencia)["inicio"] - 3600
    nueva.enviar_pendientes(canal)
    with agenda.repo.transaccion() as db:
        assert db.obtener("envio", f"{referencia}:1:recordatorio-60")["estado"] == "anulado"
        assert db.obtener("envio", f"{referencia}:1:recordatorio-30")["estado"] == "pendiente"
    assert len(canal.envios()) == 1
    agenda.reloj_prueba[0] += 1800
    nueva.enviar_pendientes(canal)
    nueva.enviar_pendientes(canal)
    assert len(canal.envios()) == 2
    assert "CONFIRMO ASISTENCIA" in canal.envios()[-1]
    assert agenda.google.creaciones == 1


def test_recordatorio_30_no_sale_despues_de_la_cita(agenda):
    referencia = reservar(agenda)
    canal = CanalAgenda()
    agenda.enviar_pendientes(canal)
    agenda.reloj_prueba[0] = cita(agenda, referencia)["inicio"] + 1
    agenda.enviar_pendientes(canal)
    assert len(canal.envios()) == 1


def test_contexto_incluye_reserva_fuera_del_modelo_hora_y_cita_pasada(agenda):
    propuesta(agenda, fecha="2026-09-21T15:00")
    assert agenda.contexto_actual("1")["ultima_propuesta"]["estado"] == "propuesta"
    referencia = agenda.confirmar("1")
    agenda.confirmar_asistencia("1")
    agenda.reloj_prueba[0] = datetime(2026, 9, 21, 15, 52, tzinfo=agenda.reglas.tz).timestamp()
    contexto = agenda.contexto_actual("1")
    assert contexto["ahora"] == "2026-09-21T15:52:00-06:00"
    assert contexto["ultima_propuesta"]["estado"] == "aceptada"
    assert contexto["citas"][0]["referencia"] == referencia
    assert contexto["citas"][0]["momento"] == "finalizada"
    assert contexto["citas"][0]["asistencia"] == "confirmada"
    assert agenda.contexto_actual("2")["citas"] == []
    assert agenda.contexto_actual("2")["ultima_propuesta"] is None
    assert not agenda.contexto_actual("local")["contacto_verificado"]


def test_contexto_marca_propuesta_vencida(agenda):
    propuesta(agenda)
    agenda.reloj_prueba[0] += 901
    assert agenda.contexto_actual("1")["ultima_propuesta"]["estado"] == "vencida"


def test_webhook_y_siguiente_turno_ven_estado_actual_sin_guardar_reloj_en_memoria(agenda):
    referencia = propuesta(agenda, fecha="2026-09-21T15:00")
    entradas = []
    class ModeloObservador(ModeloFalso):
        def invoke(self, entrada, *args, **kwargs):
            entradas.append(entrada)
            return super().invoke(entrada, *args, **kwargs)
    agente = agente_falso([])
    agente.agenda = agenda
    agente.modelo = ModeloObservador(messages=iter([AIMessage("Tu cita quedó reservada."), AIMessage("Busquemos otro horario.")]))
    agente.grafo = agente._construir_grafo()
    agente.config.chatwoot_bandeja_id = "1"
    canal = CanalAgenda()
    entrada = evento("_CONFIRMAR_", conversacion=1)
    entrada.update(sender={"id": 1, "type": "contact"}, inbox={"id": 1})
    with cliente(canal, agente) as web:
        assert web.post("/chatwoot/secreto", json=entrada).status_code == 200
    assert entradas == []
    agente.responder("¿Ya está reservada?", "1")
    agenda.reloj_prueba[0] = datetime(2026, 9, 21, 16, 12, tzinfo=agenda.reglas.tz).timestamp()
    agente.responder("Se me pasó la hora", "1")
    primero = json.loads(entradas[0][1].content.split("\n", 1)[1])
    segundo = json.loads(entradas[1][1].content.split("\n", 1)[1])
    assert primero["ultima_propuesta"]["estado"] == "aceptada"
    assert segundo["ahora"] == "2026-09-21T16:12:00-06:00"
    assert segundo["citas"][0]["momento"] == "finalizada"
    assert not any(isinstance(m, SystemMessage) for m in agente.historial("1"))
    assert referencia not in segundo["ultima_propuesta"].values()
    assert agenda.google.creaciones == 1
