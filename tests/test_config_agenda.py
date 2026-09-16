"""Un archivo de conexión por negocio.

Antes el token se guardaba siempre en `.env.agenda.local`: conectar la cuenta
de Google de un segundo cliente le borraba el token al primero, y el bot de
ese cliente dejaba de agendar sin aviso.
"""

import sys

import pytest

sys.path.insert(0, "src")

from agente import config as cfg  # noqa: E402
from agente.config import (ErrorDeConfiguracion, _archivo_agenda,
                           guardar_conexion_agenda, variables_agenda_locales)


@pytest.fixture
def raiz(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "RAIZ", tmp_path)
    return tmp_path


def test_sin_negocio_conserva_el_archivo_de_siempre(raiz):
    assert _archivo_agenda().name == ".env.agenda.local"


def test_cada_negocio_tiene_su_archivo(raiz):
    assert _archivo_agenda("clinica-ejemplo").name == ".env.agenda.clinica-ejemplo.local"


@pytest.mark.parametrize("negocio", [
    "../otro", "con/barra", "MAYUSCULAS", "con espacio", "a", "x" * 51, "acento-ñ", "punto.punto",
])
def test_rechaza_un_negocio_que_arme_otra_ruta(raiz, negocio):
    with pytest.raises(ErrorDeConfiguracion):
        _archivo_agenda(negocio)


def test_el_archivo_queda_dentro_de_la_raiz(raiz):
    assert _archivo_agenda("clinica-ejemplo").parent == raiz


def test_conectar_un_negocio_no_le_pisa_el_token_a_otro(raiz):
    guardar_conexion_agenda({"AGENDA_GOOGLE_REFRESH_TOKEN": "token-de-smarth"}, "smarth-house")
    guardar_conexion_agenda({"AGENDA_GOOGLE_REFRESH_TOKEN": "token-de-clinica"}, "clinica-ejemplo")

    assert variables_agenda_locales("smarth-house")["AGENDA_GOOGLE_REFRESH_TOKEN"] == "token-de-smarth"
    assert variables_agenda_locales("clinica-ejemplo")["AGENDA_GOOGLE_REFRESH_TOKEN"] == "token-de-clinica"


def test_el_archivo_por_defecto_es_independiente_de_los_demas(raiz):
    guardar_conexion_agenda({"AGENDA_GOOGLE_REFRESH_TOKEN": "token-por-defecto"})
    guardar_conexion_agenda({"AGENDA_GOOGLE_REFRESH_TOKEN": "token-de-clinica"}, "clinica-ejemplo")

    assert variables_agenda_locales()["AGENDA_GOOGLE_REFRESH_TOKEN"] == "token-por-defecto"


def test_sigue_rechazando_una_variable_que_no_sea_de_conexion(raiz):
    with pytest.raises(ErrorDeConfiguracion):
        guardar_conexion_agenda({"AGENDA_DSN": "postgresql://algo"}, "clinica-ejemplo")


def test_un_negocio_sin_conectar_no_devuelve_datos_de_otro(raiz):
    guardar_conexion_agenda({"AGENDA_GOOGLE_REFRESH_TOKEN": "token-de-smarth"}, "smarth-house")
    assert variables_agenda_locales("clinica-ejemplo") == {}
