"""El operador de despliegues se prueba sin red, tokens reales ni deploys."""

import hashlib
import io
from pathlib import Path
import sys
import urllib.error

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "src"))

from agente import config as configuracion
from agente.config import ConfigDespliegue, ErrorDeConfiguracion
from scripts import desplegar as d

REVISION = "a" * 40
CONFIG = ConfigDespliegue("token-falso-deploy", "token-falso-read")


def test_credenciales_locales_se_releen_y_no_se_imprimen(tmp_path, monkeypatch):
    monkeypatch.setattr(configuracion, "RAIZ", tmp_path)
    monkeypatch.delenv("COOLIFY_TOKEN", raising=False)
    monkeypatch.delenv("COOLIFY_READ_TOKEN", raising=False)
    archivo = tmp_path / ".env.coolify.local"
    with pytest.raises(ErrorDeConfiguracion, match="Falta COOLIFY_TOKEN"):
        ConfigDespliegue.desde_entorno()
    archivo.write_text("COOLIFY_TOKEN=credencial-ficticia\n", encoding="utf-8")
    config = ConfigDespliegue.desde_entorno()
    assert config.token == config.token_lectura == "credencial-ficticia"
    assert "credencial-ficticia" not in repr(config)
    archivo.write_text("COOLIFY_TOKEN=otra\nCOOLIFY_READ_TOKEN=lectura\n", encoding="utf-8")
    assert ConfigDespliegue.desde_entorno().token_lectura == "lectura"
    monkeypatch.setenv("COOLIFY_TOKEN", "desde-entorno")
    assert ConfigDespliegue.desde_entorno().token == "desde-entorno"


@pytest.mark.parametrize("rama,cambios,remoto", [
    ("piloto-demo", "", REVISION), ("main", " M prompts/sistema.md", REVISION),
    ("main", "", "b" * 40),
])
def test_no_despliega_una_revision_sin_preparar(rama, cambios, remoto, monkeypatch):
    def git(*args):
        return {"branch": rama, "status": cambios, "rev-parse": REVISION, "ls-remote": remoto}[args[0]]
    monkeypatch.setattr(d, "git", git)
    with pytest.raises(d.ErrorDespliegue):
        d.comprobar_revision()


def aplicacion():
    return {"uuid":d.APLICACION, "name":"agente-ia", "git_repository":d.REPOSITORIO,
            "git_branch":"main", "git_commit_sha":"HEAD"}


@pytest.mark.parametrize("campo,valor", [
    ("uuid", "demo"), ("name", "bot-demo"), ("git_repository", "otro/repo"),
    ("git_branch", "piloto-demo"), ("git_commit_sha", "b" * 40),
])
def test_rechaza_destinos_o_commits_distintos(campo, valor, monkeypatch):
    app = aplicacion()
    app[campo] = valor
    monkeypatch.setattr(d, "pedir", lambda *args: app)
    with pytest.raises(d.ErrorDespliegue):
        d.comprobar_aplicacion(CONFIG, REVISION)


def test_acepta_el_destino_correcto_con_token_de_lectura(monkeypatch):
    def pedir(url, token):
        assert url == f"{d.COOLIFY}/applications/{d.APLICACION}"
        assert token == CONFIG.token_lectura
        return aplicacion()
    monkeypatch.setattr(d, "pedir", pedir)
    d.comprobar_aplicacion(CONFIG, REVISION)


def test_solo_usa_get_para_desplegar_si_post_devuelve_405(monkeypatch):
    llamadas = []
    def pedir(url, token="", metodo="GET", datos=None):
        llamadas.append((url, metodo, datos))
        assert token == CONFIG.token
        if metodo == "POST":
            raise d.ErrorHTTP(405)
        return {"deployments":[{"resource_uuid":d.APLICACION, "deployment_uuid":"prueba123"}]}
    monkeypatch.setattr(d, "pedir", pedir)
    assert d.iniciar(CONFIG) == "prueba123"
    assert llamadas == [(f"{d.COOLIFY}/deploy", "POST", {"uuid":d.APLICACION}),
                        (f"{d.COOLIFY}/deploy?uuid={d.APLICACION}", "GET", None)]


@pytest.mark.parametrize("error", [d.ErrorHTTP(403), d.ErrorHTTP(500), d.ErrorDespliegue("timeout")])
def test_no_repite_un_deploy_ante_error_ambiguo(error, monkeypatch):
    llamadas = []
    def pedir(*args):
        llamadas.append(args)
        raise error
    monkeypatch.setattr(d, "pedir", pedir)
    with pytest.raises(d.ErrorDespliegue):
        d.iniciar(CONFIG)
    assert len(llamadas) == 1


@pytest.mark.parametrize("resultado", [
    {}, {"deployments": [{"resource_uuid":"demo", "deployment_uuid":"x"}]},
    {"deployments": [{"resource_uuid":d.APLICACION, "deployment_uuid":"../otra"}]},
])
def test_no_da_por_aceptado_un_deploy_sin_identificar(resultado, monkeypatch):
    monkeypatch.setattr(d, "pedir", lambda *args: resultado)
    with pytest.raises(d.ErrorDespliegue):
        d.iniciar(CONFIG)


def test_finalizado_exige_commit_y_prompt_correctos(monkeypatch):
    despliegue = {"deployment_uuid":"prueba123", "status":"finished", "commit":REVISION}
    salud = {"estado":"ok", "prompt_sha256":hashlib.sha256(b"oferta").hexdigest()}
    def pedir(url, token=""):
        if url == d.SALUD:
            assert token == ""
            return salud
        return despliegue
    monkeypatch.setattr(d, "pedir", pedir)
    monkeypatch.setattr(d, "git", lambda *args: "oferta")
    assert d.estado(CONFIG, "prueba123", REVISION) == "finished"
    despliegue["commit"] = "b" * 40
    with pytest.raises(d.ErrorDespliegue, match="commit"):
        d.estado(CONFIG, "prueba123", REVISION)
    despliegue["commit"] = REVISION
    salud["prompt_sha256"] = "anterior"
    with pytest.raises(d.ErrorDespliegue, match="no coinciden"):
        d.estado(CONFIG, "prueba123", REVISION)


def test_un_deploy_fallido_no_se_confunde_con_servicio_viejo_sano(monkeypatch):
    llamadas = []
    def pedir(*args):
        llamadas.append(args)
        return {"deployment_uuid":"prueba123", "status":"failed", "commit":REVISION}
    monkeypatch.setattr(d, "pedir", pedir)
    with pytest.raises(d.ErrorDespliegue, match="failed"):
        d.estado(CONFIG, "prueba123", REVISION)
    assert len(llamadas) == 1


def test_no_expone_secretos_del_cuerpo_de_error(monkeypatch):
    class Cliente:
        def open(self, pedido, timeout):
            assert pedido.get_header("Authorization") == f"Bearer {CONFIG.token}"
            raise urllib.error.HTTPError(pedido.full_url, 403, "error", {}, io.BytesIO(b"secreto-del-servidor"))
    monkeypatch.setattr(d.urllib.request, "build_opener", lambda *args: Cliente())
    with pytest.raises(d.ErrorHTTP) as exc:
        d.pedir(f"{d.COOLIFY}/applications/{d.APLICACION}", CONFIG.token)
    assert "secreto-del-servidor" not in str(exc.value)
    assert CONFIG.token not in str(exc.value)


def test_no_envia_credenciales_a_otro_host():
    with pytest.raises(d.ErrorDespliegue, match="solo puede"):
        d.pedir("https://otro.example/api/v1/deploy", CONFIG.token)
    with pytest.raises(d.ErrorDespliegue, match="redirigió"):
        d.SinRedirecciones().redirect_request(None, None, 302, "", {}, "https://otro.example")


def test_comprobar_no_inicia_despliegues(monkeypatch):
    monkeypatch.setattr(d.ConfigDespliegue, "desde_entorno", lambda: CONFIG)
    monkeypatch.setattr(d, "comprobar_revision", lambda: REVISION)
    monkeypatch.setattr(d, "comprobar_aplicacion", lambda *args: None)
    monkeypatch.setattr(d, "iniciar", lambda *args: pytest.fail("No debe desplegar"))
    assert d.main(["comprobar"]) == 0
