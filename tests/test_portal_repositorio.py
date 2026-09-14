"""El contrato del repositorio: memoria y PostgreSQL tienen que dar lo mismo.

Contra PostgreSQL corre solo si está PORTAL_PRUEBAS_DSN, y únicamente con la
base `catalogos_pruebas`. Cada prueba crea negocios con nombre al azar y los
borra al terminar; nunca toca otros datos.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from portal.modelo import validar_ajustes, validar_item, validar_perfil  # noqa: E402
from portal.repositorio import RepositorioEnMemoria, YaExiste  # noqa: E402

DSN = os.getenv("PORTAL_PRUEBAS_DSN", "")
AHORA = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)


def _postgres():
    from psycopg.conninfo import conninfo_to_dict

    if conninfo_to_dict(DSN).get("dbname") != "catalogos_pruebas":
        pytest.skip("Las pruebas contra PostgreSQL solo usan la base catalogos_pruebas.")
    from portal.postgres import RepositorioPostgres

    repo = RepositorioPostgres(DSN, maximo_conexiones=2)
    repo.migrar()
    return repo


@pytest.fixture(
    params=[
        "memoria",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(not DSN, reason="Sin PORTAL_PRUEBAS_DSN: PostgreSQL es opcional."),
        ),
    ]
)
def repo(request):
    if request.param == "memoria":
        yield RepositorioEnMemoria()
        return
    repo = _postgres()
    yield repo
    repo.cerrar()


@pytest.fixture
def datos(repo):
    sufijo = uuid4().hex[:10]
    a, b = f"prueba-a-{sufijo}", f"prueba-b-{sufijo}"
    repo.crear_cliente(a, "Negocio A")
    repo.crear_cliente(b, "Negocio B")
    usuario = repo.crear_usuario(f"dueno-{sufijo}@ejemplo.com", "Dueño de prueba", "hash")
    repo.dar_acceso(usuario, a, "administrador")
    yield SimpleNamespace(a=a, b=b, sufijo=sufijo, usuario=usuario)
    repo.borrar_usuario(usuario)
    repo.borrar_cliente(a)
    repo.borrar_cliente(b)


def item(**cambios) -> dict:
    return validar_item(
        {"tipo": "producto", "sku": "FUT-01", "nombre": "Uniforme", "precio": "22", "activo": True,
         "vigente_hasta": "2026-10-11", "opciones": [{"nombre": "Talla", "valores": ["S", "M"]}]}
        | cambios
    )


def foto_de(cliente_id: str) -> dict:
    identificador = uuid4().hex
    return {"id": identificador, "clave": f"{cliente_id}/{identificador}.png",
            "mime": "image/png", "bytes": 10, "sha256": "0" * 64}


def test_negocios_usuarios_y_accesos(repo, datos):
    with pytest.raises(YaExiste):
        repo.crear_cliente(datos.a, "Otro nombre")
    with pytest.raises(YaExiste):
        repo.crear_usuario(f"dueno-{datos.sufijo}@ejemplo.com", "Repetido", "hash")
    with pytest.raises(LookupError):
        repo.dar_acceso(datos.usuario, f"no-existe-{datos.sufijo}", "empleado")

    assert repo.cliente(datos.a) == {"id": datos.a, "nombre": "Negocio A"}
    assert repo.usuario_por_correo(f"dueno-{datos.sufijo}@ejemplo.com")["id"] == datos.usuario

    # Cambiar el correo conserva la cuenta (mismo id, misma contraseña) y no
    # puede pisar el de otra persona.
    nuevo = f"nuevo-{datos.sufijo}@ejemplo.com"
    repo.cambiar_correo(datos.usuario, nuevo)
    assert repo.usuario_por_correo(nuevo)["id"] == datos.usuario
    assert repo.usuario_por_correo(f"dueno-{datos.sufijo}@ejemplo.com") is None
    otro = repo.crear_usuario(f"otro-{datos.sufijo}@ejemplo.com", "Otra persona", "hash")
    try:
        with pytest.raises(YaExiste):
            repo.cambiar_correo(datos.usuario, f"otro-{datos.sufijo}@ejemplo.com")
    finally:
        repo.borrar_usuario(otro)

    repo.dar_acceso(datos.usuario, datos.b, "empleado")
    repo.dar_acceso(datos.usuario, datos.b, "administrador")  # cambia el rol, no duplica
    assert repo.accesos(datos.usuario) == [
        {"cliente_id": datos.a, "nombre": "Negocio A", "rol": "administrador"},
        {"cliente_id": datos.b, "nombre": "Negocio B", "rol": "administrador"},
    ]


def test_la_sesion_respeta_vencimiento_y_acceso(repo, datos):
    repo.crear_sesion("huella-1-" + datos.sufijo, datos.usuario, datos.a, AHORA + timedelta(hours=1))

    sesion = repo.sesion("huella-1-" + datos.sufijo, AHORA)
    assert sesion["cliente_id"] == datos.a and sesion["rol"] == "administrador"
    assert sesion["negocio"] == "Negocio A" and sesion["usuario_id"] == datos.usuario
    assert repo.sesion("huella-1-" + datos.sufijo, AHORA + timedelta(hours=2)) is None

    # Sin acceso al negocio de la sesión, la sesión no sirve.
    repo.cambiar_negocio_de_sesion("huella-1-" + datos.sufijo, datos.b)
    assert repo.sesion("huella-1-" + datos.sufijo, AHORA) is None

    repo.crear_sesion("huella-2-" + datos.sufijo, datos.usuario, datos.a, AHORA + timedelta(hours=1))
    repo.borrar_sesiones_de(datos.usuario)
    assert repo.sesion("huella-2-" + datos.sufijo, AHORA) is None


def test_mi_negocio_y_reglas(repo, datos):
    assert repo.perfil(datos.a)["formas_de_pago"] == []
    assert repo.ajustes(datos.a) == {"moneda": "USD", "cantidad_maxima": None, "descuentos": []}

    perfil = validar_perfil({"direccion": "Managua", "formas_de_pago": ["efectivo"], "lineas": [{"nombre": "Centro"}]})
    ajustes = validar_ajustes({"moneda": "NIO", "cantidad_maxima": 50, "descuentos": [{"desde": 12, "porcentaje": "5"}]})
    repo.guardar_perfil(datos.a, perfil, datos.usuario)
    repo.guardar_ajustes(datos.a, ajustes, datos.usuario)

    assert repo.perfil(datos.a) == perfil
    assert repo.ajustes(datos.a) == ajustes
    assert repo.perfil(datos.b)["direccion"] == ""
    assert repo.perfil(datos.a)["lineas"][0]["codigo"] == "centro" and repo.perfil(datos.b)["lineas"] == []


def test_los_items_quedan_dentro_de_su_negocio(repo, datos):
    creado = repo.crear_item(datos.a, item())

    assert creado["precio"] == "22.00" and creado["vigente_hasta"] == "2026-10-11"
    assert creado["moneda"] == "USD"
    assert creado["opciones"] == [
        {"nombre": "Talla", "valores": [{"valor": "S", "recargo": None}, {"valor": "M", "recargo": None}]}
    ]
    assert (creado["precio_desde"], creado["agotado"], creado["lineas"]) == (False, False, [])
    assert "cliente_id" not in creado
    with pytest.raises(YaExiste):
        repo.crear_item(datos.a, item())
    assert repo.crear_item(datos.b, item())["sku"] == "FUT-01"  # otro negocio, mismo código

    assert repo.item(datos.b, creado["id"]) is None
    assert repo.actualizar_item(datos.b, creado["id"], item(precio="1")) is None
    assert repo.borrar_item(datos.b, creado["id"]) is False

    actualizado = repo.actualizar_item(datos.a, creado["id"], item(sku="OTRO", precio="25.5", moneda="NIO"))
    assert actualizado["precio"] == "25.50" and actualizado["sku"] == "FUT-01"
    assert actualizado["moneda"] == "NIO"

    otro = repo.actualizar_item(datos.a, creado["id"], item(
        precio="30", precio_desde=True, agotado=True, lineas=["centro"],
        opciones=[{"nombre": "Talla", "valores": ["S", {"valor": "XXL", "recargo": "2"}]}],
    ))
    assert (otro["precio_desde"], otro["agotado"], otro["lineas"]) == (True, True, ["centro"])
    assert otro["opciones"][0]["valores"][1] == {"valor": "XXL", "recargo": "2.00"}
    assert [i["sku"] for i in repo.items(datos.a)] == ["FUT-01"]


def test_las_fotos_no_cruzan_negocios_y_sobreviven_al_item(repo, datos):
    creado = repo.crear_item(datos.a, item())
    foto = foto_de(datos.a)

    with pytest.raises(LookupError):
        repo.agregar_foto(datos.b, creado["id"], foto_de(datos.b))
    guardada = repo.agregar_foto(datos.a, creado["id"], foto)

    assert guardada["item_id"] == creado["id"] and guardada["mime"] == "image/png"
    assert repo.foto(datos.b, foto["id"]) is None
    assert [f["id"] for f in repo.fotos_vigentes(datos.a)] == [foto["id"]]
    assert repo.retirar_foto(datos.b, creado["id"], foto["id"]) is False

    assert repo.borrar_item(datos.a, creado["id"]) is True
    assert repo.foto(datos.a, foto["id"])["item_id"] is None
    assert repo.fotos_vigentes(datos.a) == []


def test_retirar_una_foto_la_saca_de_las_vigentes(repo, datos):
    creado = repo.crear_item(datos.a, item())
    foto = foto_de(datos.a)
    repo.agregar_foto(datos.a, creado["id"], foto)

    assert repo.retirar_foto(datos.a, creado["id"], foto["id"]) is True
    assert repo.retirar_foto(datos.a, creado["id"], foto["id"]) is False
    assert repo.fotos_vigentes(datos.a) == []
    assert repo.foto(datos.a, foto["id"]) is not None


def test_las_publicaciones_se_numeran_por_negocio(repo, datos):
    primera = repo.publicar(datos.a, {"items": [1]}, "h1", datos.usuario)
    segunda = repo.publicar(datos.a, {"items": [2]}, "h2", datos.usuario)
    otra = repo.publicar(datos.b, {"items": []}, "h3", None)

    assert (primera["version"], segunda["version"], otra["version"]) == (1, 2, 1)
    assert segunda["publicada_por"] == "Dueño de prueba" and otra["publicada_por"] == ""
    ultima = repo.ultima_publicacion(datos.a)
    assert ultima["version"] == 2 and ultima["contenido"] == {"items": [2]} and ultima["huella"] == "h2"
    assert [p["version"] for p in repo.publicaciones(datos.a)] == [2, 1]
    assert repo.ultima_publicacion(f"sin-publicar-{datos.sufijo}") is None


def test_claves_de_bot_y_auditoria(repo, datos):
    repo.crear_clave_bot("huella-bot-" + datos.sufijo, datos.a, "agente-ia")
    assert repo.cliente_de_clave_bot("huella-bot-" + datos.sufijo) == datos.a
    assert repo.revocar_claves_bot(datos.a) == 1
    assert repo.cliente_de_clave_bot("huella-bot-" + datos.sufijo) is None

    repo.auditar(datos.a, datos.usuario, "publicar", {"version": 1})
    filas = repo.auditoria(datos.a)
    assert filas[0]["accion"] == "publicar" and filas[0]["detalle"] == {"version": 1}
    assert repo.auditoria(datos.b) == []
