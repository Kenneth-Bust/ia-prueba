"""El portal de punta a punta con el repositorio en memoria: sin base ni red."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from portal.almacen import MAXIMO_FOTO, Almacen  # noqa: E402
from portal.app import COOKIE, crear_app  # noqa: E402
from portal.config import ConfigPortal  # noqa: E402
from portal.repositorio import RepositorioEnMemoria  # noqa: E402
from portal.seguridad import hashear_clave, huella  # noqa: E402

CLAVE = "clave-de-prueba-1"
CABECERA = {"X-Portal": "1"}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100
CLAVE_BOT = "clave-del-bot-de-prueba"


class Reloj:
    def __init__(self) -> None:
        self.ahora = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.ahora


def armar(tmp_path, hosts=()) -> SimpleNamespace:
    repo = RepositorioEnMemoria()
    repo.crear_cliente("smarth-house", "Smarth House")
    repo.crear_cliente("uniformes", "Uniformes Demo")
    usuarios = {}
    for correo, negocio, rol in (
        ("dueno@ejemplo.com", "smarth-house", "administrador"),
        ("empleado@ejemplo.com", "smarth-house", "empleado"),
        ("ajeno@ejemplo.com", "uniformes", "administrador"),
    ):
        usuarios[correo] = repo.crear_usuario(correo, correo.split("@")[0].title(), hashear_clave(CLAVE))
        repo.dar_acceso(usuarios[correo], negocio, rol)
    repo.crear_clave_bot(huella(CLAVE_BOT), "smarth-house", "agente-ia")

    reloj = Reloj()
    config = ConfigPortal(dsn="sin-base", carpeta_archivos=tmp_path, cookie_segura=False, hosts_permitidos=hosts)
    app = crear_app(repo, Almacen(tmp_path), config, reloj=reloj)
    return SimpleNamespace(repo=repo, app=app, reloj=reloj, usuarios=usuarios)


@pytest.fixture
def portal(tmp_path) -> SimpleNamespace:
    return armar(tmp_path)


def entrar(portal, correo="dueno@ejemplo.com", clave=CLAVE) -> TestClient:
    cliente = TestClient(portal.app)
    respuesta = cliente.post("/api/entrar", json={"correo": correo, "clave": clave}, headers=CABECERA)
    assert respuesta.status_code == 200, respuesta.text
    return cliente


def promocion(**cambios) -> dict:
    return {
        "tipo": "promocion", "sku": "PLAN-45", "nombre": "Plan mensual", "precio": "45",
        "unidad": "al mes", "vigente_hasta": "2026-10-11", "cotizacion_automatica": False,
        "activo": True,
    } | cambios


def crear_con_foto(cliente: TestClient, **cambios) -> tuple[dict, str]:
    item = cliente.post("/api/items", json=promocion(**cambios), headers=CABECERA)
    assert item.status_code == 201, item.text
    foto = cliente.post(
        f"/api/items/{item.json()['id']}/fotos", content=PNG,
        headers=CABECERA | {"Content-Type": "image/png"},
    )
    assert foto.status_code == 201, foto.text
    return item.json(), foto.json()["id"]


def bot(portal, clave=CLAVE_BOT) -> TestClient:
    return TestClient(portal.app, headers={"Authorization": f"Bearer {clave}"})


# -- Sesión ---------------------------------------------------------------------------


def test_entrar_deja_una_cookie_protegida_y_guarda_solo_la_huella(portal):
    cliente = TestClient(portal.app)

    respuesta = cliente.post(
        "/api/entrar", json={"correo": " Dueno@Ejemplo.com ", "clave": CLAVE}, headers=CABECERA
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["negocio"] == {"id": "smarth-house", "nombre": "Smarth House"}
    assert respuesta.json()["rol"] == "administrador"
    cookie = respuesta.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    token = cliente.cookies[COOKIE]
    assert huella(token) in portal.repo._sesiones and token not in portal.repo._sesiones


def test_contrasena_equivocada_y_correo_inexistente_dan_el_mismo_mensaje(portal):
    cliente = TestClient(portal.app)

    mala = cliente.post("/api/entrar", json={"correo": "dueno@ejemplo.com", "clave": "otra-clave-larga"}, headers=CABECERA)
    nadie = cliente.post("/api/entrar", json={"correo": "nadie@ejemplo.com", "clave": CLAVE}, headers=CABECERA)

    assert mala.status_code == nadie.status_code == 401
    assert mala.json() == nadie.json()


def test_cinco_fallos_bloquean_ese_correo_aunque_despues_acierte(portal):
    cliente = TestClient(portal.app)
    for _ in range(5):
        cliente.post("/api/entrar", json={"correo": "dueno@ejemplo.com", "clave": "equivocada-123"}, headers=CABECERA)

    respuesta = cliente.post("/api/entrar", json={"correo": "dueno@ejemplo.com", "clave": CLAVE}, headers=CABECERA)

    assert respuesta.status_code == 429


def test_sin_la_cabecera_propia_no_se_cambia_nada(portal):
    """Un formulario de otra página no puede mandar X-Portal."""
    cliente = entrar(portal)

    assert cliente.post("/api/items", json=promocion()).status_code == 403
    assert TestClient(portal.app).post("/api/entrar", json={"correo": "dueno@ejemplo.com", "clave": CLAVE}).status_code == 403
    assert portal.repo.items("smarth-house") == []


def test_sin_sesion_no_hay_datos_y_la_sesion_vence(portal):
    assert TestClient(portal.app).get("/api/items").status_code == 401

    cliente = entrar(portal)
    assert cliente.get("/api/sesion").status_code == 200
    portal.reloj.ahora += timedelta(hours=13)
    respuesta = cliente.get("/api/sesion")
    assert respuesta.status_code == 401 and "venció" in respuesta.json()["error"]


def test_salir_invalida_el_token_aunque_alguien_lo_haya_copiado(portal):
    cliente = entrar(portal)
    token = cliente.cookies[COOKIE]

    cliente.post("/api/salir", headers=CABECERA)

    copia = TestClient(portal.app, cookies={COOKIE: token})
    assert copia.get("/api/sesion").status_code == 401


def test_cambiar_de_negocio_solo_con_acceso(portal):
    cliente = entrar(portal)
    assert cliente.post("/api/sesion/negocio", json={"negocio": "uniformes"}, headers=CABECERA).status_code == 404

    portal.repo.dar_acceso(portal.usuarios["dueno@ejemplo.com"], "uniformes", "empleado")
    respuesta = cliente.post("/api/sesion/negocio", json={"negocio": "uniformes"}, headers=CABECERA)

    assert respuesta.status_code == 200
    assert respuesta.json()["negocio"]["id"] == "uniformes" and respuesta.json()["rol"] == "empleado"
    assert cliente.get("/api/items").status_code == 403


# -- Roles y separación entre negocios ------------------------------------------------


def test_el_empleado_solo_consulta_lo_publicado(portal):
    dueno = entrar(portal)
    crear_con_foto(dueno)
    dueno.post("/api/publicar", headers=CABECERA)
    empleado = entrar(portal, "empleado@ejemplo.com")

    assert empleado.put("/api/perfil", json={}, headers=CABECERA).status_code == 403
    assert empleado.get("/api/items").status_code == 403
    assert empleado.post("/api/publicar", headers=CABECERA).status_code == 403
    publicado = empleado.get("/api/publicado").json()["publicacion"]
    assert publicado["contenido"]["items"][0]["sku"] == "PLAN-45"


def test_un_negocio_no_ve_ni_toca_lo_de_otro(portal):
    item, foto_id = crear_con_foto(entrar(portal))
    ajeno = entrar(portal, "ajeno@ejemplo.com")

    assert ajeno.get("/api/items").json() == []
    assert ajeno.put(f"/api/items/{item['id']}", json=promocion(precio="1"), headers=CABECERA).status_code == 404
    assert ajeno.delete(f"/api/items/{item['id']}", headers=CABECERA).status_code == 404
    assert ajeno.get(f"/api/fotos/{foto_id}").status_code == 404
    assert ajeno.delete(f"/api/items/{item['id']}/fotos/{foto_id}", headers=CABECERA).status_code == 404
    subida = ajeno.post(f"/api/items/{item['id']}/fotos", content=PNG, headers=CABECERA | {"Content-Type": "image/png"})
    assert subida.status_code == 404
    assert portal.repo.item("smarth-house", item["id"])["precio"] == "45.00"


# -- Cargar, publicar y lo que ve el bot ------------------------------------------------


def test_cargar_publicar_y_leer_desde_el_bot(portal):
    cliente = entrar(portal)
    item, foto_id = crear_con_foto(cliente)
    perfil = cliente.put(
        "/api/perfil", json={"direccion": "Managua", "formas_de_pago": ["transferencia"]}, headers=CABECERA
    )
    assert perfil.status_code == 200
    assert bot(portal).get("/api/bot/catalogo").status_code == 404  # todavía no publicó

    assert cliente.get("/api/estado").json()["cambios_sin_publicar"] is True
    assert cliente.post("/api/publicar", headers=CABECERA).json() == {"sin_cambios": False, "version": 1}
    assert cliente.get("/api/estado").json()["cambios_sin_publicar"] is False
    assert cliente.post("/api/publicar", headers=CABECERA).json() == {"sin_cambios": True, "version": 1}

    respuesta = bot(portal).get("/api/bot/catalogo")
    assert respuesta.status_code == 200
    contenido = respuesta.json()["contenido"]
    assert contenido["negocio"]["id"] == "smarth-house"
    assert contenido["perfil"]["formas_de_pago"] == ["Transferencia bancaria"]
    assert contenido["items"][0]["precio"] == "45.00"
    assert contenido["items"][0]["moneda"] == "USD"
    assert contenido["items"][0]["fotos"][0]["id"] == foto_id

    etiqueta = respuesta.headers["etag"]
    assert bot(portal).get("/api/bot/catalogo", headers={"If-None-Match": etiqueta}).status_code == 304
    foto = bot(portal).get(f"/api/bot/fotos/{foto_id}")
    assert foto.content == PNG and foto.headers["content-type"] == "image/png"


def test_el_bot_necesita_su_clave_y_solo_ve_su_negocio(portal):
    _, foto_id = crear_con_foto(entrar(portal))
    portal.repo.crear_clave_bot(huella("clave-de-uniformes"), "uniformes", "bot-demo")

    assert TestClient(portal.app).get("/api/bot/catalogo").status_code == 401
    assert bot(portal, "inventada").get("/api/bot/catalogo").status_code == 401
    assert bot(portal, "clave-de-uniformes").get(f"/api/bot/fotos/{foto_id}").status_code == 404

    portal.repo.revocar_claves_bot("smarth-house")
    assert bot(portal).get(f"/api/bot/fotos/{foto_id}").status_code == 401


def test_el_bot_sigue_con_lo_publicado_hasta_que_se_publica_de_nuevo(portal):
    cliente = entrar(portal)
    item, foto_id = crear_con_foto(cliente)
    cliente.post("/api/publicar", headers=CABECERA)

    cliente.put(f"/api/items/{item['id']}", json=promocion(precio="50"), headers=CABECERA)
    cliente.delete(f"/api/items/{item['id']}/fotos/{foto_id}", headers=CABECERA)
    assert bot(portal).get("/api/bot/catalogo").json()["contenido"]["items"][0]["precio"] == "45.00"
    assert bot(portal).get(f"/api/bot/fotos/{foto_id}").status_code == 200

    assert cliente.post("/api/publicar", headers=CABECERA).json()["version"] == 2
    publicado = bot(portal).get("/api/bot/catalogo").json()["contenido"]["items"][0]
    assert publicado["precio"] == "50.00" and publicado["fotos"] == []


def test_el_codigo_no_se_repite_ni_cambia_al_editar(portal):
    cliente = entrar(portal)
    item = cliente.post("/api/items", json=promocion(), headers=CABECERA).json()

    repetido = cliente.post("/api/items", json=promocion(), headers=CABECERA)
    editado = cliente.put(f"/api/items/{item['id']}", json=promocion(sku="OTRO"), headers=CABECERA)

    assert repetido.status_code == 422 and "Ya hay" in repetido.json()["error"]
    assert editado.json()["sku"] == "PLAN-45"


# -- Validaciones y cabeceras ---------------------------------------------------------------


def test_las_fotos_se_validan_al_subir(portal):
    cliente = entrar(portal)
    item = cliente.post("/api/items", json=promocion(), headers=CABECERA).json()
    url = f"/api/items/{item['id']}/fotos"

    gif = cliente.post(url, content=b"GIF89a" + b"0" * 50, headers=CABECERA)
    grande = cliente.post(url, content=PNG + b"0" * MAXIMO_FOTO, headers=CABECERA)
    assert gif.status_code == 422 and "JPG o PNG" in gif.json()["error"]
    assert grande.status_code == 413

    for _ in range(5):
        assert cliente.post(url, content=PNG, headers=CABECERA).status_code == 201
    sexta = cliente.post(url, content=PNG, headers=CABECERA)
    assert sexta.status_code == 422 and "hasta 5 fotos" in sexta.json()["error"]


def test_los_errores_llegan_con_un_mensaje_para_la_persona(portal):
    cliente = entrar(portal)

    precio = cliente.post("/api/items", json=promocion(precio="abc"), headers=CABECERA)
    lista = cliente.post("/api/items", json=[1, 2], headers=CABECERA)
    cuenta = cliente.put("/api/perfil", json={"nota_pagos": "BAC 123456789"}, headers=CABECERA)

    assert precio.status_code == 422 and "precio" in precio.json()["error"]
    assert lista.status_code == 422 and "formato" in lista.json()["error"]
    assert cuenta.status_code == 422 and "números de cuenta" in cuenta.json()["error"]


def test_cabeceras_de_seguridad(portal):
    cliente = TestClient(portal.app)

    pagina = cliente.get("/")
    api = cliente.get("/api/sesion")

    assert "script-src 'self'" in pagina.headers["content-security-policy"]
    assert pagina.headers["x-frame-options"] == "DENY"
    assert api.headers["cache-control"] == "no-store"
    assert cliente.get("/estaticos/../app.py").status_code == 404
    assert cliente.get("/favicon.ico").status_code == 204


def test_solo_responde_a_las_direcciones_permitidas(tmp_path):
    portal = armar(tmp_path, hosts=("127.0.0.1:8010",))

    ajeno = TestClient(portal.app, base_url="http://rebinding.example")
    propio = TestClient(portal.app, base_url="http://127.0.0.1:8010")

    assert ajeno.get("/").status_code == 400
    assert ajeno.get("/salud").status_code == 200  # el chequeo de Coolify
    assert propio.get("/").status_code == 200


def test_la_actividad_queda_registrada(portal):
    cliente = entrar(portal)
    crear_con_foto(cliente)
    cliente.post("/api/publicar", headers=CABECERA)

    acciones = [fila["accion"] for fila in cliente.get("/api/actividad").json()]

    assert acciones[:4] == ["publicar", "subir_foto", "crear_item", "entrar"]
