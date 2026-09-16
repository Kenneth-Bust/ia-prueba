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
from fastapi.responses import HTMLResponse, JSONResponse

from ..agente import Agente
from ..canales.buffer import BufferDeMensajes
from ..canales.chatwoot import Chatwoot
from ..config import Config
from ..prompts import leer_prompt
from ..respuesta import intercalar_adjuntos, pausa_de_tipeo

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
        bandeja_id=config.chatwoot_bandeja_id,
    )

    # El agente se arma una sola vez y atiende a todo el mundo. Es lo que
    # queremos: adentro tiene la conexión a Postgres, y armarlo por mensaje
    # sería abrir una conexión nueva cada vez.
    agente = agente or Agente(config)
    agenda = getattr(agente, "agenda", None)

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
            if agenda is not None:
                from ..agenda import CONFIRMACION, ASISTENCIA
                from ..agenda_modelo import ErrorDeAgenda
                opcion = texto.strip().lower().rstrip(".!")
                if opcion in ("sin recordatorios", "no recordatorios", "activar recordatorios"):
                    aviso = await asyncio.to_thread(agenda.permitir_recordatorios, conversacion, opcion == "activar recordatorios")
                    await asyncio.to_thread(canal.enviar, conversacion, [aviso])
                    return
                confirmacion = CONFIRMACION.fullmatch(texto.strip())
                asistencia = ASISTENCIA.fullmatch(texto.strip())
                if asistencia:
                    try:
                        aviso = await asyncio.to_thread(agenda.confirmar_asistencia, conversacion, asistencia[1])
                    except ErrorDeAgenda as error:
                        aviso = str(error)
                    await asyncio.to_thread(canal.enviar, conversacion, [aviso])
                    return
                if confirmacion:
                    try:
                        referencia = await asyncio.to_thread(agenda.confirmar, conversacion, confirmacion[1])
                        await asyncio.to_thread(agenda.enviar_pendientes, canal,
                                               config.agenda_plantilla_whatsapp, config.agenda_plantilla_idioma)
                        with agenda.repo.transaccion() as db:
                            cita = db.obtener("cita", referencia)
                        if cita.get("pendiente"):
                            await asyncio.to_thread(canal.enviar, conversacion,
                                ["Estoy verificando el cambio con Google Calendar. Te enviaré la confirmación cuando termine."])
                    except ErrorDeAgenda as error:
                        await asyncio.to_thread(canal.enviar, conversacion, [str(error)])
                    return
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
                salida = await asyncio.to_thread(
                    agente.responder_partido_con_adjuntos,
                    texto,
                    conversacion,
                    archivos,
                )
                mensajes = salida.mensajes
                adjuntos_salida = salida.adjuntos
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
                adjuntos_salida = ()

            try:
                if not cerrando:
                    # No sumamos 15 segundos al tiempo del modelo: esperamos
                    # únicamente lo que falta desde el último mensaje recibido.
                    await _esperar_hasta(
                        recibido_en + config.respuesta_minima_segundos
                    )
                await _enviar_con_ritmo(
                    canal,
                    conversacion,
                    mensajes,
                    config.ritmo_humano,
                    adjuntos=adjuntos_salida,
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
        tarea_agenda = None
        detener_agenda = asyncio.Event()
        if agenda is not None:
            async def mantener_agenda():
                while not detener_agenda.is_set():
                    try:
                        await asyncio.to_thread(agenda.trabajar, canal,
                                               config.agenda_plantilla_whatsapp, config.agenda_plantilla_idioma)
                    except Exception as error:
                        # Una caída externa no apaga WhatsApp. Las operaciones quedan en la base.
                        registro.error("Agenda pendiente de recuperación: %s", type(error).__name__)
                    try:
                        await asyncio.wait_for(detener_agenda.wait(), timeout=30)
                    except asyncio.TimeoutError:
                        pass
            tarea_agenda = asyncio.create_task(mantener_agenda())
        yield
        # Al desplegar no agregamos una demora artificial al vaciado: el
        # servidor tiene un plazo limitado para cerrar sin perder mensajes.
        cerrando = True
        detener_agenda.set()
        if tarea_agenda is not None:
            await tarea_agenda
        # Al apagar, soltamos lo que estaba esperando. Sin esto, un deploy
        # justo en esos segundos se come la ráfaga de alguien.
        await buffer.vaciar()

    app = FastAPI(title="Agente - webhook de Chatwoot", lifespan=ciclo_de_vida)

    # -- Las rutas -------------------------------------------------------------

    # Google exige una página principal y una política de privacidad públicas,
    # en el dominio autorizado, para publicar la app de OAuth. Van acá y no en
    # el portal porque este contenedor ya es el que responde en ese dominio:
    # así son una sola cosa para desplegar. Son de lectura y no tocan el
    # webhook de Chatwoot.
    CORREO_CONTACTO = "joelitocruz5@gmail.com"

    def _pagina(titulo: str, cuerpo: str) -> HTMLResponse:
        return HTMLResponse(
            "<!doctype html><html lang='es'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{titulo} · Smarth House</title><style>"
            "body{font:16px/1.6 system-ui,sans-serif;max-width:46rem;margin:0 auto;"
            "padding:2rem 1rem;color:#1a1a1a;background:#fff}"
            "h1{font-size:1.6rem}h2{font-size:1.1rem;margin-top:2rem}"
            "a{color:#0b57d0}footer{margin-top:3rem;font-size:.85rem;color:#555}"
            "</style></head><body>" + cuerpo +
            "<footer>Smarth House · Nicaragua · "
            f"<a href='mailto:{CORREO_CONTACTO}'>{CORREO_CONTACTO}</a><br>"
            "<a href='/'>Inicio</a> · <a href='/privacidad'>Privacidad</a> · "
            "<a href='/terminos'>Términos</a></footer></body></html>"
        )

    @app.get("/", response_class=HTMLResponse)
    async def inicio() -> HTMLResponse:
        return _pagina("Asistente de agenda", """
<h1>Smarth House · Asistente de agenda</h1>
<p>Smarth House es una agencia nicaragüense que configura asistentes de IA para
atender el WhatsApp de otros negocios. Este servicio atiende las consultas que
llegan por WhatsApp y coordina las demostraciones por videollamada.</p>
<p>Cuando una persona pide una demostración, el asistente consulta los horarios
disponibles, le propone opciones y —solo después de que ella lo confirma por
escrito— registra la cita en el calendario de Google del negocio y le envía la
confirmación con el enlace de la videollamada por WhatsApp.</p>
<h2>Permisos de Google que utiliza</h2>
<p>El asistente usa <code>calendar.events</code> para crear, mover y cancelar
las citas en el calendario del negocio, y la identidad básica de la cuenta
(<code>openid</code>, <code>email</code>) solo para verificar que la cuenta
autorizada es la correcta. No accede a ningún otro dato de Google.</p>
<p>Para consultas: <a href='mailto:""" + CORREO_CONTACTO + "'>" + CORREO_CONTACTO + "</a>.</p>")

    @app.get("/privacidad", response_class=HTMLResponse)
    async def privacidad() -> HTMLResponse:
        return _pagina("Política de privacidad", """
<h1>Política de privacidad</h1>
<p>Describe cómo Smarth House trata los datos personales en su asistente de
agenda por WhatsApp.</p>
<h2>Qué datos tratamos</h2>
<p><strong>De la cuenta de Google que autoriza el servicio:</strong> su
dirección de correo verificada, únicamente para comprobar que la cuenta
autorizada es la correcta, y el acceso a los eventos de su calendario para
crear, modificar y cancelar las citas que gestiona el asistente.</p>
<p><strong>De quien agenda por WhatsApp:</strong> el nombre que indica para la
cita, el identificador de su conversación y su contacto en el sistema de
atención, y la fecha, la hora y la referencia de la cita.</p>
<h2>Para qué los usamos</h2>
<p>Exclusivamente para gestionar las citas: proponer horarios, confirmarlas,
reprogramarlas, cancelarlas y enviar los avisos correspondientes por WhatsApp.
No se usan para publicidad ni para elaborar perfiles.</p>
<h2>Qué no pedimos ni guardamos</h2>
<p>No solicitamos ni almacenamos contraseñas de Google, datos de tarjetas o
cuentas bancarias, ni información de salud. El asistente no pide claves ni
códigos de verificación.</p>
<h2>Uso de los datos de las API de Google</h2>
<p>El uso que Smarth House hace de la información recibida de las API de Google
se ajusta a la
<a href='https://developers.google.com/terms/api-services-user-data-policy'>Política
de Datos de Usuario de los Servicios de API de Google</a>, incluidos sus
requisitos de uso limitado. La información del calendario se usa solo para
prestar la función de agenda visible para el usuario, no se transfiere a
terceros salvo lo necesario para prestarla, y no se utiliza para publicidad.</p>
<h2>Con quién se comparten</h2>
<p>Con Google, para registrar los eventos en el calendario, y con Meta a través
de nuestro sistema de atención, para entregar los mensajes de WhatsApp. No se
venden ni se ceden a terceros con otros fines.</p>
<h2>Conservación y derechos</h2>
<p>Las citas y sus avisos se conservan mientras sean necesarios para la gestión
de la agenda y el registro de lo acordado. Podés pedir el acceso, la
rectificación o la baja de tus datos, y revocar en cualquier momento el acceso
de esta aplicación a tu cuenta de Google desde
<a href='https://myaccount.google.com/permissions'>los permisos de tu cuenta</a>.</p>
<p>Para ejercer esos derechos, escribinos a
<a href='mailto:""" + CORREO_CONTACTO + "'>" + CORREO_CONTACTO + """</a>.</p>""")

    @app.get("/terminos", response_class=HTMLResponse)
    async def terminos() -> HTMLResponse:
        return _pagina("Términos del servicio", """
<h1>Términos del servicio</h1>
<h2>Qué ofrece</h2>
<p>El asistente de Smarth House responde consultas por WhatsApp y coordina
citas para demostraciones por videollamada. Una propuesta de horario no es una
cita reservada: la reserva existe cuando la persona la confirma por escrito y
el sistema devuelve su referencia.</p>
<h2>Uso aceptable</h2>
<p>El servicio es para coordinar citas legítimas. No debe usarse para enviar
contenido ilícito, suplantar a otra persona ni interferir con su
funcionamiento. Podemos suspender la atención automática ante un uso abusivo.</p>
<h2>Disponibilidad y límites</h2>
<p>El asistente depende de servicios de terceros (WhatsApp, Google Calendar) y
puede no estar disponible en algún momento. No garantizamos ausencia de errores
ni un tiempo de respuesta determinado. Las citas pueden ser reprogramadas o
canceladas por cualquiera de las partes; los cambios se avisan por WhatsApp.</p>
<h2>Contacto</h2>
<p>Consultas y reclamos: <a href='mailto:""" + CORREO_CONTACTO + "'>" + CORREO_CONTACTO + "</a>.</p>")

    @app.get("/salud")
    async def salud() -> dict:
        """Para que el servidor sepa que la app está viva.

        Coolify le pega a esto cada tanto. Si no contesta, reinicia el
        contenedor.
        """
        # Identifica el texto efectivo sin publicarlo. Se relee igual que
        # en cada mensaje, para detectar un deploy con el prompt anterior.
        prompt = leer_prompt(config.prompt_sistema)
        resultado = {
            "estado": "ok",
            "proveedor": config.proveedor,
            "modelo": config.modelo,
            "memoria": "postgres" if config.modo == "produccion" else "sqlite",
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "respuesta_minima_segundos": config.respuesta_minima_segundos,
            "buffer_segundos": config.buffer_segundos,
        }
        if config.portal_url:
            from ..portal import REGLA_CATALOGO

            resultado["catalogo_fuente"] = "portal"
            resultado["reglas_catalogo_sha256"] = hashlib.sha256(
                REGLA_CATALOGO.encode("utf-8")
            ).hexdigest()
        if agenda is not None:
            resultado["agenda"] = "habilitada"
            resultado["agenda_asistencia"] = "habilitada"
            resultado["agenda_reglas_sha256"] = hashlib.sha256(config.agenda_reglas_ruta.read_bytes()).hexdigest()
        return resultado

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

        if not isinstance(evento, dict):
            return JSONResponse({"error": "esperaba un objeto JSON"}, status_code=400)

        entrante = canal.traducir(evento)

        if entrante is None or not canal.deberia_responder(entrante):
            # No es un error: es la mayoría de lo que llega. Cada respuesta
            # que manda el propio agente vuelve como un evento más.
            return JSONResponse({"estado": "ignorado"})

        if agenda is not None:
            from ..agenda_modelo import ErrorDeAgenda
            conversacion = evento.get("conversation") or {}
            remitente = evento.get("sender") or (conversacion.get("meta") or {}).get("sender") or {}
            try:
                await asyncio.to_thread(agenda.registrar_contacto, entrante.conversacion,
                                       remitente.get("id"), config.chatwoot_cuenta_id, config.chatwoot_bandeja_id)
            except ErrorDeAgenda:
                return JSONResponse({"error": "contacto no verificable"}, status_code=400)

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
    adjuntos=None,
) -> None:
    """Manda los mensajes uno por uno, con el tiempo de escribirlos en el medio.

    Partir la respuesta en varios globos era la mitad del truco. La otra
    mitad es esta: si los globos salen todos juntos, la persona ve dos
    mensajes aparecer en el mismo instante y eso no lo hace nadie. Delata al
    bot más que una sola respuesta larga.

    Entonces, entre uno y otro: se prende el "escribiendo...", se espera lo
    que tardaría alguien en tipear el que viene, y recién ahí sale.

    Con un solo mensaje esto no hace nada, que es el caso más común.

    Las fotos aprobadas salen como un mensaje propio, después del globo que
    las anuncia: ver respuesta.intercalar_adjuntos(). Sin texto, igual salen.
    """
    envios = intercalar_adjuntos(mensajes, adjuntos)

    for i, (texto, fotos) in enumerate(envios):
        if fotos:
            await asyncio.to_thread(canal.enviar, conversacion, [], list(fotos))
        else:
            await asyncio.to_thread(canal.enviar, conversacion, [texto])

        siguiente = envios[i + 1] if i + 1 < len(envios) else None
        if siguiente is None or not ritmo:
            continue

        # El "escribiendo..." tiene que estar prendido DURANTE la pausa, no
        # antes de mandar: es lo que hace que la espera se lea como alguien
        # tecleando y no como que el bot se colgó. Una foto no se tipea: con
        # texto vacío toma la pausa mínima.
        await asyncio.to_thread(canal.escribiendo, conversacion, True)
        await asyncio.sleep(pausa_de_tipeo(siguiente[0]))


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
