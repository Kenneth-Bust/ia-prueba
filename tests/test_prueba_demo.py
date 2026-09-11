"""El simulador no debe mandar mensajes a la agencia ni a WhatsApp."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.probar_bandeja_demo import ejecutar


def datos_de_prueba():
    return {"CHATWOOT_URL": "https://cw.test", "CHATWOOT_TOKEN": "falso", "CHATWOOT_CUENTA_ID": "2", "CHATWOOT_BANDEJA_ID": "6"}


def api_falsa(llamadas, tipo_usuario="User", tipo_bandeja="Channel::Api"):
    def consultar(metodo, camino, datos=None):
        llamadas.append((metodo, camino, datos))
        if camino.endswith("/profile"):
            return {"type": tipo_usuario, "accounts": [{"id": 2, "name": "Cliente Demo"}]}
        if camino.endswith("/inboxes"):
            return {"payload": [{"id": 6, "name": "Pruebas Demo", "channel_type": tipo_bandeja}]}
        if camino.endswith("/contacts"):
            return {"payload": {"contact": {"id": 9, "contact_inboxes": [{"source_id": "sintetico", "inbox": {"id": 6}}]}}}
        if camino.endswith("/conversations"):
            return {"id": 12}
        return {"payload": [{"message_type": 1, "content": "Respuesta ficticia"}]}
    return consultar


@pytest.mark.parametrize("cambio", [{"CHATWOOT_CUENTA_ID": "1"}, {"CHATWOOT_TOKEN": ""}, {"CHATWOOT_BANDEJA_ID": ""}])
def test_configuracion_incompleta_o_de_agencia_no_hace_pedidos(cambio):
    valores = datos_de_prueba()
    valores.update(cambio)
    llamadas = []
    with pytest.raises(ValueError):
        ejecutar(valores, api_falsa(llamadas))
    assert llamadas == []


@pytest.mark.parametrize("usuario,bandeja", [("SuperAdmin", "Channel::Api"), ("User", "Channel::Whatsapp")])
def test_destino_no_autorizado_no_crea_ni_envia(usuario, bandeja):
    llamadas = []
    with pytest.raises(ValueError):
        ejecutar(datos_de_prueba(), api_falsa(llamadas, usuario, bandeja))
    assert all(metodo == "GET" for metodo, _, _ in llamadas)


def test_la_prueba_envia_solo_un_mensaje_sin_telefono_ni_correo():
    llamadas = []
    assert ejecutar(datos_de_prueba(), api_falsa(llamadas)) == 12
    envios = [datos for metodo, camino, datos in llamadas if metodo == "POST" and camino.endswith("/messages")]
    assert len(envios) == 1
    assert envios[0]["message_type"] == "incoming"
    contacto = next(datos for _, camino, datos in llamadas if camino.endswith("/contacts"))
    assert "phone_number" not in contacto and "email" not in contacto
