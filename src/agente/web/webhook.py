"""El servidor que atiende WhatsApp.

Esta es la app que corre en el servidor. **No es la plataforma de pruebas**
(`web/app.py`): son dos cosas distintas y a propósito. La de pruebas es para
tu máquina, tiene la pantalla con los ajustes y no sale de localhost. Esta no
tiene pantalla: es una puerta por donde entra Chatwoot y nada más.

Lo que hace, de punta a punta:

    Chatwoot pega en POST /chatwoot/<token>
      → contestamos 200 al toque              ← esto es obligatorio
      → juntamos la ráfaga de mensajes          (buffer.py)
      → responde el agente                      (agente.py)
      → la respuesta sale por la API de Chatwoot (canales/chatwoot.py)

**Por qué el 200 sale antes de responderle a la persona.** Chatwoot espera
que el webhook conteste rápido; si tardamos lo que tarda el modelo en
pensar, da el pedido por fallado y lo reintenta — y entonces el agente
contesta dos veces lo mismo. Así que primero decimos "recibido" y recién
después pensamos la respuesta, en segundo plano.

**La seguridad es el token en la URL.** Chatwoot no firma sus webhooks (no
hay HMAC como en Meta), así que lo único que separa un mensaje de verdad de
cualquiera que descubra el dominio es que la URL tenga el token. Por eso es
largo y por eso no va en el código.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from time import monotonic

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..agente import Agente
from ..canales.buffer import BufferDeMensajes
from ..canales.chatwoot import Chatwoot
from ..config import Config
from ..prompts import leer_prompt
from ..respuesta import pausa_de_tipeo

registro = logging.getLogger("agente.webhook")


def crear_app(
    config: Config | None = None,
    agente: Agente | None = None,
    canal: Chatwoot | None = None,
) -> FastAPI:
    """Arma el servidor.

    El agente y el canal se pueden pasar armados: es lo que hacen los tests
    para probar todo esto sin salir a internet ni gastar un token.
    """
    config = config or Config.desde_entorno()

    canal = canal or Chatwoot(
        url=config.chatwoot_url,
        token=config.chatwoot_token,
        cuenta_id=config.chatwoot_cuenta_id,
        etiqueta_humano=config.chatwoot_etiqueta_humano,
    )

    # El agente se arma una sola vez y atiende a todo el mundo. Es lo que
    # queremos: adentro tiene la conexión a Postgres, y armarlo por mensaje
    # sería abrir una conexión nueva cada vez.
    agente = agente or Agente(config)

    # Un candado por conversación. Dos personas distintas se atienden a la
    # vez sin problema, pero dos mensajes de la MISMA persona no: si se
    # respondieran en paralelo, los dos leerían la memoria en el mismo punto
    # y el segundo pisaría lo que guardó el primero.
    candados: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
    recibidos_en: dict[str, float] = {}
    cerrando = False

    async def responder(
        conversacion: str, texto: str, adjuntos: list | None = None
    ) -> None:
        """Le pasa la ráfaga al agente y manda la respuesta por Chatwoot."""
        # Se captura antes del candado: una ráfaga posterior tiene su propio
        # reloj, aunque espere mientras terminamos de contestar esta.
        recibido_en = recibidos_en.pop(conversacion, monotonic())
        async with candados[conversacion]:
            registro.info(
                "[%s] %s%s",
                conversacion,
                texto.replace("\n", " | ")[:200],
                f"  [+{len(adjuntos)} adjunto(s)]" if adjuntos else "",
            )

            # El "escribiendo..." y el agente son código bloqueante (urllib y
            # el modelo). Van a un hilo aparte para no trabar el servidor:
            # mientras este mensaje se piensa, los demás siguen entrando.
            await asyncio.to_thread(canal.escribiendo, conversacion, True)

            archivos = await asyncio.to_thread(
                _bajar, canal, conversacion, adjuntos or []
            )

            try:
                mensajes = await asyncio.to_thread(
                    agente.responder_partido, texto, conversacion, archivos
                )
            except Exception as e:
                # El detalle del error va al log, donde lo puede leer quien
                # mantiene esto. A la persona que está del otro lado no: un
                # cliente que llega de un anuncio y recibe un stack trace se
                # va, y encima no entiende qué hacer con eso. Se le pide que
                # repita, que es lo único accionable que puede hacer.
                registro.error(
                    "[%s] %s: %s", conversacion, type(e).__name__, e
                )
                mensajes = [
                    "Perdón, se me complicó la conexión y no pude procesar tu "
                    "mensaje. ¿Me lo repetís?"
                ]

            try:
                if not cerrando:
                    # No sumamos 15 segundos al tiempo del modelo: esperamos
                    # únicamente lo que falta desde el último mensaje recibido.
                    await _esperar_hasta(
                        recibido_en + config.respuesta_minima_segundos
                    )
                await _enviar_con_ritmo(
                    canal, conversacion, mensajes, config.ritmo_humano
                )
            except Exception as e:
                # Acá ya no hay a quién avisarle: el canal de salida es
                # justamente el que falló. Queda en los logs.
                registro.error("[%s] no se pudo enviar: %s", conversacion, e)
            finally:
                await asyncio.to_thread(canal.escribiendo, conversacion, False)

            registro.info("[%s] -> %s mensaje(s)", conversacion, len(mensajes))

    buffer = BufferDeMensajes(config.buffer_segundos, responder)

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        nonlocal cerrando
        registro.info(
            "Agente escuchando - %s / %s - memoria %s - buffer %ss",
            config.proveedor,
            config.modelo,
            "Postgres" if config.modo == "produccion" else "SQLite",
            config.buffer_segundos,
        )
        yield
        # Al desplegar no agregamos una demora artificial al vaciado: el
        # servidor tiene un plazo limitado para cerrar sin perder mensajes.
        cerrando = True
        # Al apagar, soltamos lo que estaba esperando. Sin esto, un deploy
        # justo en esos segundos se come la ráfaga de alguien.
        await buffer.vaciar()

    app = FastAPI(title="Agente - webhook de Chatwoot", lifespan=ciclo_de_vida)

    # -- Las rutas -------------------------------------------------------------

    @app.get("/salud")
    async def salud() -> dict:
        """Para que el servidor sepa que la app está viva.

        Coolify le pega a esto cada tanto. Si no contesta, reinicia el
        contenedor.
        """
        # Identifica el texto efectivo sin publicarlo. Se relee igual que
        # en cada mensaje, para detectar un deploy con el prompt anterior.
        prompt = leer_prompt(config.prompt_sistema)
        return {
            "estado": "ok",
            "proveedor": config.proveedor,
            "modelo": config.modelo,
            "memoria": "postgres" if config.modo == "produccion" else "sqlite",
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "respuesta_minima_segundos": config.respuesta_minima_segundos,
            "buffer_segundos": config.buffer_segundos,
        }

    @app.post("/chatwoot/{token}")
    async def entrante(token: str, pedido: Request) -> JSONResponse:
        """Por acá entra todo lo que manda Chatwoot."""
        if not config.chatwoot_webhook_token or token != config.chatwoot_webhook_token:
            # Sin detalles en la respuesta: al que probó la URL no le decimos
            # si el token existe, si es corto o si le erró por una letra.
            registro.warning("Llamada con token equivocado")
            return JSONResponse({"error": "no autorizado"}, status_code=401)

        try:
            evento = await pedido.json()
        except Exception:
            return JSONResponse({"error": "esperaba JSON"}, status_code=400)

        entrante = canal.traducir(evento)

        if entrante is None or not canal.deberia_responder(entrante):
            # No es un error: es la mayoría de lo que llega. Cada respuesta
            # que manda el propio agente vuelve como un evento más.
            return JSONResponse({"estado": "ignorado"})

        # Se suma a la ráfaga y contestamos ya. Lo que sigue pasa solo.
        recibidos_en[entrante.conversacion] = monotonic()
        await buffer.agregar(
            entrante.conversacion, entrante.texto, entrante.adjuntos
        )

        return JSONResponse({"estado": "recibido"})

    return app


async def _esperar_hasta(instante: float) -> None:
    """Espera sin bloquear otros chats; si el modelo tardó más, no demora."""
    # Revalidar evita enviar antes del mínimo si el reloj del sistema o el
    # temporizador de asyncio despiertan con una pequeña diferencia.
    while (restante := instante - monotonic()) > 0:
        await asyncio.sleep(restante)


async def _enviar_con_ritmo(
    canal: Chatwoot,
    conversacion: str,
    mensajes: list[str],
    ritmo: bool = True,
) -> None:
    """Manda los mensajes uno por uno, con el tiempo de escribirlos en el medio.

    Partir la respuesta en varios globos era la mitad del truco. La otra
    mitad es esta: si los globos salen todos juntos, la persona ve dos
    mensajes aparecer en el mismo instante y eso no lo hace nadie. Delata al
    bot más que una sola respuesta larga.

    Entonces, entre uno y otro: se prende el "escribiendo...", se espera lo
    que tardaría alguien en tipear el que viene, y recién ahí sale.

    Con un solo mensaje esto no hace nada, que es el caso más común.
    """
    for i, texto in enumerate(mensajes):
        await asyncio.to_thread(canal.enviar, conversacion, [texto])

        siguiente = mensajes[i + 1] if i + 1 < len(mensajes) else None
        if siguiente is None or not ritmo:
            continue

        # El "escribiendo..." tiene que estar prendido DURANTE la pausa, no
        # antes de mandar: es lo que hace que la espera se lea como alguien
        # tecleando y no como que el bot se colgó.
        await asyncio.to_thread(canal.escribiendo, conversacion, True)
        await asyncio.sleep(pausa_de_tipeo(siguiente))


def _bajar(canal: Chatwoot, conversacion: str, adjuntos: list) -> list:
    """Baja las fotos y audios que mandó la persona.

    Devuelve pares (contenido, mime) listos para el modelo.

    Por qué se traga el error de una descarga: si la foto no se puede bajar,
    la alternativa es no contestarle nada a la persona. Preferimos responder
    con el texto que sí tenemos —el modelo va a decir que no pudo ver la
    imagen, que es la verdad— antes que quedarnos mudos. Queda en los logs.
    """
    archivos: list[tuple[bytes, str]] = []

    for adjunto in adjuntos:
        try:
            archivos.append(canal.descargar(adjunto))
        except Exception as e:
            registro.error(
                "[%s] no se pudo bajar el adjunto: %s", conversacion, e
            )

    return archivos
