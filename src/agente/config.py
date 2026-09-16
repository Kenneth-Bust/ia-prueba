"""Configuración del agente.

Todo sale del archivo .env. Nada de credenciales escritas en el código.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values, load_dotenv

# Raíz del proyecto (donde vive el .env)
RAIZ = Path(__file__).resolve().parents[2]

load_dotenv(RAIZ / ".env")


PROVEEDORES_VALIDOS = ("claude", "openai", "gemini")
MODOS_VALIDOS = ("test", "produccion")


def ruta_del_prompt() -> Path:
    """Resuelve el archivo elegido y conserva las configuraciones anteriores."""
    ruta = RAIZ / os.getenv("PROMPT_SISTEMA", "prompts/plantillas/general.md")
    # Los .env privados no viajan con Git. Las rutas antiguas conservan su
    # mismo contenido al actualizar el repo, sin caer en el prompt de emergencia.
    anteriores = {
        RAIZ / "prompts/sistema.md": RAIZ / "prompts/archivo/smarth_house_sin_portal.md",
        RAIZ / "prompts/demo.md": RAIZ / "prompts/plantillas/cliente_demo.md",
    }
    return anteriores.get(ruta, ruta)

# Qué variable de entorno lleva la clave de cada proveedor
CLAVE_POR_PROVEEDOR = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GOOGLE_API_KEY",
}

MODELOS_POR_DEFECTO = {
    "claude": "claude-opus-5",
    "openai": "gpt-5",
    "gemini": "gemini-2.5-pro",
}


class ErrorDeConfiguracion(Exception):
    """Falta algo en el .env o está mal puesto."""


@dataclass(frozen=True)
class ConfigDespliegue:
    """Credenciales locales de operación; el bot no necesita cargarlas."""

    token: str = field(repr=False)
    token_lectura: str = field(default="", repr=False)

    @classmethod
    def desde_entorno(cls) -> "ConfigDespliegue":
        # Se lee al ejecutar el comando, sin reiniciar Codex ni Claude.
        # El archivo está excluido tanto de Git como de la imagen Docker.
        valores = dotenv_values(RAIZ / ".env.coolify.local", interpolate=False)
        token = (os.getenv("COOLIFY_TOKEN") or valores.get("COOLIFY_TOKEN") or "").strip()
        lectura = (
            os.getenv("COOLIFY_READ_TOKEN") or valores.get("COOLIFY_READ_TOKEN") or ""
        ).strip()
        if not token:
            raise ErrorDeConfiguracion(
                "Falta COOLIFY_TOKEN. Guardalo en .env.coolify.local; "
                "no lo pegues en el chat ni en una línea de comandos."
            )
        return cls(token=token, token_lectura=lectura or token)


@dataclass
class Config:
    proveedor: str
    modelo: str
    api_key: str
    max_tokens: int
    memoria_mensajes: int
    prompt_sistema: Path
    modo: str = "test"
    cache: bool = True
    sqlite_ruta: str = "datos/conversaciones.db"
    postgres_dsn: str = ""
    # Vacío mientras el agente corra solo en la computadora. Lo usa el bot
    # de Telegram; el resto del proyecto ni lo mira.
    telegram_token: str = ""

    # -- Chatwoot: solo lo mira el webhook (web/webhook.py) ------------------
    chatwoot_url: str = ""
    chatwoot_token: str = ""
    chatwoot_cuenta_id: str = "1"
    # La etiqueta que apaga al bot en una conversación: el traspaso a una
    # persona. Se pone con un clic desde la bandeja de Chatwoot.
    chatwoot_etiqueta_humano: str = "humano"
    # El secreto que va en la URL del webhook. Chatwoot no firma sus pedidos,
    # así que esto es lo único que separa un mensaje de verdad de cualquiera
    # que haya descubierto el dominio.
    chatwoot_webhook_token: str = ""
    # Cuánto espera juntando la ráfaga antes de contestar (ver buffer.py).
    buffer_segundos: int = 8
    # Tiempo mínimo hasta la primera respuesta, contado desde el último
    # mensaje de la ráfaga. Incluye el buffer y lo que tardó el modelo.
    respuesta_minima_segundos: int = 15
    # Si las respuestas partidas salen con pausa entre globo y globo, como
    # las escribiría una persona. En false salen todas juntas, que es más
    # rápido pero se nota que es un bot (ver respuesta.pausa_de_tipeo).
    ritmo_humano: bool = True
    # Vacío conserva todas las bandejas de la cuenta actual. Cada bot de un
    # cliente lleva un ID explícito para no atender otra bandeja por error.
    chatwoot_bandeja_id: str = ""
    # Catálogo opcional. Si queda vacío, el agente no recibe la herramienta
    # de promociones y conserva exactamente el comportamiento anterior.
    promociones_ruta: Path | None = None
    # Catálogo de productos con fotos y cotizador (catalogo.py). Igual que el
    # de promociones: vacío deja al bot sin esas herramientas.
    catalogo_ruta: Path | None = None
    # Fuente única por aplicación: evita combinar el catálogo de la demo
    # con la oferta real del negocio que autoriza esta clave.
    portal_url: str = ""
    portal_clave_bot: str = field(default="", repr=False)
    portal_negocio_id: str = ""
    portal_linea: str = ""
    agenda_reglas_ruta: Path | None = None
    agenda_dsn: str = field(default="", repr=False)
    agenda_google_cliente_id: str = field(default="", repr=False)
    agenda_google_secreto: str = field(default="", repr=False)
    agenda_google_refresh_token: str = field(default="", repr=False)
    agenda_plantilla_whatsapp: str = ""
    agenda_plantilla_idioma: str = "es"

    def __post_init__(self):
        if self.agenda_reglas_ruta:
            if not all((self.agenda_dsn, self.agenda_google_cliente_id, self.agenda_google_secreto,
                        self.agenda_google_refresh_token, self.chatwoot_cuenta_id, self.chatwoot_bandeja_id)):
                raise ErrorDeConfiguracion("Para activar agenda completá su base, OAuth de Google y cuenta/bandeja de Chatwoot.")
            if self.modo == "produccion" and not self.agenda_dsn.startswith(("postgresql://", "postgres://", "host=", "dbname=", "user=", "service=")):
                raise ErrorDeConfiguracion("La agenda de producción necesita PostgreSQL persistente.")
        if any((self.portal_url, self.portal_clave_bot, self.portal_negocio_id, self.portal_linea)):
            if not all((self.portal_url, self.portal_clave_bot, self.portal_negocio_id)):
                raise ErrorDeConfiguracion(
                    "Configurá juntos PORTAL_URL, PORTAL_CLAVE_BOT y PORTAL_NEGOCIO_ID."
                )
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,40}", self.portal_negocio_id):
                raise ErrorDeConfiguracion("PORTAL_NEGOCIO_ID no es un identificador válido.")
            if self.portal_linea and not re.fullmatch(r"[a-z0-9_]{1,40}", self.portal_linea):
                raise ErrorDeConfiguracion("PORTAL_LINEA no es un código válido.")
            origen = urlsplit(self.portal_url)
            if (
                not origen.hostname or origen.username or origen.password
                or origen.query or origen.fragment or origen.path.rstrip("/")
                or (origen.scheme != "https" and not (
                    origen.scheme == "http" and origen.hostname in ("localhost", "127.0.0.1", "::1")
                ))
            ):
                raise ErrorDeConfiguracion("PORTAL_URL debe ser un origen HTTPS sin ruta ni credenciales.")
            if self.catalogo_ruta or self.promociones_ruta:
                raise ErrorDeConfiguracion(
                    "Al conectar el portal, dejá CATALOGO_RUTA y PROMOCIONES_RUTA vacíos."
                )

    @classmethod
    def desde_entorno(
        cls, proveedor: str | None = None, modelo: str | None = None
    ) -> "Config":
        """Arma la configuración leyendo el .env.

        Se le puede pasar un proveedor y un modelo a mano para pisar los del
        .env: así la plataforma de pruebas los cambia en caliente.
        """
        proveedor = (proveedor or os.getenv("PROVEEDOR", "claude")).strip().lower()

        if proveedor not in PROVEEDORES_VALIDOS:
            raise ErrorDeConfiguracion(
                f"El proveedor '{proveedor}' no existe. "
                f"Elegí uno de: {', '.join(PROVEEDORES_VALIDOS)}."
            )

        nombre_clave = CLAVE_POR_PROVEEDOR[proveedor]
        api_key = (os.getenv(nombre_clave) or "").strip()

        if not api_key:
            raise ErrorDeConfiguracion(
                f"Falta la clave de {proveedor}. "
                f"Abrí el archivo .env y completá {nombre_clave}."
            )

        modelo = (
            modelo
            or os.getenv(f"MODELO_{proveedor.upper()}")
            or MODELOS_POR_DEFECTO[proveedor]
        ).strip()

        modo = (os.getenv("MODO", "test") or "test").strip().lower()
        if modo not in MODOS_VALIDOS:
            raise ErrorDeConfiguracion(
                f"MODO tiene que ser 'test' o 'produccion', no '{modo}'."
            )

        respuesta_minima = _entero("RESPUESTA_MINIMA_SEGUNDOS", 15)
        if respuesta_minima < 0:
            raise ErrorDeConfiguracion(
                "RESPUESTA_MINIMA_SEGUNDOS no puede ser negativo. Usá 0 para desactivar la espera."
            )

        return cls(
            proveedor=proveedor,
            modelo=modelo,
            api_key=api_key,
            max_tokens=_entero("MAX_TOKENS", 4096),
            memoria_mensajes=_entero("MEMORIA_MENSAJES", 20),
            prompt_sistema=ruta_del_prompt(),
            modo=modo,
            cache=_booleano("CACHE", True),
            sqlite_ruta=os.getenv("SQLITE_RUTA", "datos/conversaciones.db"),
            postgres_dsn=(os.getenv("POSTGRES_DSN") or "").strip(),
            telegram_token=(os.getenv("TELEGRAM_TOKEN") or "").strip(),
            chatwoot_url=(os.getenv("CHATWOOT_URL") or "").strip(),
            chatwoot_token=(os.getenv("CHATWOOT_TOKEN") or "").strip(),
            chatwoot_cuenta_id=(os.getenv("CHATWOOT_CUENTA_ID") or "1").strip(),
            chatwoot_etiqueta_humano=(
                os.getenv("CHATWOOT_ETIQUETA_HUMANO") or "humano"
            ).strip(),
            chatwoot_webhook_token=(
                os.getenv("CHATWOOT_WEBHOOK_TOKEN") or ""
            ).strip(),
            buffer_segundos=_entero("BUFFER_SEGUNDOS", 8),
            respuesta_minima_segundos=respuesta_minima,
            ritmo_humano=_booleano("RITMO_HUMANO", True),
            chatwoot_bandeja_id=_identificador_opcional("CHATWOOT_BANDEJA_ID"),
            promociones_ruta=_ruta_catalogo_opcional("PROMOCIONES_RUTA"),
            catalogo_ruta=_ruta_catalogo_opcional("CATALOGO_RUTA"),
            portal_url=(os.getenv("PORTAL_URL") or "").strip().rstrip("/"),
            portal_clave_bot=(os.getenv("PORTAL_CLAVE_BOT") or "").strip(),
            portal_negocio_id=(os.getenv("PORTAL_NEGOCIO_ID") or "").strip(),
            portal_linea=(os.getenv("PORTAL_LINEA") or "").strip(),
            agenda_reglas_ruta=_ruta_catalogo_opcional("AGENDA_REGLAS_RUTA", carpeta="agendas"),
            agenda_dsn=(os.getenv("AGENDA_DSN") or "").strip(),
            agenda_google_cliente_id=(os.getenv("AGENDA_GOOGLE_CLIENTE_ID") or "").strip(),
            agenda_google_secreto=(os.getenv("AGENDA_GOOGLE_SECRETO") or "").strip(),
            agenda_google_refresh_token=(os.getenv("AGENDA_GOOGLE_REFRESH_TOKEN") or "").strip(),
            agenda_plantilla_whatsapp=(os.getenv("AGENDA_PLANTILLA_WHATSAPP") or "").strip(),
            agenda_plantilla_idioma=(os.getenv("AGENDA_PLANTILLA_IDIOMA") or "es").strip(),
        )


def proveedores_disponibles() -> dict[str, bool]:
    """Qué proveedores tienen la clave cargada. Lo usa la web para los botones."""
    return {
        nombre: bool((os.getenv(clave) or "").strip())
        for nombre, clave in CLAVE_POR_PROVEEDOR.items()
    }


# ---------------------------------------------------------------------------
# Guardar ajustes en el .env
# ---------------------------------------------------------------------------

# Solo estas variables se pueden tocar desde la plataforma de pruebas.
#
# NO están en la lista, a propósito:
#   · las claves de API  → no se editan desde el navegador
#   · MODO               → la plataforma es para probar: siempre test
#   · CACHE              → siempre activado; se apaga editando el .env a mano
AJUSTABLES = (
    "PROVEEDOR",
    "MODELO_CLAUDE",
    "MODELO_OPENAI",
    "MODELO_GEMINI",
    "MAX_TOKENS",
    "MEMORIA_MENSAJES",
)


def guardar_ajustes(cambios: dict[str, str]) -> None:
    """Escribe los cambios en el .env y los aplica sin reiniciar.

    Reemplaza solo la línea de cada variable y deja el resto del archivo
    intacto: los comentarios y el orden se conservan. Si la variable no
    estaba, la agrega al final.
    """
    archivo = RAIZ / ".env"

    permitidos = {
        clave: str(valor) for clave, valor in cambios.items() if clave in AJUSTABLES
    }
    if not permitidos:
        return

    lineas = (
        archivo.read_text(encoding="utf-8").splitlines()
        if archivo.exists()
        else []
    )

    pendientes = dict(permitidos)

    for i, linea in enumerate(lineas):
        pelada = linea.strip()
        if not pelada or pelada.startswith("#") or "=" not in pelada:
            continue

        nombre = pelada.split("=", 1)[0].strip()
        if nombre in pendientes:
            lineas[i] = f"{nombre}={pendientes.pop(nombre)}"

    for nombre, valor in pendientes.items():
        lineas.append(f"{nombre}={valor}")

    archivo.write_text("\n".join(lineas) + "\n", encoding="utf-8")

    # Que el proceso que está corriendo vea los valores nuevos ya mismo.
    for nombre, valor in permitidos.items():
        os.environ[nombre] = valor


def clave_de(proveedor: str) -> str:
    """La clave de un proveedor, o cadena vacía si no está cargada."""
    variable = CLAVE_POR_PROVEEDOR.get(proveedor.strip().lower(), "")
    return (os.getenv(variable) or "").strip() if variable else ""


def _entero(nombre: str, por_defecto: int) -> int:
    valor = (os.getenv(nombre) or "").strip()
    if not valor:
        return por_defecto
    try:
        return int(valor)
    except ValueError:
        raise ErrorDeConfiguracion(
            f"{nombre} tiene que ser un número entero, no '{valor}'."
        ) from None


def _booleano(nombre: str, por_defecto: bool) -> bool:
    valor = (os.getenv(nombre) or "").strip().lower()
    if not valor:
        return por_defecto
    return valor in ("1", "true", "si", "sí", "on", "yes")


def _identificador_opcional(nombre: str) -> str:
    valor = (os.getenv(nombre) or "").strip()
    if valor and (not valor.isascii() or not valor.isdecimal() or int(valor) <= 0):
        raise ErrorDeConfiguracion(f"{nombre} tiene que ser un ID positivo o quedar vacío.")
    return str(int(valor)) if valor else ""


def _ruta_catalogo_opcional(nombre: str, carpeta: str = "catalogos") -> Path | None:
    valor = (os.getenv(nombre) or "").strip()
    if not valor:
        return None
    relativa = Path(valor)
    if relativa.is_absolute():
        raise ErrorDeConfiguracion(f"{nombre} debe ser una ruta relativa dentro de {carpeta}/.")
    ruta = (RAIZ / relativa).resolve()
    catalogos = (RAIZ / carpeta).resolve()
    if not ruta.is_relative_to(catalogos) or ruta.suffix.lower() != ".json":
        raise ErrorDeConfiguracion(f"{nombre} debe apuntar a un JSON dentro de {carpeta}/.")
    return ruta


@dataclass
class AdministracionPiloto:
    """Accesos de preparación; el webhook nunca carga estas credenciales."""

    chatwoot_plataforma_token: str
    coolify_url: str
    coolify_token: str

    @classmethod
    def desde_archivo(cls) -> "AdministracionPiloto":
        # El archivo está ignorado por Git y no entra en la imagen Docker.
        # Separarlo evita darle permisos de infraestructura al bot que atiende.
        valores = dotenv_values(RAIZ / ".env.admin.local")
        return cls(
            chatwoot_plataforma_token=(valores.get("CHATWOOT_PLATAFORMA_TOKEN") or "").strip(),
            coolify_url=(valores.get("COOLIFY_URL") or "").strip().rstrip("/"),
            coolify_token=(valores.get("COOLIFY_TOKEN") or "").strip(),
        )


def variables_demo() -> dict[str, str]:
    """Lee exclusivamente el archivo del piloto, sin heredar claves de la agencia."""
    return {
        nombre: valor or ""
        for nombre, valor in dotenv_values(RAIZ / ".env.demo.local").items()
    }


LETRAS_NEGOCIO = "abcdefghijklmnopqrstuvwxyz0123456789-"


def _archivo_agenda(negocio: str = "") -> Path:
    """Un archivo por negocio: conectar un cliente no le pisa el token a otro.

    Sin negocio conserva `.env.agenda.local`, que es el que ya está en uso. El
    nombre se valida con el mismo alfabeto que las reglas de agenda, así no
    puede armar una ruta fuera de la raíz del proyecto con `..` o una barra.
    """
    if not negocio:
        return RAIZ / ".env.agenda.local"
    if not 2 <= len(negocio) <= 50 or any(letra not in LETRAS_NEGOCIO for letra in negocio):
        raise ErrorDeConfiguracion(
            "El negocio se escribe en minúsculas, dígitos y guiones, igual que en sus reglas de agenda."
        )
    return RAIZ / f".env.agenda.{negocio}.local"


def variables_agenda_locales(negocio: str = "") -> dict[str, str]:
    """Conexión administrada de Google; nunca se carga automáticamente en el bot."""
    return {k: v or "" for k, v in dotenv_values(_archivo_agenda(negocio), interpolate=False).items()}


def config_agenda_local(negocio: str = ""):
    """Carga explícita para la CLI, sin cambiar la activación normal del webhook."""
    archivo = _archivo_agenda(negocio)
    load_dotenv(archivo, override=True)
    configuracion = Config.desde_entorno()
    if not configuracion.agenda_reglas_ruta:
        raise ErrorDeConfiguracion(f"Completá AGENDA_REGLAS_RUTA en {archivo.name}.")
    return configuracion


def guardar_conexion_agenda(valores: dict[str, str], negocio: str = ""):
    """Guarda tokens sin imprimirlos ni cambiar la configuración activa."""
    from dotenv import set_key
    permitidas = {"AGENDA_GOOGLE_CLIENTE_ID", "AGENDA_GOOGLE_SECRETO", "AGENDA_GOOGLE_REFRESH_TOKEN"}
    archivo = _archivo_agenda(negocio)
    for clave, valor in valores.items():
        if clave not in permitidas:
            raise ErrorDeConfiguracion("Variable de conexión no permitida.")
        set_key(str(archivo), clave, valor)


def cargar_oauth_google(ruta: Path, negocio: str = ""):
    """Importa el JSON de un cliente OAuth Desktop, fuera del repositorio publicado."""
    import json
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    instalado = datos.get("installed")
    if not isinstance(instalado, dict) or not instalado.get("client_id") or not instalado.get("client_secret"):
        raise ErrorDeConfiguracion("Necesitás el JSON de un cliente OAuth de tipo aplicación de escritorio.")
    guardar_conexion_agenda({"AGENDA_GOOGLE_CLIENTE_ID": instalado["client_id"],
                            "AGENDA_GOOGLE_SECRETO": instalado["client_secret"]}, negocio)


def dsn_pruebas_agenda():
    """Prueba optativa: solo la base aislada que ya usa el portal de pruebas."""
    if not _booleano("AGENDA_PROBAR_POSTGRES", False):
        return ""
    from psycopg.conninfo import conninfo_to_dict
    dsn = dotenv_values(RAIZ / ".env.portal.local", interpolate=False).get("PORTAL_DSN") or ""
    if not dsn or conninfo_to_dict(dsn).get("dbname") != "catalogos_pruebas":
        raise ErrorDeConfiguracion("La prueba de agenda exige la base aislada catalogos_pruebas.")
    return dsn
