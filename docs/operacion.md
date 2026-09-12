# Operación: qué hay desplegado y cómo se atiende

Este archivo es el mapa de lo que está **corriendo de verdad**, no de lo que
el código permite hacer. Si sos un agente de IA que abre este proyecto, leelo
antes de tocar nada desplegado: te ahorra redescubrir todo y repetir errores
que ya se pagaron.

Última actualización: 12 de septiembre de 2026.

---

## Qué hay arriba

Todo vive en **un VPS de Hostinger** (KVM 2, Ubuntu 24.04, IP `2.25.112.244`)
administrado con **Coolify**. Al 11/09/2026: CPU 18 %, memoria 29 %, disco
10/100 GB. Hay margen para más contenedores.

| Servicio | Dominio | Qué es |
|---|---|---|
| `agente-ia` | `agente.automaticnic.online` | Bot de la agencia (Smarth House). Rama `main`. |
| `bot-demo` | `bot-demo.automaticnic.online` | Bot del piloto (Cliente Demo). Rama `piloto-demo`. |
| `chatwoot` | `appchatwoot.automaticnic.online` | Una sola instalación, varias cuentas. |
| Coolify | `appcoolify.automaticnic.online` | Panel. |
| PostgreSQL | interno `1hrm4idgdx20aqz5grz12fqb` | Memorias de los bots. |

Identificadores de Coolify, por si hay que llamar a su API:

```text
servidor        dikztpeyebroxdiap1979lsc   (localhost)
proyecto        luzuylwsssqmine3vgtwqdir   (My first project / production)
agente-ia       inuqmphtxqxzzrw3pyp724kk
bot-demo        x2qnwcfwio5vpahcfzdrbsts
postgres        1hrm4idgdx20aqz5grz12fqb
chatwoot        e5kf6qc7ayczz1rmxqgrx5hq   (es un "service", no una "application")
```

El repositorio es `Kenneth-Bust/ia-prueba`, **público**. Se hizo público
porque Coolify no tenía credenciales de GitHub y era el camino más corto. No
contiene secretos: el `.env` está en `.gitignore` y las credenciales viven en
las variables de entorno de Coolify.

## Cómo se reparte Chatwoot

Una instalación, una cuenta por negocio. El aislamiento es lógico, no físico.

| Cuenta | ID | Bandeja | Bot que la atiende |
|---|---|---|---|
| Smarth House Nicaragua (la agencia) | 1 | WhatsApp `Prueba`, +505 8452 1733 | `agente-ia` |
| Cliente Demo | 2 | API `Pruebas Demo` (ID 2) | `bot-demo` |

**Qué separa a un bot de otro.** Cada bot tiene su `CHATWOOT_CUENTA_ID` y su
`CHATWOOT_WEBHOOK_TOKEN`, y el del piloto además lleva `CHATWOOT_BANDEJA_ID`.
El canal descarta cualquier evento de otra cuenta o bandeja **antes** de
llamar al modelo: un evento cruzado no gasta tokens. Verificado en vivo.

`agente-ia` corre `main`, que todavía **no** tiene ese filtro; su protección
es el secreto del webhook. Cuando se mergee `piloto-demo` lo va a tener.

## El traspaso a una persona, de punta a punta

Funciona sin que nadie toque nada, y conviene entender la cadena porque
depende de una frase literal:

```text
el prospecto pide un asesor
  → el asistente responde, tal cual:
    "te paso con una persona del equipo y te escribe por aquí mismo"
  → la automatización "Traspaso a una persona" de Chatwoot detecta la frase
  → le pone la etiqueta `humano`  →  el bot se calla en ese chat
  → asigna la conversación al usuario 1
```

**Si se cambia esa frase en `prompts/sistema.md`, hay que cambiar también la
condición de la automatización**, o el traspaso deja de marcarse y nadie se
entera. Están acopladas a propósito: es lo que evita programar una
herramienta para que el bot etiquete.

Probado en vivo el 11/09/2026 en la conversación 3.

**Lo que todavía no llega es el aviso al teléfono.** Chatwoot genera la
notificación interna (se ve en la campanita y en la app), pero el servidor no
tiene configurado el envío de push: no hay variables de VAPID ni de Firebase.
Hasta resolverlo, los traspasos se miran entrando a la app, en «Míos» o
filtrando por la etiqueta `humano`.

## La memoria arrastra la identidad anterior

Al cambiar el prompt del bot de la agencia de TecnoStore a Smarth House, el
primer mensaje siguió contestando como la tienda de PCs. **No era el
despliegue**: el contenedor ya tenía el prompt nuevo.

El bot lee su prompt más los últimos veinte mensajes de la charla, y veinte
mensajes hablando de placas de video pesan más que unas instrucciones nuevas.

```bash
python scripts/olvidar.py --conversacion 3
python scripts/olvidar.py --todas
```

Borra lo que el bot recuerda; el historial de Chatwoot queda intacto. Ante
un cambio grande de catálogo o identidad: editar, desplegar, comprobar las
respuestas y, si hace falta, olvidar solo las conversaciones de prueba
identificadas. **No ejecutar `--todas --si` como rutina de despliegue**: puede
borrar el contexto de ventas en curso y de personas que están con un asesor.
Antes de un borrado masivo, revisar el alcance y contar con una copia y con
autorización explícita para esas conversaciones.

No afecta a las campañas: cada persona nueva abre una conversación nueva, con
memoria vacía. Solo arrastran las conversaciones que ya venían.

## Los tres niveles de acceso

Esto es lo que se le explica al cliente cuando pregunta quién ve sus chats.

| Nivel | Alcance | Quién |
|---|---|---|
| **SuperAdmin** | Toda la instalación: crear y borrar cuentas | Solo `joelitocruz5@gmail.com` |
| **Administrator** | Una sola cuenta: agentes, bandejas, integraciones | El dueño del negocio, y un técnico de la agencia |
| **Agent** | Solo atender conversaciones | El equipo del cliente |

Comprobado contra la API, no solo en la interfaz: con el token de un agente de
la cuenta 2, los endpoints de la cuenta 1 devuelven
`401 You are not authorized to access this account`.

**El usuario de la agencia no pertenece a las cuentas de los clientes.** Para
entrar a la bandeja de un cliente hay que agregarse explícitamente como
usuario de esa cuenta; ser SuperAdmin no alcanza. Es una buena noticia para
vender: nadie lee los chats de un cliente por accidente.

**El usuario técnico lo controla la agencia, no el cliente.** Su token es el
que usa el bot: si el cliente lo borra o le cambia la contraseña, su bot deja
de responder.

## Trampas que ya se pagaron

Cosas que parecen bugs, no lo son, y cuestan horas de encontrar:

- **El contenedor no alcanza la IP pública del propio servidor.** Un
  `POSTGRES_DSN` con `host=2.25.112.244` funciona desde tu máquina y deja al
  bot en bucle de reinicio adentro de Docker. Usá el nombre interno
  (`1hrm4idgdx20aqz5grz12fqb`). Pasó con los dos bots.

- **La API de Coolify crea cada variable dos veces.** Después de cargar
  variables, hay que listar y borrar los duplicados o quedan 30 donde debería
  haber 15. No rompe, pero confunde a cualquiera que abra el panel.

- **El health check por defecto apunta a `/`, que en esta app es 404.** Hay
  que ponerlo en `/salud` o Coolify marca el contenedor *unhealthy* y puede
  reiniciarlo sin motivo.

- **`FORCE_SSL=true` en Chatwoot lo tira abajo.** Rails redirige el health
  check interno (que entra por HTTP) y Coolify lo da por caído: el proxy deja
  de enrutarle y todo devuelve 503. No hace falta: el proxy ya termina el
  HTTPS. Se probó y se revirtió.

- **Los modelos Gemini 2.5 ya no se habilitan a cuentas nuevas.** Devuelven
  404 recién al primer mensaje, no al arrancar. Ambos bots usan
  `gemini-3.8-flash`.

- **El nivel gratuito de Gemini falla 3 de cada 4 llamadas** con 503 "high
  demand". Con créditos cargados el problema desaparece. El código reintenta
  tres veces con espera creciente.

## La oferta comercial

Definida y cargada en el prompt del bot de la agencia el 11/09/2026:

| Concepto | Monto |
|---|---|
| Instalación, una vez | US$ 150 |
| Mensualidad, hasta 1.000 conversaciones | US$ 45 |

Tres usuarios del panel (uno administrador y dos que atienden), pago por
transferencia BAC, contrato de seis meses.

La tarifa incluye el panel CRM propio del negocio para monitorear las
conversaciones, soporte y capacitación. "Propio" es su espacio y sus accesos,
no propiedad del software ni servidor exclusivo. No se promete soporte
humano 24/7 ni una cantidad de sesiones u horas sin confirmación del equipo.

La campaña tiene fecha límite publicada del **11 de octubre de 2026**. Para
quienes contraten dentro de la promoción, **US$ 45 mensuales quedan fijos
para siempre** en el plan de hasta 1.000 conversaciones: los seis meses son
el compromiso mínimo, no la duración del precio. La primera explicación de
costos debe incluir mensualidad, instalación y contrato.
También debe indicar expresamente que es una promoción por tiempo limitado,
la fecha límite y el CRM, soporte y capacitación incluidos. Cada mención
de tarifa fija o para siempre debe llevar el límite de hasta 1.000
conversaciones por mes; los excesos se consultan, no generan cobros ni una
pérdida permanente de la promoción inventados por el bot. El total inicial
de US$ 195 (150 + 45) fue confirmado por el dueño.

El prompt no garantiza tiempos de respuesta, ausencia total de errores ni
un plazo de instalación sin que lo confirme el equipo. El calendario de
pagos, el criterio exacto de conteo y las ampliaciones de capacidad también
los confirma el equipo; el asistente no los inventa.

El costo real por cliente es de unos US$ 12 al mes con cinco clientes
(US$ 18 fijos de VPS y backups repartidos, más US$ 8,50 de IA por 500
conversaciones). El borrador de contrato está fuera del repositorio.

## Tiempo de respuesta en WhatsApp

`RESPUESTA_MINIMA_SEGUNDOS` vale **15** por defecto. Se mide desde la recepción
del último mensaje de la ráfaga hasta el primer envío, contando el buffer y
la generación de la IA. Si esos pasos ya tardaron más, no agrega otra pausa.
No es una garantía de entrega exacta a los 15 segundos: el proveedor, la red
y las ráfagas pueden alargarla. No afecta Telegram ni la consola.

El webhook sigue confirmando recepción sin esperar esa pausa cuando el
buffer está habilitado. Cada chat mantiene su reloj; no bloquea otras
conversaciones. Al apagar se omite la demora artificial para vaciar pendientes.
`0` desactiva solo el mínimo; no desactiva `BUFFER_SEGUNDOS`. `/salud` publica
ambos valores para verificar la configuración efectiva tras el despliegue.

## Desplegar y comprobar el prompt de la promoción

Para que Codex o Claude hagan el despliegue, usá el
[comando compartido y su configuración local](despliegue.md).

El prompt se relee en cada mensaje **dentro del contenedor**. Como el
Dockerfile lo copia a la imagen, editar el archivo local y hacer push no
actualiza por sí solo producción: hace falta un despliegue de Coolify.

1. Probar los cambios y subir el commit a `main`.
2. En Coolify, abrir **agente-ia**, comprobar repositorio y rama `main`, y
   ejecutar **Deploy**. No seleccionar `bot-demo`.
3. Esperar a que el despliegue termine correctamente. Comprobar el commit
   efectivo en el registro; que el servicio anterior siga sano no demuestra
   que se haya aplicado el cambio.
4. Consultar `https://agente.automaticnic.online/salud`. Además de
   `estado: ok`, las versiones nuevas devuelven `prompt_sha256`: la huella
   SHA-256 del texto efectivo, leído en UTF-8 y sin espacios exteriores,
   igual que lo recibe el modelo. Compararla con el prompt local revisado.
   El endpoint no publica el contenido ni prueba la disponibilidad de Gemini.
5. Probar desde WhatsApp el precio completo, el precio al séptimo mes y la
   derivación a una persona. Antes de reactivar una conversación, revisar
   su etiqueta actual y confirmar que nadie la esté atendiendo.

Revisión del 12/09/2026: la conversación 3 ya no tenía la etiqueta `humano`;
no hay que retirarla basándose en un resumen anterior. Los estados de las
conversaciones se comprueban en vivo, no se asumen.

Para desplegar por API se necesita un token de Coolify, distinto del token
de Chatwoot. No guardar tokens en este documento ni pegarlos en un chat.
Consultar la [documentación de despliegues de Coolify](https://coolify.io/docs/api/endpoints/deployments/deploy-by-tag-or-uuid)
para el método y los permisos de la versión instalada.

Al finalizar la campaña, revisar el prompt antes de seguir publicitando la
oferta. El bot no dispone de una fecha actual confiable y no desactiva la
promoción automáticamente; no cambiar la tarifa prometida a quienes ya
contrataron dentro del plazo.

## Lo que falta antes de cobrarle a un cliente

- **No hay envío de correos.** Todas las variables `CHATWOOT_SMTP_*` están
  vacías. Consecuencias: las invitaciones a usuarios nuevos nunca llegan,
  nadie puede recuperar su contraseña y no salen notificaciones. Hoy los
  usuarios se crean por API o desde Super Admin, fijando la contraseña a mano.

- **El Postgres no tiene backups automáticos.** Todas las memorias de todos
  los clientes están en un servidor sin copia. Hostinger ofrece backups
  diarios por unos US$ 6/mes.

- **`MAX_TOKENS=512` en `bot-demo` corta las respuestas a mitad de frase.**
  Está bajo a propósito para el piloto. Un cliente real necesita 4096.

- **El bot no envía imágenes.** Recibe y entiende fotos y audios, pero solo
  responde texto. Cuando un cliente pide ver un producto, el bot promete
  fotos que nunca llegan: es una venta perdida y ya pasó en pruebas reales.

- **Un solo VPS.** Compartir servidor implica compartir capacidad y caídas.

## Dar de alta un cliente nuevo

El molde, ya validado con el piloto:

1. **Cuenta en Chatwoot** (Platform App o Super Admin). Anotá el ID real.
2. **Usuarios**: el dueño como administrador con **su email real**, su equipo
   como agentes, y un técnico de la agencia como administrador.
3. **Base de memoria** propia en el Postgres, con un rol que solo pueda
   conectarse a ella.
4. **Aplicación en Coolify** desde el mismo repositorio, con su prompt, su
   secreto de webhook y el DSN interno.
5. **Subdominio** `bot-<cliente>.automaticnic.online` apuntando a la IP, y
   health check en `/salud`.
6. **Un único webhook de cuenta** para `message_created` hacia su bot. No
   pongas además el callback del canal ni un Agent Bot: duplicaría los
   eventos.
7. **Su número de WhatsApp** en **su** portafolio de Meta, conectado como
   bandeja dentro de **su** cuenta.
8. **Verificá el aislamiento** antes de entregar: que un usuario suyo reciba
   401 al pedir otra cuenta, y que un evento de otra cuenta se descarte.

## Documentos relacionados

- [piloto-demo.md](piloto-demo.md): el detalle del piloto y qué se comprobó.
- [../AGENTS.md](../AGENTS.md): cómo está hecho el código.
- [../README.md](../README.md): cómo correrlo.
