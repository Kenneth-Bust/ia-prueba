"""El canal de Chatwoot.

Es el que atiende WhatsApp de verdad, pero no le habla a Meta: le habla a
Chatwoot, que está en el medio. El recorrido completo de un mensaje es este:

    persona → WhatsApp → Meta → Chatwoot → (webhook) → agente
                                    ↑                     │
                                    └───── API REST ──────┘

Por qué con Chatwoot en el medio y no directo contra Meta:

  · Queda el historial y la bandeja de entrada, con buscador.
  · Una persona puede meterse en la conversación y seguirla a mano.
  · El mismo agente atiende Instagram, el widget de la web o Telegram sin
    tocar una línea: para nosotros todo entra por el mismo webhook.

A diferencia de Telegram, acá **nadie sale a buscar los mensajes**: Chatwoot
nos pega a una URL cuando pasa algo. Por eso esto necesita un servidor con
dominio y HTTPS, y por eso el webhook vive en su propia app (web/webhook.py).

El `conversacion` (el thread_id de LangGraph) es el **id de conversación de
Chatwoot**. Es la misma unidad que ves en la bandeja: un hilo en la pantalla
es un hilo de memoria del agente. También es lo que necesitamos para
contestar, así que sirve para las dos cosas.

Se usa `urllib`, de la biblioteca estándar, para no sumar una dependencia.
La API de Chatwoot son pedidos HTTP con JSON: no hace falta más.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path
from uuid import uuid4

from .base import Adjunto, AdjuntoSaliente, Canal, MensajeEntrante

registro = logging.getLogger("agente.chatwoot")

# Cuánto esperamos a que Chatwoot conteste. Corre en el mismo servidor que
# el agente, así que si tarda más que esto es porque algo anda mal.
ESPERA_DE_RED = 20

# Bajar un archivo tarda más que pedir un JSON, sobre todo un audio largo.
ESPERA_DE_DESCARGA = 60

# Tope de tamaño por archivo. No es un límite del modelo: es para que una
# persona que manda un video de 80 MB no deje sin memoria al contenedor.
MAXIMO_DE_ADJUNTO = 15 * 1024 * 1024
MAXIMO_DE_ADJUNTO_SALIENTE = 5 * 1024 * 1024
MIMES_DE_IMAGEN_SALIENTE = {"image/jpeg", "image/png"}

# Qué adjuntos vale la pena mandarle al modelo. Los que no están acá se
# descartan en silencio: un .zip no aporta nada a la conversación y encima
# se paga como tokens.
TIPOS_QUE_ENTIENDE = {"image", "audio"}


class ErrorDeChatwoot(Exception):
    """Chatwoot contestó algo que no esperábamos."""


class EnvioIncierto(ErrorDeChatwoot):
    """Se agotó la espera y no sabemos si Chatwoot creó el mensaje o no."""


class Chatwoot(Canal):
    """La bandeja de Chatwoot: por acá entran y salen los mensajes."""

    nombre = "chatwoot"

    def __init__(
        self,
        url: str,
        token: str,
        cuenta_id: str | int,
        etiqueta_humano: str = "humano",
        bandeja_id: str | int = "",
    ) -> None:
        if not url or not token:
            raise ValueError(
                "Faltan datos de Chatwoot. Abrí el .env y completá "
                "CHATWOOT_URL y CHATWOOT_TOKEN."
            )

        # La barra final sobra y duplicada rompe la URL ("...com//api/v1").
        self.url = url.rstrip("/")
        self.token = token
        self.cuenta_id = _identificador(cuenta_id)
        self.bandeja_id = _identificador(bandeja_id) if str(bandeja_id).strip() else ""
        if not self.cuenta_id or (str(bandeja_id).strip() and not self.bandeja_id):
            raise ValueError("La cuenta y la bandeja de Chatwoot necesitan IDs positivos.")
        self.etiqueta_humano = (etiqueta_humano or "").strip().lower()

        # Los mensajes que ya contestamos. Chatwoot reintenta el webhook si no
        # le respondemos rápido, y sin esto el agente contesta dos veces lo
        # mismo. Alcanza con acordarse de los últimos.
        self._ya_contestados: deque[str] = deque(maxlen=1000)

    # -- Entrada ---------------------------------------------------------------

    def traducir(self, evento: dict) -> MensajeEntrante | None:
        """Convierte un evento del webhook en algo que el agente entiende.

        Devuelve None si el evento no es un mensaje que tengamos que mirar:
        otro tipo de evento, o un mensaje que no trae ni texto ni adjuntos.

        Un mensaje **sin texto pero con una foto** es válido y hay que
        atenderlo: en WhatsApp la gente manda la foto del producto sola,
        sin escribir nada. Antes se descartaba y el bot quedaba mudo.
        """
        if not self.pertenece(evento) or evento.get("event") != "message_created":
            return None

        conversacion = evento.get("conversation") or {}
        id_conversacion = conversacion.get("id")
        contenido = evento.get("content") or ""
        if not isinstance(contenido, str):
            return None
        texto = contenido.strip()
        adjuntos = _adjuntos_de(evento)

        if not id_conversacion or (not texto and not adjuntos):
            return None

        return MensajeEntrante(
            texto=texto,
            # El id de conversación es el thread_id: la memoria de cada
            # persona por separado.
            conversacion=str(id_conversacion),
            identificador=str(evento.get("id") or ""),
            datos=evento,
            adjuntos=adjuntos,
        )

    def descargar(self, adjunto: Adjunto) -> tuple[bytes, str]:
        """Baja el archivo de un adjunto. Devuelve (contenido, mime).

        Va con el token de la API porque en Chatwoot los archivos de las
        conversaciones no son públicos: sin el header, la descarga vuelve
        con una pantalla de login en vez del archivo.
        """
        pedido = urllib.request.Request(
            adjunto.url,
            headers={"api_access_token": self.token},
        )

        with urllib.request.urlopen(pedido, timeout=ESPERA_DE_DESCARGA) as respuesta:
            contenido = respuesta.read()
            # El mime que declara el servidor le gana al que adivinamos
            # nosotros por la extensión: WhatsApp manda los audios como
            # .oga, .ogg o .m4a según el teléfono.
            mime = respuesta.headers.get("Content-Type", "") or adjunto.mime

        if len(contenido) > MAXIMO_DE_ADJUNTO:
            raise ErrorDeChatwoot(
                f"El archivo pesa {len(contenido) // 1024} KB y el tope son "
                f"{MAXIMO_DE_ADJUNTO // 1024} KB."
            )

        return contenido, (mime.split(";")[0].strip() or "application/octet-stream")

    def deberia_responder(self, mensaje: MensajeEntrante) -> bool:
        """Si el agente tiene que contestar este mensaje o dejarlo pasar.

        Acá está casi toda la diferencia entre un bot de demo y uno que
        atiende clientes de verdad. Son cuatro filtros y los cuatro importan:
        """
        evento = mensaje.datos

        # También lo comprobamos acá para los canales que reciben un
        # MensajeEntrante ya armado, sin pasar por traducir(). Nunca hacemos
        # consultas de etiquetas ni descargas para eventos de otra cuenta.
        if not self.pertenece(evento):
            return False

        # 1. Solo los mensajes que ENTRAN. Los que salen son las respuestas
        #    del propio agente y las de las personas del equipo. Sin este
        #    filtro el agente se lee a sí mismo y se contesta para siempre:
        #    es el error más caro de todos, porque cada vuelta gasta tokens.
        if _tipo_de_mensaje(evento) != "incoming":
            return False

        # 2. Las notas privadas son para el equipo, no para el cliente. Si el
        #    agente contestara ahí, mandaría al chat algo que era interno.
        if evento.get("private"):
            return False

        # 3. El mismo mensaje dos veces. Chatwoot reintenta si el webhook no
        #    contestó a tiempo, y el reintento trae el mismo id.
        if mensaje.identificador and mensaje.identificador in self._ya_contestados:
            return False

        # 4. El traspaso a una persona. Si la conversación tiene la etiqueta,
        #    el bot se calla: la está atendiendo alguien del equipo. Es *el*
        #    diferencial de tener Chatwoot en el medio — se apaga con un clic
        #    desde la bandeja, sin tocar el servidor.
        if self._la_atiende_una_persona(evento):
            return False

        if mensaje.identificador:
            self._ya_contestados.append(mensaje.identificador)

        return True

    def pertenece(self, evento: dict) -> bool:
        """Acepta únicamente eventos de esta cuenta y, si se fijó, bandeja."""
        if not isinstance(evento, dict):
            return False
        cuenta = evento.get("account") or {}
        conversacion = evento.get("conversation") or {}
        bandeja = evento.get("inbox") or {}
        if not all(isinstance(dato, dict) for dato in (cuenta, conversacion, bandeja)):
            return False
        if _identificador(cuenta.get("id")) != self.cuenta_id:
            return False
        if "account_id" in conversacion:
            if _identificador(conversacion["account_id"]) != self.cuenta_id:
                return False

        if self.bandeja_id:
            # Chatwoot puede ubicar el ID en inbox.id o conversation.inbox_id.
            # Si aparecen varias ubicaciones, todas deben coincidir: elegir
            # solamente una permitiría aceptar un evento contradictorio.
            ids = [
                dato[clave]
                for dato, clave in (
                    (bandeja, "id"), (conversacion, "inbox_id"), (evento, "inbox_id")
                )
                if clave in dato
            ]
            if not ids or any(_identificador(valor) != self.bandeja_id for valor in ids):
                return False
        return True

    def _la_atiende_una_persona(self, evento: dict) -> bool:
        """Si la conversación está marcada con la etiqueta de traspaso."""
        if not self.etiqueta_humano:
            return False

        conversacion = evento.get("conversation") or {}
        etiquetas = conversacion.get("labels")

        # Chatwoot manda las etiquetas en el evento casi siempre. Cuando no
        # las manda (cambia entre versiones y entre tipos de evento) hay que
        # preguntarle, porque dar por hecho que no hay ninguna sería dejar al
        # bot hablando arriba de una persona.
        if etiquetas is None:
            etiquetas = self._etiquetas_de(conversacion.get("id"))

        return self.etiqueta_humano in {
            str(e).strip().lower() for e in etiquetas or []
        }

    def _etiquetas_de(self, id_conversacion) -> list[str]:
        """Le pregunta a Chatwoot qué etiquetas tiene una conversación."""
        if not id_conversacion:
            return []

        # Por qué se traga el error: si Chatwoot no contesta esta consulta, la
        # alternativa es no responderle al cliente. Preferimos responder. El
        # riesgo del otro lado (el bot habla arriba de una persona) existe,
        # pero solo en el caso raro de que justo esta llamada falle.
        try:
            respuesta = self._api(
                "GET", f"conversations/{id_conversacion}/labels"
            )
        except Exception:
            return []

        return respuesta.get("payload") or []

    # -- Salida ----------------------------------------------------------------

    def enviar(
        self,
        conversacion: str,
        mensajes: list[str],
        adjuntos: list[AdjuntoSaliente] | tuple[AdjuntoSaliente, ...] | None = None,
    ) -> None:
        """Manda las respuestas a esa conversación, en orden.

        Salen como `outgoing`, que es lo que Chatwoot entiende por "esto lo
        dice nuestro lado". Desde ahí Chatwoot lo empuja al canal que
        corresponda: WhatsApp, Instagram, el widget de la web.
        """
        pendientes = list(adjuntos or [])
        textos = [texto for texto in mensajes if texto.strip()]
        # Gemini a veces cierra una vuelta de herramienta sin escribir nada.
        # Si ya hay fotos aprobadas, salen igual: quedarse mudo después de
        # buscarlas es perder justo lo que la persona pidió ver.
        if pendientes and not textos:
            textos = [""]

        for texto in textos:
            camino = f"conversations/{conversacion}/messages"
            if pendientes:
                self._enviar_con_archivos(camino, texto, pendientes)
                pendientes = []
                continue

            self._api(
                "POST",
                camino,
                {"content": texto, "message_type": "outgoing"},
            )

    def _enviar_con_archivos(
        self, camino: str, texto: str, adjuntos: list[AdjuntoSaliente]
    ) -> None:
        """Manda el texto con sus imágenes; si Chatwoot las rechaza, solo el texto."""
        try:
            self._api_archivos(camino, texto, list(adjuntos))
        except EnvioIncierto as error:
            # Chatwoot pudo haber creado el mensaje aunque no llegó la
            # confirmación. Reenviar a ciegas le mostraría a la persona el
            # mismo texto dos veces: queda en logs y no se repite.
            registro.error("Envío con adjuntos sin confirmar, no se repite: %s", error)
        except Exception as error:
            # La cotización sigue siendo útil si el archivo falla. El texto
            # sale por el camino probado y el detalle queda en logs; nunca se
            # afirma desde acá que la imagen sí llegó.
            registro.error("No se pudo enviar un adjunto: %s", error)
            aviso = (
                "No pude adjuntar la imagen en este momento; "
                "el equipo puede compartirla directamente."
            )
            self._api(
                "POST",
                camino,
                {
                    "content": f"{texto}\n\n{aviso}" if texto.strip() else aviso,
                    "message_type": "outgoing",
                },
            )

    def escribiendo(self, conversacion: str, encendido: bool = True) -> None:
        """El "escribiendo..." mientras el modelo piensa.

        No es decorativo: una respuesta puede tardar varios segundos y sin
        esto la persona no sabe si la escucharon o si se colgó.
        """
        # Que falle el aviso no puede voltear la respuesta: es cosmético.
        try:
            self._api(
                "POST",
                f"conversations/{conversacion}/toggle_typing_status",
                {"typing_status": "on" if encendido else "off"},
            )
        except Exception:
            pass

    # -- La API ----------------------------------------------------------------

    def yo_soy(self) -> dict:
        """Los datos de la cuenta. Sirve para avisar al arrancar con cuál se habla."""
        return self._api("GET", "conversations?status=open&page=1")

    def enviar_aviso_agenda(self, envio, contacto, cita, plantilla, idioma, *, recuperar=False):
        """Entrega avisos persistentes, verificando destinatario y ventana de WhatsApp."""
        from ..agenda_modelo import ErrorDeAgenda
        conversacion = str(envio["conversacion"])
        if not conversacion.isdigit() or contacto["cuenta"] != self.cuenta_id:
            raise ErrorDeAgenda("El aviso no pertenece a esta cuenta.")
        actual = self._api("GET", f"conversations/{conversacion}")
        remitente = (actual.get("meta") or {}).get("sender") or {}
        if (str(actual.get("inbox_id")) != contacto["bandeja"]
                or f"{self.cuenta_id}:{remitente.get('id')}" != contacto["contacto"]
                or (self.bandeja_id and contacto["bandeja"] != self.bandeja_id)):
            raise ErrorDeAgenda("La conversación ya no coincide con el destinatario del aviso.")
        camino = f"conversations/{conversacion}/messages"
        if recuperar:
            # La API de mensajes no ofrece una clave idempotente garantizada.
            # Si el POST perdió su respuesta, buscamos la marca; nunca reenviamos a ciegas.
            pagina = self._api("GET", camino)
            for mensaje in pagina.get("payload", []):
                if (mensaje.get("content_attributes") or {}).get("agenda_envio_id") == envio["id"]:
                    return mensaje
            return None
        datos = {"content": envio["texto"], "message_type": "outgoing", "private": False,
                 "content_attributes": {"agenda_envio_id": envio["id"]}}
        if actual.get("can_reply") is not True:
            if not plantilla:
                raise ErrorDeAgenda("El aviso necesita una plantilla de WhatsApp aprobada.")
            from datetime import datetime
            from zoneinfo import ZoneInfo
            zona = cita.get("zona", "America/Managua")
            fecha = datetime.fromtimestamp(cita["inicio"], ZoneInfo(zona)).strftime("%d/%m/%Y %H:%M") + " " + zona
            estado = {"alta": "agendada", "mover": "reprogramada", "cancelar": "cancelada", "enlace": "enlace disponible"}.get(envio["tipo"], "recordatorio")
            if envio["tipo"].startswith("error"):
                estado = "cambio pendiente de revisión por el equipo"
            informacion = cita.get("enlace") if cita["estado"] == "confirmada" else "Respondé para consultar al equipo"
            if cita["estado"] == "confirmada" and cita.get("asistencia_codigo") and not envio["tipo"].startswith("error"):
                from ..agenda import Agenda
                informacion = ((informacion + " — ") if informacion else "") + Agenda._instruccion_asistencia(cita)
            parametros = {"1": cita.get("negocio_nombre", "nuestro equipo"), "2": estado,
                          "3": fecha, "4": cita["id"], "5": informacion or "Respondé para consultar al equipo"}
            datos["content"] = (f"Actualización de tu cita con {parametros['1']}: {parametros['2']}. "
                                f"Fecha y hora: {parametros['3']}. Referencia: {parametros['4']}. "
                                f"Información: {parametros['5']}.")
            datos["template_params"] = {"name": plantilla, "category": "UTILITY", "language": idioma,
                                        "processed_params": {"body": parametros}}
        respuesta = self._api("POST", camino, datos)
        if not respuesta.get("id") or respuesta.get("status") == "failed":
            raise ErrorDeAgenda("Chatwoot no aceptó el aviso de agenda.")
        return respuesta

    def _api(self, metodo: str, camino: str, datos: dict | None = None) -> dict:
        """Una llamada a la API de Chatwoot."""
        url = f"{self.url}/api/v1/accounts/{self.cuenta_id}/{camino}"

        pedido = urllib.request.Request(
            url,
            data=json.dumps(datos).encode("utf-8") if datos is not None else None,
            method=metodo,
            headers={
                "Content-Type": "application/json",
                # Así se autentica Chatwoot: no es un Bearer, es este header.
                "api_access_token": self.token,
            },
        )

        try:
            with urllib.request.urlopen(pedido, timeout=ESPERA_DE_RED) as respuesta:
                cuerpo = respuesta.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            # El cuerpo del error es lo único que dice qué pasó de verdad
            # (token vencido, conversación que no existe, cuenta equivocada).
            # Sin esto solo se ve "HTTP Error 404" y no se puede arreglar nada.
            detalle = e.read().decode("utf-8", "replace")[:300]
            raise ErrorDeChatwoot(
                f"Chatwoot devolvió {e.code} en {metodo} {camino}: {detalle}"
            ) from None

        return json.loads(cuerpo) if cuerpo else {}

    def _api_archivos(
        self, camino: str, texto: str, adjuntos: list[AdjuntoSaliente]
    ) -> dict:
        """Crea un mensaje multipart con texto e imágenes de catálogo."""
        archivos: list[tuple[str, str, bytes]] = []
        for adjunto in adjuntos:
            ruta = adjunto.ruta.resolve()
            if not ruta.is_file():
                raise ErrorDeChatwoot(f"No existe el adjunto '{adjunto.codigo}'.")
            if adjunto.mime not in MIMES_DE_IMAGEN_SALIENTE:
                raise ErrorDeChatwoot("Solo se pueden enviar imágenes JPEG o PNG.")
            contenido = ruta.read_bytes()
            if len(contenido) > MAXIMO_DE_ADJUNTO_SALIENTE:
                raise ErrorDeChatwoot("Una imagen saliente supera 5 MB.")
            nombre = (
                Path(adjunto.nombre)
                .name.replace('"', "")
                .replace("\r", "")
                .replace("\n", "")
            )
            archivos.append((nombre or ruta.name, adjunto.mime, contenido))

        limite, cuerpo = _multipart(
            {"content": texto, "message_type": "outgoing"}, archivos
        )
        url = f"{self.url}/api/v1/accounts/{self.cuenta_id}/{camino}"
        pedido = urllib.request.Request(
            url,
            data=cuerpo,
            method="POST",
            headers={
                "Content-Type": f"multipart/form-data; boundary={limite}",
                "api_access_token": self.token,
            },
        )
        try:
            with urllib.request.urlopen(pedido, timeout=ESPERA_DE_RED) as respuesta:
                respuesta_cruda = respuesta.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            detalle = error.read().decode("utf-8", "replace")[:300]
            raise ErrorDeChatwoot(
                f"Chatwoot devolvió {error.code} al enviar adjuntos: {detalle}"
            ) from None
        except (TimeoutError, urllib.error.URLError) as error:
            # Un rechazo claro (respuesta HTTP o conexión negada) deja mandar
            # el texto solo. Un tiempo agotado no: el POST pudo llegar y crear
            # el mensaje, así que se informa como incierto para no duplicarlo.
            motivo = getattr(error, "reason", error)
            if isinstance(motivo, TimeoutError):
                raise EnvioIncierto(
                    f"Chatwoot no confirmó a tiempo el envío con adjuntos: {motivo}"
                ) from None
            raise
        return json.loads(respuesta_cruda) if respuesta_cruda else {}


# -- Ayudantes ----------------------------------------------------------------


def _identificador(valor) -> str:
    """Normaliza IDs de JSON sin confundir true con el número de cuenta 1."""
    if isinstance(valor, bool) or not isinstance(valor, (str, int)):
        return ""
    texto = str(valor).strip()
    if not texto.isascii() or not texto.isdecimal() or int(texto) <= 0:
        return ""
    return str(int(texto))


def _multipart(
    campos: dict[str, str], archivos: list[tuple[str, str, bytes]]
) -> tuple[str, bytes]:
    """Codifica el formulario que espera ``attachments[]`` en Chatwoot."""
    limite = f"----agente-{uuid4().hex}"
    partes: list[bytes] = []

    for nombre, valor in campos.items():
        partes.extend(
            [
                f"--{limite}\r\n".encode("ascii"),
                (
                    f'Content-Disposition: form-data; name="{nombre}"\r\n\r\n'
                ).encode("ascii"),
                str(valor).encode("utf-8"),
                b"\r\n",
            ]
        )

    for nombre, mime, contenido in archivos:
        partes.extend(
            [
                f"--{limite}\r\n".encode("ascii"),
                (
                    'Content-Disposition: form-data; name="attachments[]"; '
                    f'filename="{nombre}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {mime}\r\n\r\n".encode("ascii"),
                contenido,
                b"\r\n",
            ]
        )

    partes.append(f"--{limite}--\r\n".encode("ascii"))
    return limite, b"".join(partes)


def _adjuntos_de(evento: dict) -> list[Adjunto]:
    """Saca las fotos, audios y archivos que vinieron con el mensaje.

    Chatwoot los manda en `attachments`, cada uno con su `data_url` y un
    `file_type` que ya viene clasificado ("image", "audio", "video", "file").
    Nos quedamos con lo que el modelo sabe leer y descartamos el resto: un
    .zip o un .exe no tiene nada que aportarle a la conversación.
    """
    adjuntos: list[Adjunto] = []

    for crudo in evento.get("attachments") or []:
        if not isinstance(crudo, dict):
            continue

        # data_url es el archivo original; thumb_url sería la miniatura, que
        # para leer el texto de una etiqueta no alcanza.
        url = crudo.get("data_url") or crudo.get("file_url") or ""
        if not url:
            continue

        tipo = str(crudo.get("file_type") or "file").strip().lower()
        if tipo not in TIPOS_QUE_ENTIENDE:
            continue

        adjuntos.append(Adjunto(url=url, tipo=tipo))

    return adjuntos


def _tipo_de_mensaje(evento: dict) -> str:
    """Si el mensaje entra o sale.

    Chatwoot lo manda como texto ("incoming"), pero según la versión y el
    endpoint puede venir como número (0 = incoming, 1 = outgoing). Traducimos
    los dos para que un cambio de versión no vuelva loco al bot.
    """
    tipo = evento.get("message_type")

    if isinstance(tipo, int):
        return {0: "incoming", 1: "outgoing"}.get(tipo, "otro")

    return str(tipo or "").strip().lower()
