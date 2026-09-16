"""Distingue reserva y asistencia; comprueba límites con tratamientos distintos."""

import pytest

from test_agenda import agenda, reservar, cita, propuesta, propuesta_actual
from agente.agenda import Agenda, herramientas_agenda
from agente.agenda_modelo import ErrorDeAgenda, ReglasAgenda
from agente.agenda_repositorio import RepositorioAgenda
from agente.config import RAIZ


def cambiar(agenda, referencia, fecha="2026-09-22T11:00"):
    agenda.proponer("1", "mover", cita_id=referencia, fecha=fecha)
    agenda.confirmar("1")


def test_agendar_no_confirma_asistencia_y_confirmar_no_reserva_de_nuevo(agenda):
    referencia = reservar(agenda)
    actual = cita(agenda, referencia)
    assert actual["asistencia"] == "pendiente"
    assert agenda.mis_citas("1")[0]["estado"] == "agendada"
    herramienta = next(h for h in herramientas_agenda(agenda) if h.name == "confirmar_asistencia")
    texto = herramienta.invoke({"referencia": referencia}, config={"configurable": {"thread_id": "1"}})
    assert "CONFIRMO ASISTENCIA" in texto
    assert actual["asistencia_codigo"] not in texto
    assert cita(agenda, referencia)["asistencia"] == "pendiente"
    for _ in range(2):
        assert "Asistencia confirmada" in agenda.confirmar_asistencia("1", actual["asistencia_codigo"])
    otra = Agenda(agenda.reglas, RepositorioAgenda(agenda.repo.destino, agenda.repo.negocio), agenda.google, agenda.reloj)
    assert otra.mis_citas("1")[0]["asistencia"] == "confirmada"
    assert agenda.google.creaciones == 1
    assert agenda.google.cambios == 0


def test_asistencia_rechaza_otro_contacto_y_codigo_anterior_al_cambio(agenda):
    referencia = reservar(agenda)
    codigo = cita(agenda, referencia)["asistencia_codigo"]
    with pytest.raises(ErrorDeAgenda):
        agenda.confirmar_asistencia("2", codigo)
    agenda.confirmar_asistencia("1", codigo)
    cambiar(agenda, referencia)
    assert cita(agenda, referencia)["asistencia"] == "pendiente"
    with pytest.raises(ErrorDeAgenda):
        agenda.confirmar_asistencia("1", codigo)
    agenda.confirmar_asistencia("1", cita(agenda, referencia)["asistencia_codigo"])


def test_confirmar_asistencia_sin_codigo_usa_el_ultimo_aviso_y_es_idempotente(agenda):
    referencia = reservar(agenda)
    assert "Asistencia confirmada" in agenda.confirmar_asistencia("1")
    assert "Asistencia confirmada" in agenda.confirmar_asistencia("1")
    assert cita(agenda, referencia)["asistencia"] == "confirmada"
    assert agenda.google.creaciones == 1


def test_cambio_manual_reinicia_asistencia_pero_enlace_no(agenda):
    referencia = reservar(agenda)
    actual = cita(agenda, referencia)
    agenda.confirmar_asistencia("1", actual["asistencia_codigo"])
    evento = agenda.google.eventos[(actual["calendario"], actual["evento_id"])]
    evento["hangoutLink"] = "https://meet.google.com/prueba"
    agenda.sincronizar()
    assert cita(agenda, referencia)["asistencia"] == "confirmada"
    evento["start"]["dateTime"] = "2026-09-22T11:00:00-06:00"
    evento["end"]["dateTime"] = "2026-09-22T11:30:00-06:00"
    agenda.sincronizar()
    assert cita(agenda, referencia)["asistencia"] == "pendiente"
    with pytest.raises(ErrorDeAgenda):
        agenda.confirmar_asistencia("1", actual["asistencia_codigo"])


def test_asistencia_cancelada_o_pasada_no_se_confirma(agenda):
    referencia = reservar(agenda)
    actual = cita(agenda, referencia)
    agenda.reloj_prueba[0] = actual["inicio"] + 1
    with pytest.raises(ErrorDeAgenda):
        agenda.confirmar_asistencia("1", actual["asistencia_codigo"])
    agenda.reloj_prueba[0] = actual["inicio"] - 3600
    agenda.proponer("1", "cancelar", cita_id=referencia)
    agenda.confirmar("1")
    with pytest.raises(ErrorDeAgenda):
        agenda.confirmar_asistencia("1", actual["asistencia_codigo"])


def test_cancelar_ultima_cita_no_confirma_otra_por_error(agenda):
    reservar(agenda, fecha="2026-09-22T09:00")
    ultima = reservar(agenda, fecha="2026-09-22T10:00")
    agenda.proponer("1", "cancelar", cita_id=ultima)
    agenda.confirmar("1")
    with pytest.raises(ErrorDeAgenda, match="identificar"):
        agenda.confirmar_asistencia("1")


def test_cita_heredada_no_asume_asistencia(agenda):
    referencia = reservar(agenda)
    with agenda.repo.transaccion() as db:
        antigua = db.obtener("cita", referencia)
        for campo in ("asistencia", "asistencia_codigo", "asistencia_confirmada_en"):
            antigua.pop(campo)
        db.guardar("cita", antigua)
    assert agenda.mis_citas("1")[0]["asistencia"] == "pendiente"
    assert "CONFIRMO ASISTENCIA" in agenda.solicitar_asistencia("1", referencia)
    assert agenda.google.creaciones == 1


def test_recordatorio_usa_estado_actual_de_asistencia(agenda):
    referencia = reservar(agenda)
    class Canal:
        textos = []
        def enviar_aviso_agenda(self, envio, *args, **kwargs):
            self.textos.append(envio["texto"])
            return {"id": len(self.textos)}
    canal = Canal()
    agenda.enviar_pendientes(canal)
    actual = cita(agenda, referencia)
    agenda.confirmar_asistencia("1", actual["asistencia_codigo"])
    agenda.reloj_prueba[0] = actual["inicio"] - 86400
    agenda.enviar_pendientes(canal)
    assert "Tu asistencia ya está confirmada" in canal.textos[-1]
    assert "CONFIRMO ASISTENCIA" not in canal.textos[-1]


def clinica(agenda):
    agenda.reglas = ReglasAgenda.leer(RAIZ / "agendas/clinica_ejemplo.json")


def agendar_tratamiento(agenda, contacto, servicio, recurso, fecha="2026-09-22T09:00"):
    agenda.proponer(contacto, "alta", servicio=servicio, recurso=recurso, fecha=fecha, nombre="Prueba")
    return agenda.confirmar(contacto)


def test_clinica_cuatro_consultas_y_siguiente_media_hora(agenda):
    clinica(agenda)
    for i in range(1, 5):
        agendar_tratamiento(agenda, str(i), "consulta", f"profesional_{i}")
    disponibles = agenda.disponibilidad("consulta", "2026-09-22")["horarios"]
    assert not any("T09:00" in h["fecha"] for h in disponibles)
    assert sum(h["cupos"] for h in disponibles if "T09:30" in h["fecha"]) == 4


def test_duracion_y_limite_del_tratamiento_se_comparten_entre_profesionales(agenda):
    clinica(agenda)
    opciones = [h for h in agenda.disponibilidad("tratamiento_largo", "2026-09-22")["horarios"] if "T09:00" in h["fecha"]]
    assert len(opciones) == 4
    assert {h["cupos_totales_horario"] for h in opciones} == {2}
    for i in (1, 2):
        ref = agendar_tratamiento(agenda, str(i), "tratamiento_largo", f"profesional_{i}")
        assert cita(agenda, ref)["fin"] - cita(agenda, ref)["inicio"] == 3600
    with pytest.raises(ErrorDeAgenda, match="cupos"):
        agendar_tratamiento(agenda, "3", "tratamiento_largo", "profesional_3", "2026-09-22T09:30")
    with pytest.raises(ErrorDeAgenda, match="cupos"):
        agendar_tratamiento(agenda, "3", "consulta", "profesional_1", "2026-09-22T09:30")
    agendar_tratamiento(agenda, "3", "consulta", "profesional_3", "2026-09-22T09:30")
    agendar_tratamiento(agenda, "4", "tratamiento_largo", "profesional_4", "2026-09-22T10:00")


def test_limite_tratamiento_se_revalida_al_confirmar(agenda):
    clinica(agenda)
    agenda.reglas.servicios["tratamiento_largo"]["capacidad_simultanea"] = 1
    agenda.proponer("2", "alta", servicio="tratamiento_largo", recurso="profesional_2",
                    fecha="2026-09-22T09:00", nombre="Prueba")
    agendar_tratamiento(agenda, "1", "tratamiento_largo", "profesional_1")
    with pytest.raises(ErrorDeAgenda, match="último cupo"):
        agenda.confirmar("2")


def test_cambio_incierto_superpuesto_no_cuenta_dos_veces_misma_persona(agenda):
    agenda.reglas.recursos["asesor"]["capacidad"] = 2
    agenda.reglas.servicios["demo"]["minutos"] = 60
    ref = reservar(agenda)
    agenda.google.falla = "despues"
    cambiar(agenda, ref, "2026-09-22T09:30")
    assert cita(agenda, ref)["pendiente"]
    horarios = agenda.disponibilidad("demo", "2026-09-22")["horarios"]
    assert next(h["cupos"] for h in horarios if "T09:30" in h["fecha"]) == 1


def test_duracion_cambiada_invalida_propuesta(agenda):
    ref = propuesta(agenda)
    agenda.reglas.servicios["demo"]["minutos"] = 60
    with pytest.raises(ErrorDeAgenda, match="duración"):
        agenda.confirmar("1", ref)
    assert agenda.google.creaciones == 0


@pytest.mark.parametrize("limite", [None, 0, -1, True, 1.5, "4", 101])
def test_limite_tratamiento_invalido(limite):
    import json
    datos = json.loads((RAIZ / "agendas/clinica_ejemplo.json").read_text(encoding="utf-8"))
    datos["servicios"]["consulta"]["capacidad_simultanea"] = limite
    with pytest.raises(ErrorDeAgenda):
        ReglasAgenda.desde_dict(datos)
