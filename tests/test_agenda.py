"""Reservas y fallos con Calendar falso; no envían mensajes ni gastan tokens."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import re
import sys
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agente.agenda import Agenda, herramientas_agenda
from agente.agenda_modelo import ErrorDeAgenda, ReglasAgenda, ocupacion_maxima
from agente.agenda_repositorio import RepositorioAgenda
from agente.calendario_google import ErrorGoogle
from agente.config import RAIZ, dsn_pruebas_agenda


class GoogleFalso:
    def __init__(self):
        self.eventos = {}
        self.creaciones = 0
        self.cambios = 0
        self.falla = ""

    def listar(self, calendario, desde, hasta):
        return [deepcopy(e) for (cal, _), e in list(self.eventos.items()) if cal == calendario and e.get("status") != "cancelled"]

    def obtener(self, calendario, evento):
        return deepcopy(self.eventos.get((calendario, evento)))

    def crear(self, calendario, datos):
        if self.falla == "antes":
            raise ErrorGoogle(503, True)
        if (calendario, datos["id"]) in self.eventos:
            raise ErrorGoogle(409)
        self.creaciones += 1
        evento = {**deepcopy(datos), "etag": '"1"', "status": "confirmed"}
        self.eventos[(calendario, datos["id"])] = evento
        if self.falla == "despues":
            raise ErrorGoogle(0, True)
        return deepcopy(evento)

    def modificar(self, calendario, evento, datos, etag):
        if self.falla == "rechazar":
            raise ErrorGoogle(412)
        original = self.eventos[(calendario, evento)]
        if original["etag"] != etag:
            raise ErrorGoogle(412)
        self.cambios += 1
        original.update(deepcopy(datos))
        original["etag"] = f'"{self.cambios + 1}"'
        if self.falla == "despues":
            raise ErrorGoogle(0, True)
        return deepcopy(original)

    def cancelar(self, calendario, evento, etag):
        if self.eventos[(calendario, evento)]["etag"] != etag:
            raise ErrorGoogle(412)
        del self.eventos[(calendario, evento)]
        if self.falla == "despues":
            raise ErrorGoogle(0, True)
        return {}


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.skipif(not dsn_pruebas_agenda(), reason="PostgreSQL aislado optativo"))])
def agenda(tmp_path, request):
    reglas = ReglasAgenda.leer(RAIZ / "agendas/smarth_house.json")
    destino = dsn_pruebas_agenda() if request.param == "postgres" else str(tmp_path / "agenda.db")
    negocio = "agenda-pruebas-" + uuid4().hex if request.param == "postgres" else reglas.negocio
    repo = RepositorioAgenda(destino, negocio)
    repo.preparar()
    reloj = [datetime(2026, 9, 21, 7, tzinfo=reglas.tz).timestamp()]
    servicio = Agenda(reglas, repo, GoogleFalso(), reloj=lambda: reloj[0])
    servicio.reloj_prueba = reloj
    for i in range(1, 8):
        servicio.registrar_contacto(str(i), str(i), "1", "1")
    yield servicio
    if request.param == "postgres":
        with repo.transaccion() as db:
            db.ejecutar("DELETE FROM agenda_registros WHERE negocio=?", (negocio,))


def propuesta(agenda, conversacion="1", fecha="2026-09-22T09:00", recurso="asesor"):
    texto = agenda.proponer(conversacion, "alta", servicio="demo", recurso=recurso, fecha=fecha, nombre="Persona de prueba")
    return re.search(r"CONFIRMAR ([a-f0-9]{12})", texto)[1]


def reservar(agenda, **kwargs):
    referencia = propuesta(agenda, **kwargs)
    return agenda.confirmar(kwargs.get("conversacion", "1"), referencia)


def cita(agenda, referencia):
    with agenda.repo.transaccion() as db:
        return db.obtener("cita", referencia)


def test_proponer_no_es_reservar_y_reintentar_confirmacion_no_duplica(agenda):
    ref = propuesta(agenda)
    assert agenda.google.creaciones == 0
    primera = agenda.confirmar("1", ref)
    assert agenda.confirmar("1", ref) == primera
    assert agenda.google.creaciones == 1
    assert cita(agenda, primera)["estado"] == "confirmada"


def test_cuatro_cupos_y_quinta_rechazada_con_dos_instancias(agenda):
    agenda.reglas.recursos["asesor"]["capacidad"] = 4
    otras = Agenda(agenda.reglas, RepositorioAgenda(agenda.repo.destino, agenda.repo.negocio), agenda.google, agenda.reloj)
    propuestas = [(str(i), propuesta(agenda, conversacion=str(i))) for i in range(1, 6)]
    def aceptar(par):
        try:
            return otras.confirmar(*par)
        except ErrorDeAgenda:
            return None
    with ThreadPoolExecutor(max_workers=5) as ejecutor:
        resultados = list(ejecutor.map(aceptar, propuestas))
    assert sum(bool(x) for x in resultados) == 4
    assert agenda.google.creaciones == 4


def test_ultimo_cupo_se_revalida_despues_de_la_propuesta(agenda):
    a, b = propuesta(agenda), propuesta(agenda, conversacion="2")
    agenda.confirmar("1", a)
    with pytest.raises(ErrorDeAgenda, match="último cupo"):
        agenda.confirmar("2", b)


def test_timeout_despues_de_crear_se_recupera_tras_reinicio(agenda):
    ref = propuesta(agenda)
    agenda.google.falla = "despues"
    identificador = agenda.confirmar("1", ref)
    assert cita(agenda, identificador)["estado"] == "pendiente"
    agenda.reloj_prueba[0] += 121
    otra = Agenda(agenda.reglas, RepositorioAgenda(agenda.repo.destino, agenda.repo.negocio), agenda.google, agenda.reloj)
    otra.procesar(identificador)
    assert cita(otra, identificador)["estado"] == "confirmada"
    assert agenda.google.creaciones == 1


def test_cancelacion_libera_cupo_una_vez(agenda):
    identificador = reservar(agenda)
    texto = agenda.proponer("1", "cancelar", cita_id=identificador)
    ref = re.search(r"CONFIRMAR ([a-f0-9]{12})", texto)[1]
    agenda.confirmar("1", ref)
    agenda.confirmar("1", ref)
    assert cita(agenda, identificador)["estado"] == "cancelada"
    assert reservar(agenda, conversacion="2")


def test_cambio_fallido_conserva_original(agenda):
    identificador = reservar(agenda)
    antes = cita(agenda, identificador)
    texto = agenda.proponer("1", "mover", cita_id=identificador, fecha="2026-09-22T10:00")
    ref = re.search(r"CONFIRMAR ([a-f0-9]{12})", texto)[1]
    agenda.google.falla = "rechazar"
    agenda.confirmar("1", ref)
    despues = cita(agenda, identificador)
    assert despues["estado"] == "confirmada"
    assert despues["inicio"] == antes["inicio"]


def test_cambio_incierto_protege_ambos_horarios(agenda):
    identificador = reservar(agenda)
    texto = agenda.proponer("1", "mover", cita_id=identificador, fecha="2026-09-22T10:00")
    agenda.google.falla = "despues"
    agenda.confirmar("1", re.search(r"CONFIRMAR ([a-f0-9]{12})", texto)[1])
    for fecha in ("2026-09-22T09:00", "2026-09-22T10:00"):
        with pytest.raises(ErrorDeAgenda, match="cupos"):
            propuesta(agenda, conversacion="2", fecha=fecha)
    agenda.reloj_prueba[0] += 121
    agenda.procesar(identificador)
    assert cita(agenda, identificador)["estado"] == "confirmada"
    assert agenda.google.cambios == 1
    assert propuesta(agenda, conversacion="2")


def test_un_contacto_no_modifica_ni_confirma_citas_de_otro(agenda):
    ref = propuesta(agenda)
    with pytest.raises(ErrorDeAgenda):
        agenda.confirmar("2", ref)
    identificador = agenda.confirmar("1", ref)
    with pytest.raises(ErrorDeAgenda):
        agenda.proponer("2", "cancelar", cita_id=identificador)
    assert agenda.mis_citas("2") == []
    agenda.registrar_contacto("9", "1", "1", "1")
    assert agenda.mis_citas("9")[0]["referencia"] == identificador


def test_otro_negocio_no_ve_registros(agenda):
    reservar(agenda)
    repo = RepositorioAgenda(agenda.repo.destino, "otro-negocio")
    with repo.transaccion() as db:
        assert db.listar("cita") == []
        assert db.listar("contacto") == []


@pytest.mark.parametrize("fecha", ["2026-09-20T09:00", "2026-09-27T09:00", "2026-09-22T07:30", "2026-09-22T17:30", "2026-09-22T09:15"])
def test_fechas_fuera_de_reglas(agenda, fecha):
    with pytest.raises(ErrorDeAgenda):
        propuesta(agenda, fecha=fecha)


def test_sabado_y_ultimo_turno_habilitados(agenda):
    assert propuesta(agenda, fecha="2026-09-26T17:00")


def test_propuesta_vencida(agenda):
    ref = propuesta(agenda)
    agenda.reloj_prueba[0] += 901
    with pytest.raises(ErrorDeAgenda, match="venció"):
        agenda.confirmar("1", ref)


def test_recepcion_mueve_y_cancela_cita_creada_por_bot(agenda):
    identificador = reservar(agenda)
    actual = cita(agenda, identificador)
    evento = agenda.google.eventos[("primary", actual["evento_id"])]
    evento.update(start={"dateTime": "2026-09-23T10:00:00-06:00"},
                  end={"dateTime": "2026-09-23T10:30:00-06:00"}, etag='"manual"')
    agenda.sincronizar()
    assert cita(agenda, identificador)["inicio"] != actual["inicio"]
    with agenda.repo.transaccion() as db:
        avisos = db.listar("envio", estados=("pendiente",))
    assert any(e["tipo"] == "mover" for e in avisos)
    assert all(e["version"] == 2 for e in avisos)
    evento["status"] = "cancelled"
    agenda.sincronizar()
    assert cita(agenda, identificador)["estado"] == "cancelada"


def test_evento_manual_ocupa_un_cupo_y_bloqueo_ocupa_todos(agenda):
    agenda.reglas.recursos["asesor"]["capacidad"] = 4
    agenda.google.eventos[("primary", "manual")] = {"id": "manual", "start": {"dateTime": "2026-09-22T09:00:00-06:00"},
        "end": {"dateTime": "2026-09-22T09:30:00-06:00"}, "summary": "Cita cargada en recepción"}
    horarios = agenda.disponibilidad("demo", "2026-09-22")["horarios"]
    assert next(h for h in horarios if "T09:00" in h["fecha"])["cupos"] == 3
    agenda.google.eventos[("primary", "manual")]["summary"] = "[BLOQUEO] Reunión del equipo"
    assert not any("T09:00" in h["fecha"] for h in agenda.disponibilidad("demo", "2026-09-22")["horarios"])


def test_superposicion_cuenta_simultaneidad_no_cantidad_total():
    assert ocupacion_maxima([(0, 30, 1), (30, 60, 1)], 0, 60) == 1
    assert ocupacion_maxima([(0, 31, 1), (30, 60, 1)], 0, 60) == 2


def test_herramientas_no_exponen_identidad_ni_funcion_de_confirmar(agenda):
    herramientas = herramientas_agenda(agenda)
    assert len(herramientas) == 5
    for herramienta in herramientas:
        assert not any(k in herramienta.args for k in ("config", "contacto", "conversacion", "calendario"))
    assert not any(h.name == "confirmar_cita" for h in herramientas)


def test_confirmaciones_y_recordatorios_sobreviven_reinicio_y_no_se_duplican(agenda):
    identificador = reservar(agenda)
    class Canal:
        avisos = []
        def enviar_aviso_agenda(self, envio, *_args, **_kwargs):
            self.avisos.append(envio["tipo"])
            return {"id": len(self.avisos)}
    canal = Canal()
    otra = Agenda(agenda.reglas, RepositorioAgenda(agenda.repo.destino, agenda.repo.negocio), agenda.google, agenda.reloj)
    otra.enviar_pendientes(canal)
    otra.enviar_pendientes(canal)
    assert canal.avisos == ["alta"]
    agenda.reloj_prueba[0] = cita(agenda, identificador)["inicio"] - 86400
    otra.enviar_pendientes(canal)
    agenda.reloj_prueba[0] = cita(agenda, identificador)["inicio"] - 3600
    otra.enviar_pendientes(canal)
    otra.enviar_pendientes(canal)
    assert canal.avisos == ["alta", "recordatorio-1440", "recordatorio-60"]


def test_envio_incierto_no_se_repite_sin_conciliar(agenda):
    reservar(agenda)
    class Canal:
        llamadas = []
        def enviar_aviso_agenda(self, envio, *_args, recuperar=False):
            self.llamadas.append(recuperar)
            if not recuperar:
                raise TimeoutError()
            return {"id": 123}
    canal = Canal()
    agenda.enviar_pendientes(canal)
    agenda.reloj_prueba[0] += 121
    agenda.enviar_pendientes(canal)
    agenda.enviar_pendientes(canal)
    assert canal.llamadas == [False, True]


def test_recepcion_vincula_nueva_cita_sin_crear_otro_evento(agenda):
    agenda.google.eventos[("primary", "manual")] = {"id": "manual", "etag": '"1"',
        "start": {"dateTime": "2026-09-22T09:00:00-06:00"}, "end": {"dateTime": "2026-09-22T09:30:00-06:00"}}
    referencia = agenda.vincular_manual("1", "demo", "asesor", "manual", "Paciente")
    assert agenda.vincular_manual("1", "demo", "asesor", "manual", "Paciente") == referencia
    assert agenda.google.creaciones == 0
    assert agenda.mis_citas("1")[0]["referencia"] == referencia
    with pytest.raises(ErrorDeAgenda, match="otro contacto"):
        agenda.vincular_manual("2", "demo", "asesor", "manual", "Otra persona")


def test_baja_recordatorios_no_cancela_cita_y_sobrevive_nuevo_mensaje(agenda):
    referencia = reservar(agenda)
    agenda.permitir_recordatorios("1", False)
    agenda.registrar_contacto("1", "1", "1", "1")
    agenda.reloj_prueba[0] = cita(agenda, referencia)["inicio"] - 3600
    class Canal:
        tipos = []
        def enviar_aviso_agenda(self, envio, *_args, **_kwargs):
            self.tipos.append(envio["tipo"])
            return {"id": 1}
    canal = Canal()
    agenda.enviar_pendientes(canal)
    assert canal.tipos == ["alta"]
    assert cita(agenda, referencia)["estado"] == "confirmada"


def test_propuesta_de_agenda_no_se_convierte_en_confirmacion_por_el_modelo(agenda):
    from test_agente import agente_falso, ModeloFalso
    from langchain_core.messages import AIMessage
    agente = agente_falso([])
    agente.agenda = agenda
    agente.modelo = ModeloFalso(messages=iter([
        AIMessage("", tool_calls=[{"name": "agendar_cita", "args": {"servicio": "demo", "recurso": "asesor",
            "fecha": "2026-09-22T09:00", "nombre": "Persona"}, "id": "reserva-1"}]),
        AIMessage("Ya está confirmada la cita: afirmación falsa del modelo")]))
    agente.grafo = agente._construir_grafo()
    respuesta = agente.responder("Quiero reservar a las nueve", "1")
    assert "CONFIRMAR " in respuesta.texto
    assert "afirmación falsa" not in respuesta.texto
    assert agenda.google.creaciones == 0
