"""El mínimo incluye la ráfaga y la IA, sin dormir 15 segundos en cada test."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from test_agente import agente_falso
from test_chatwoot import ChatwootFalso, cliente, evento

from agente.config import Config, ErrorDeConfiguracion
from agente.web import webhook


@pytest.mark.parametrize("valor,esperado", [(None, 15), ("", 15), ("0", 0), ("25", 25)])
def test_configura_el_minimo_sin_depender_del_buffer(monkeypatch, valor, esperado):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "clave-falsa")
    monkeypatch.setenv("BUFFER_SEGUNDOS", "5")
    if valor is None:
        monkeypatch.delenv("RESPUESTA_MINIMA_SEGUNDOS", raising=False)
    else:
        monkeypatch.setenv("RESPUESTA_MINIMA_SEGUNDOS", valor)
    config = Config.desde_entorno("claude")
    assert config.respuesta_minima_segundos == esperado
    assert config.buffer_segundos == 5


@pytest.mark.parametrize("valor", ["-1", "quince", "1.5"])
def test_rechaza_un_minimo_invalido(monkeypatch, valor):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "clave-falsa")
    monkeypatch.setenv("RESPUESTA_MINIMA_SEGUNDOS", valor)
    with pytest.raises(ErrorDeConfiguracion, match="RESPUESTA_MINIMA_SEGUNDOS"):
        Config.desde_entorno("claude")


@pytest.mark.parametrize("ahora,esperado", [(109, 6), (115, 0), (121, 0)])
def test_espera_solo_lo_que_falta_o_nada_si_la_ia_tardo_mas(monkeypatch, ahora, esperado):
    dormir = AsyncMock()
    reloj = iter([ahora, 115])
    monkeypatch.setattr(webhook, "monotonic", lambda: next(reloj))
    monkeypatch.setattr(webhook.asyncio, "sleep", dormir)
    asyncio.run(webhook._esperar_hasta(115))
    if esperado:
        dormir.assert_awaited_once_with(esperado)
    else:
        dormir.assert_not_awaited()


def test_revalida_el_minimo_si_el_temporizador_despierta_antes(monkeypatch):
    from unittest.mock import call

    dormir = AsyncMock()
    reloj = iter([109, 114, 115])
    monkeypatch.setattr(webhook, "monotonic", lambda: next(reloj))
    monkeypatch.setattr(webhook.asyncio, "sleep", dormir)
    asyncio.run(webhook._esperar_hasta(115))
    assert dormir.await_args_list == [call(6), call(1)]


@pytest.fixture
def reloj(monkeypatch):
    """Controla el tiempo y la liberación de ráfagas sin tocar la red."""
    estado = SimpleNamespace(ahora=100, plazos=[], pausas=[], buffer=None)
    monkeypatch.setattr(webhook, "monotonic", lambda: estado.ahora)

    async def esperar(instante):
        estado.plazos.append(instante)
        estado.pausas.append(max(0, instante - estado.ahora))
        estado.ahora = max(estado.ahora, instante)

    monkeypatch.setattr(webhook, "_esperar_hasta", esperar)

    class BufferManual:
        def __init__(self, segundos, al_completar):
            self.al_completar = al_completar
            self.pendientes = {}
            estado.buffer = self

        async def agregar(self, conversacion, texto, adjuntos=None):
            self.pendientes.setdefault(conversacion, []).append((texto, adjuntos or []))

        async def soltar(self, conversacion):
            partes = self.pendientes.pop(conversacion)
            await self.al_completar(
                conversacion,
                "\n".join(texto for texto, _ in partes),
                [adjunto for _, adjuntos in partes for adjunto in adjuntos],
            )

        async def vaciar(self):
            for conversacion in list(self.pendientes):
                await self.soltar(conversacion)

    monkeypatch.setattr(webhook, "BufferDeMensajes", BufferManual)
    return estado


def test_cuenta_desde_el_ultimo_mensaje_y_confirma_el_webhook_antes(reloj):
    canal = ChatwootFalso()
    with cliente(canal, agente_falso(["respuesta"]), respuesta_minima_segundos=15) as web:
        assert web.post("/chatwoot/secreto", json=evento("hola")).json() == {"estado": "recibido"}
        reloj.ahora = 104
        web.post("/chatwoot/secreto", json=evento("precio", id_mensaje=2))
        assert canal.envios() == []
        assert reloj.plazos == []

        # Cinco segundos de buffer y cuatro de IA ya cuentan dentro de los 15.
        reloj.ahora = 113
        web.portal.call(reloj.buffer.soltar, "12")
        assert reloj.plazos == [119]
        assert reloj.pausas == [6]
        assert canal.envios() == ["respuesta"]


def test_las_conversaciones_tienen_relojes_independientes(reloj):
    canal = ChatwootFalso()
    with cliente(canal, agente_falso(["uno", "dos"]), respuesta_minima_segundos=15) as web:
        web.post("/chatwoot/secreto", json=evento(conversacion=11))
        reloj.ahora = 103
        web.post("/chatwoot/secreto", json=evento(conversacion=22, id_mensaje=2))
        reloj.ahora = 110
        web.portal.call(reloj.buffer.soltar, "11")
        web.portal.call(reloj.buffer.soltar, "22")
        assert reloj.plazos == [115, 118]
        assert canal.envios() == ["uno", "dos"]


def test_el_modelo_lento_no_recibe_otros_quince_segundos(reloj):
    canal = ChatwootFalso()
    with cliente(canal, agente_falso(["respuesta"]), respuesta_minima_segundos=15) as web:
        web.post("/chatwoot/secreto", json=evento())
        reloj.ahora = 124
        web.portal.call(reloj.buffer.soltar, "12")
        assert reloj.pausas == [0]
        assert reloj.ahora == 124


def test_no_hay_minimo_extra_cuando_se_desactiva(reloj):
    with cliente(ChatwootFalso(), agente_falso(["respuesta"]), respuesta_minima_segundos=0) as web:
        web.post("/chatwoot/secreto", json=evento())
        reloj.ahora = 105
        web.portal.call(reloj.buffer.soltar, "12")
        assert reloj.pausas == [0]


def test_al_apagar_se_vacia_sin_demora_artificial(reloj):
    canal = ChatwootFalso()
    with cliente(canal, agente_falso(["respuesta"]), respuesta_minima_segundos=15) as web:
        web.post("/chatwoot/secreto", json=evento())
        assert canal.envios() == []
    assert reloj.plazos == []
    assert canal.envios() == ["respuesta"]


def test_los_ignorados_no_reinician_el_reloj(reloj):
    with cliente(ChatwootFalso(), agente_falso(["respuesta"]), respuesta_minima_segundos=15) as web:
        web.post("/chatwoot/secreto", json=evento())
        reloj.ahora = 104
        respuesta = web.post("/chatwoot/secreto", json=evento(tipo="outgoing", id_mensaje=2))
        assert respuesta.json()["estado"] == "ignorado"
        web.portal.call(reloj.buffer.soltar, "12")
        assert reloj.plazos == [115]


def test_salud_publica_los_tiempos_efectivos():
    with cliente(ChatwootFalso(), agente_falso([]), buffer_segundos=5, respuesta_minima_segundos=15) as web:
        salud = web.get("/salud").json()
    assert salud["respuesta_minima_segundos"] == 15
    assert salud["buffer_segundos"] == 5


def test_espera_real_con_buffer_real_sin_frenar_la_recepcion():
    """Comprueba el ensamblaje con tiempos cortos, sin modelo ni canal remotos."""
    import threading
    from time import monotonic

    httpx = pytest.importorskip("httpx")
    canal = ChatwootFalso()
    enviado = threading.Event()
    instantes = []

    def enviar(conversacion, mensajes):
        instantes.append(monotonic())
        enviado.set()

    canal.enviar = enviar
    agente = agente_falso(["respuesta"])
    agente.config.chatwoot_webhook_token = "secreto"
    agente.config.buffer_segundos = 0.01
    agente.config.respuesta_minima_segundos = 0.12
    app = webhook.crear_app(agente.config, agente=agente, canal=canal)

    async def correr():
        transporte = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transporte, base_url="http://prueba") as web:
            inicio = monotonic()
            respuesta = await web.post("/chatwoot/secreto", json=evento())
            assert respuesta.json()["estado"] == "recibido"
            assert not enviado.is_set(), "el acuse debe salir antes de esperar y enviar"
            assert (await web.get("/salud")).status_code == 200
            assert await asyncio.to_thread(enviado.wait, 2)
            assert instantes[0] - inicio >= 0.12

    asyncio.run(correr())
