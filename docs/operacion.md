# Operación: qué hay desplegado y cómo se atiende

Este archivo es el mapa de lo que está **corriendo de verdad**, no de lo que
el código permite hacer. Si sos un agente de IA que abre este proyecto, leelo
antes de tocar nada desplegado: te ahorra redescubrir todo y repetir errores
que ya se pagaron.

Última actualización: 14 de septiembre de 2026.

---

## Qué hay arriba

Todo vive en **un VPS de Hostinger** (KVM 2, Ubuntu 24.04, IP `2.25.112.244`)
administrado con **Coolify**. Al 11/09/2026: CPU 18 %, memoria 29 %, disco
10/100 GB. Hay margen para más contenedores.

| Servicio | Dominio | Qué es |
|---|---|---|
| `agente-ia` | `agente.automaticnic.online` | Bot de la agencia (Smarth House). Rama `main`. |
| `bot-demo` | `bot-demo.automaticnic.online` | Bot del piloto (Cliente Demo). Rama `piloto-demo`. |
| `portal-catalogos` | `catalogos.automaticnic.online` | Catálogos por negocio. Rama `portal`; base propia y fotos en bind mount persistente. |
| `chatwoot` | `appchatwoot.automaticnic.online` | Una sola instalación, varias cuentas. |
| Coolify | `appcoolify.automaticnic.online` | Panel. |
| PostgreSQL | interno `1hrm4idgdx20aqz5grz12fqb` | Memorias de los bots. |

Identificadores de Coolify, por si hay que llamar a su API:

```text
servidor        dikztpeyebroxdiap1979lsc   (localhost)
proyecto        luzuylwsssqmine3vgtwqdir   (My first project / production)
agente-ia       inuqmphtxqxzzrw3pyp724kk
bot-demo        x2qnwcfwio5vpahcfzdrbsts
portal-catalogos vhvndsnvosry83dqlztwontm
postgres        1hrm4idgdx20aqz5grz12fqb
chatwoot        e5kf6qc7ayczz1rmxqgrx5hq   (es un "service", no una "application")
```

El repositorio es `Kenneth-Bust/ia-prueba`, **público**. Se hizo público
porque Coolify no tenía credenciales de GitHub y era el camino más corto. No
contiene secretos: el `.env` está en `.gitignore` y las credenciales viven en
las variables de entorno de Coolify.

## Smarth House conectado al portal — 14/09/2026

La integración ya está desplegada en `agente-ia` desde `main`, con
`PROMPT_SISTEMA=prompts/smarth_house_portal.md`. Consulta el catálogo publicado
y envía sus fotos por WhatsApp. `prompts/archivo/smarth_house_sin_portal.md` conserva el prompt
anterior como referencia; ya no es el activo de la agencia.

La oferta sigue en versión 4: Promoción, US$45 al mes por número, descripción
aprobada y vigencia hasta el 11/10/2026. No hay un plan regular posterior:
lo confirma el equipo. La clave `agente-ia-portal` ya está configurada en
Coolify; no recrearla ni imprimirla. La demo de uniformes se conservó.

El [registro de migración](despliegue-smarth-portal.md) documenta pruebas,
despliegues, configuración, persistencia de fotos corregida y restauración
de respaldos. La memoria y los identificadores de conversación se conservaron.
Las respuestas ahora avanzan según la pregunta, sin enviar toda la oferta
ante un saludo o una consulta general sobre cómo funciona.

Pendientes operativos: respaldos periódicos fuera del VPS y migración de la
memoria heredada, que todavía usa el superusuario `postgres`, a permisos
limitados. Ya existe una copia manual restaurada y verificada; no cambiar
el DSN del bot de la campaña por rutina.

Para entrar a Coolify usá **https://appcoolify.automaticnic.online**. El
certificado de origen y la redirección HTTP → HTTPS se verificaron. La IP
`http://2.25.112.244:8000` sigue en HTTP y por eso muestra “No es seguro”.

## Cómo se reparte Chatwoot

Una instalación, una cuenta por negocio. El aislamiento es lógico, no físico.

| Cuenta | ID | Bandeja | Bot que la atiende |
|---|---|---|---|
| Smarth House Nicaragua (la agencia) | 1 | WhatsApp `Prueba`, +505 8452 1733 | `agente-ia` |
| Cliente Demo | 2 | API `Pruebas Demo` (ID 2) | `bot-demo` |

**Qué separa a un bot de otro.** Cada bot tiene su `CHATWOOT_CUENTA_ID` y su
`CHATWOOT_WEBHOOK_TOKEN` y `CHATWOOT_BANDEJA_ID`.
El canal descarta cualquier evento de otra cuenta o bandeja **antes** de
llamar al modelo: un evento cruzado no gasta tokens. Verificado en vivo.

`agente-ia` tiene los filtros activos para cuenta **1**, bandeja **1**.
La cuenta 2 conserva además una bandeja API 3 y conversación sintética 5
de la verificación del portal. Su webhook temporal se retiró; no confundirla
con la bandeja 2 que atiende el piloto de uniformes.

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

**Si se cambia esa frase en el prompt activo (`prompts/smarth_house_portal.md`), hay que cambiar también la
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

Enfoque comercial revisado el 13/09 y conectado al portal el 14/09/2026.
Las revisiones, los ID de despliegue y las huellas comprobadas en `/salud` constan
en el [registro de despliegues verificados](#registro-de-despliegues-verificados).

| Concepto | Monto |
|---|---|
| Promoción mensual por número, hasta 1.000 conversaciones | US$ 45 (publicación v4) |
| Instalación | Propuesta que el dueño define con el prospecto en la demo |

El antecedente comercial contempla tres usuarios del panel (uno administrador
y dos que atienden) y transferencia BAC; el bot informa alcance y formas de
pago solo desde lo publicado. El contrato de seis meses es el antecedente comercial
interno: este cambio no cancela contratos ni modifica acuerdos existentes.
Las condiciones de contratación las explica y confirma personalmente el
equipo; el bot no publica plazos de permanencia.

La tarifa incluye el panel CRM propio del negocio para monitorear las
conversaciones, una app para revisar los chats y responder desde el celular,
soporte y capacitación. "Propio" es su espacio y sus accesos, no propiedad del
software, una app exclusiva ni servidor exclusivo. No se promete soporte
humano 24/7 ni una cantidad de sesiones u horas sin confirmación del equipo.
La app permite llevar la atención desde el celular; el envío de
notificaciones al teléfono sigue pendiente, como se explica en el traspaso.

La campaña tiene fecha límite publicada del **11 de octubre de 2026**. Para
quienes contraten dentro de la promoción, **US$ 45 mensuales quedan fijos
para siempre** en el plan de hasta 1.000 conversaciones, según la descripción
aprobada. El bot consulta la publicación vigente antes de informar condiciones.
La primera explicación de precio resume importe, unidad, límite, vigencia
y hasta dos beneficios, sin volcar toda la descripción. La conservación de
tarifa se amplía si preguntan por condiciones. Puede ofrecer una demo una
vez, sin otra pregunta de calificación. Si ya la ofreció, no insiste.
Cada mención de tarifa fija o para siempre debe
llevar el límite de hasta 1.000 conversaciones por mes; los excesos se
consultan, no generan cobros ni una pérdida permanente de la promoción
inventados por el bot.

Un saludo no dispara ofertas. Si preguntan “cómo funciona”, explica el
servicio brevemente y pregunta el rubro si falta; no envía precio, foto y
cierre comercial juntos. Las promociones disponibles o una solicitud de
imagen sí reciben su foto. Las repreguntas consultan `ver_catalogo` sin
reenviarla. Se prefieren 20–50 palabras, con más detalle cuando una
cotización o varias preguntas lo exijan.

Un cambio de tarifa se carga y **publica en el portal**, junto con una nueva
foto si la anterior tiene el precio dibujado. No exige editar el prompt ni
desplegar el bot. No se publicaron aumentos futuros ni vencimientos
anticipados. Los acuerdos particulares existentes los confirma el equipo.

**La presentación inicial ya no incluye instalación ni contrato.** Los
US$ 150 de instalación y el total inicial de US$ 195 son referencias del
enfoque anterior, no cotizaciones autorizadas para el bot. El dueño quiere
mostrar primero la demo y negociar personalmente la instalación. Si
preguntan por el costo inicial, la instalación o la permanencia, el bot
explica que la propuesta y las condiciones las confirma el equipo en la
videollamada. No inventa importes o descuentos, no promete instalación
gratis o incluida ni ausencia de contrato. Si el prospecto prefiere
resolverlo por chat, puede pasar a un asesor sin exigir una llamada.

**Aceptar la demo activa el traspaso existente**, con la frase literal
"Perfecto, te paso con una persona del equipo y te escribe por aquí mismo."
También aplica si la persona pide directamente una demo. No se agrega una
segunda confirmación. El equipo coordina la videollamada: no hay integración
de agenda y el bot no confirma reservas, horarios ni enlaces. La
automatización y la frase que la activa conservan su funcionamiento.

El prompt indica que las cotizaciones y los plazos de respuestas anteriores
deben confirmarse con el equipo, sin repetirlos como vigentes ni invalidar
acuerdos por su cuenta. Se conserva la memoria de los prospectos; no se
borra como parte de este cambio comercial.

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
5. Probar con una conversación de prueba identificada: la mensualidad y sus
   beneficios (incluida la app), la tarifa en un mes posterior, las preguntas
   directas de instalación o contrato y la aceptación de la demo con traspaso
   literal. Verificar también que no insiste si se rechaza la demo ni retoma
   cotizaciones antiguas como vigentes. Los tests con modelos falsos no
   validan la redacción que genera el proveedor real. Antes de reactivar una
   conversación, revisar su etiqueta actual y confirmar que nadie la esté
   atendiendo.

Revisión del 12/09/2026: la conversación 3 ya no tenía la etiqueta `humano`;
no hay que retirarla basándose en un resumen anterior. Los estados de las
conversaciones se comprueban en vivo, no se asumen.

Para desplegar por API se necesita un token de Coolify, distinto del token
de Chatwoot. No guardar tokens en este documento ni pegarlos en un chat.
Consultar la [documentación de despliegues de Coolify](https://coolify.io/docs/api/endpoints/deployments/deploy-by-tag-or-uuid)
para el método y los permisos de la versión instalada.

Al finalizar la campaña, revisar la publicación antes de seguir publicitando.
Las herramientas filtran la vigencia usando la fecha de Nicaragua; una
promoción vencida deja de ofrecerse. Si no hay servicio regular publicado,
el equipo confirma la tarifa. No cambiar acuerdos de quienes contrataron
dentro del plazo ni reutilizar el precio del historial como oferta vigente.

## Registro de despliegues verificados

### 17/09/2026 — AGENDARME, color en Calendar y respuesta al repetir

Dos despliegues de `agente-ia` desde `main`, ambos con `scripts/desplegar.py`:
commit `8d45fa5069a041992746904b42386c124ee3914e` (solicitud
`alal4xl0t1lmfnrnpn5hzkdm`) y commit `f4b9b5249640f0b812efe02ee2287e1d1ae8dab5`
(`msl8sguknzn5oywsn853qjka`). Los dos quedaron `finished` y verificados: commit
esperado, servicio sano y prompt correcto. `/salud` confirmó `estado: ok`,
`agenda: habilitada`, `agenda_estado_calendario: visible` y
`agenda_recordatorios_minutos: [1440, 30]`.

Qué cambió para el contacto: reservar y reprogramar se autorizan con
**`AGENDARME`**; cancelar conserva `CONFIRMAR`. El servidor sigue aceptando
`CONFIRMAR` y `CONFIRMO` sin anunciarlos, porque las conversaciones abiertas
conservan la instrucción anterior en pantalla. El evento de Calendar lleva
color además del título: amarillo con la asistencia pendiente, verde cuando
está confirmada. Repetir `AGENDARME` sobre una propuesta ya ejecutada dejaba
mudo al bot —el webhook cortaba sin contestar y sin pasar el mensaje al
modelo—; ahora responde el estado de la cita y sigue sin duplicar el evento.

Validación: 544 y 546 pruebas aprobadas antes de cada envío. Esa misma noche el
usuario repitió el recorrido real por WhatsApp y pasó completo, incluida la
detección de dos borrados manuales del evento hechos en Calendar. Detalle en
[agenda-incidente-2026-09-17.md](agenda-incidente-2026-09-17.md).

No se modificaron el piloto, el portal, las memorias ni las etiquetas.
**Pendiente:** la plantilla UTILITY sigue sin aprobarse, así que los avisos
fuera de la ventana de 24 h no llegan.

### 15/09/2026 — Confirmación de agenda sin códigos visibles

Publicado y desplegado únicamente `agente-ia`, commit
`c0a6b3c0dcd557022ee9c12fad4b08fac3c4182c`. Tras el push se consultó dos
veces el historial y no apareció un despliegue automático. La solicitud manual
generó `hygjskxg6qw9ouywegefacj5`, estado `finished`; la aplicación quedó
`running:healthy`.

`/salud` confirmó `estado: ok`, `agenda: habilitada`,
`agenda_asistencia: habilitada` y `agenda_confirmacion: simple`, con las mismas
huellas de prompt y reglas aprobadas. La persona ahora responde solo
`CONFIRMAR` a la última propuesta de su conversación o `CONFIRMO ASISTENCIA`.
Los identificadores continúan persistidos para idempotencia y conciliación,
pero ya no aparecen en propuestas, confirmaciones ni recordatorios normales.
Los códigos emitidos antes del cambio siguen admitidos por compatibilidad.

Validación: 492 pruebas aprobadas, 50 omitidas; cinco casos críticos pasaron
además contra PostgreSQL aislado. Se comprobó que repetir `CONFIRMAR` no duplica
el evento, que otra conversación no puede confirmar la propuesta y que siempre
se usa la última propuesta vigente. No se enviaron mensajes a contactos durante
el despliegue. Falta que el usuario repita el recorrido real por WhatsApp.

No se modificaron el piloto, el portal, las memorias ni las etiquetas. Detalle
funcional en [revision-agenda.md](revision-agenda.md).

### 15/09/2026 — Revisión de asistencia y cupos por tratamiento

Publicado y desplegado solo `agente-ia`, commit
`eeab1fe6c579a50de3420e2ec5efd3f15ca55e92`, mediante `scripts/desplegar.py`.
Se comprobó el historial tras el push y durante las pruebas; no apareció
un despliegue automático. La única solicitud manual generó
`7athnkohguvmz0whcowisnug`, estado `finished`, aplicación `running:healthy`.

`/salud` confirmó `estado: ok`, `agenda: habilitada`,
`agenda_asistencia: habilitada`, catálogo de portal y las mismas huellas de
prompt y reglas de Smarth House que el despliegue de agenda anterior.

La reserva completada se distingue ahora de la asistencia confirmada por
el contacto. Reprogramar reinicia esa asistencia. Se incorporó un límite
opcional compartido por tratamiento y se corrigieron el doble conteo de
horarios superpuestos durante un cambio pendiente y las propuestas cuya
duración cambió antes de confirmar.

Pruebas: 488 aprobadas, 46 omitidas en la suite; 12 pruebas seleccionadas
adicionales en PostgreSQL aislado, incluida concurrencia para cuatro cupos.
Lectura de Google Calendar verificada. Sigue pendiente el recorrido real
desde WhatsApp del usuario, la plantilla UTILITY y revisar la renovación
del token emitido durante pruebas. Las notas locales posteriores al primer
despliegue indican que la app OAuth ya se publicó; no se volvió a verificar
ese panel durante esta revisión.

Los cambios locales previos de `docs/agenda.md` se conservaron. No se
desplegaron el piloto ni el portal. Instrucciones y límites de la base clínica:
[revision-agenda.md](revision-agenda.md).

### 15/09/2026 — Agenda de citas con Google Calendar

Se publicó `be1df75` en `main` y se desplegó únicamente `agente-ia` con
`scripts/desplegar.py`. **El autodespliegue no se disparó con el push**: se
comprobó nueve veces en tres minutos contra `/salud` antes de lanzarlo a mano,
para no crear un despliegue duplicado.

| Evidencia | Valor verificado |
|---|---|
| Commit desplegado | `be1df756e3ae8636d8ba3513ea94e62de0e1c146` |
| ID del despliegue en Coolify | `4aobo5pf4z6fiurtjhdtw78z` |
| Estado del despliegue | `finished` |
| Salud pública | `estado: ok`, `agenda: habilitada` |
| SHA-256 del prompt efectivo | `fa5af0234cb9cb2832389a0baffae7c0419faa0c46d415d57a374cc8afce9a17` |
| SHA-256 de las reglas de agenda | `5e7c3e8e3955a13c081874d3e2142652b1f12ed5d0b1018b7ac49597bee188d4` |
| Reglas del catálogo | `65deb39c…`, sin cambios |
| Pruebas automáticas | 468 aprobadas, 34 omitidas, con modelos falsos |

Las dos huellas se compararon contra el contenido guardado en Git, no contra
la copia de trabajo: en Windows los archivos tienen CRLF y el contenedor lee
la versión con LF, así que los bytes difieren aunque el contenido sea el
mismo. La del prompt además se calcula sobre el texto ya recortado por
`leer_prompt()`, no sobre los bytes del archivo.

**Recursos creados.** Base `agenda_smarth` con rol propio dentro del Postgres
existente (`1hrm4idgdx20aqz5grz12fqb`), sin tocar la base de las memorias. La
cuenta de Google autorizada es la de la agencia y el calendario configurado es
su `primary`: las demos conviven con la agenda personal del dueño. Para la
clínica corresponde revisar esa decisión.

**Comprobado contra la API real** antes de desplegar: alta con enlace de Meet,
reprogramación conservando el mismo `evento_id`, cancelación, detección de una
baja hecha a mano en Google con anulación de los recordatorios pendientes, y
una conversación completa con Gemini donde el modelo consultó disponibilidad
antes de responder sin inventar horarios.

**No comprobado todavía:** una reserva completa por WhatsApp con un contacto
real. `/salud` confirma que la agenda cargó, no que el circuito con un cliente
funcione. **Pendientes:** la plantilla UTILITY de Meta no está aprobada, así
que los avisos fuera de la ventana de 24 h —los recordatorios— quedan
bloqueados en la cola; la confirmación inmediata sí sale porque la
conversación está abierta. La app de OAuth sigue en estado de prueba y su
refresh token vence a los siete días: el dominio ya está verificado en Search
Console y falta completar la marca y publicarla. Detalle en
[agenda.md](agenda.md).

### 14/09/2026 — Catálogo del portal, fotos y respuestas progresivas

Integración inicial `45bdb54`, desplegada en agente-ia como
`ispbjxswherbpqcqpy8kbhcc` y en portal-catalogos como
`oh23cd5hq4gdsuvswowmn2gl`. Ajuste de conversación `aed3a69`, despliegue
`r36z1nw75tsfvys4ykmz98m9`. Los tres finalizaron; salud comprobada.
Suite del ajuste: **405 aprobadas, 8 omitidas**, con modelos falsos.

Prompt activo: `prompts/smarth_house_portal.md`, huella
`1f32fe5efcd5b56552c392839c2c551ba21867c7c80e8ce9b718c9b39f1ea3f2`.
Reglas del catálogo:
`65deb39cd50609b4bd9c4f497148f9602d3e70b05b9b56ab7995184c2bdb7a54`.
`catalogo_fuente: portal`. El piloto sigue sano y sin despliegue nuevo.

Diez turnos aislados con Gemini verificaron las respuestas breves; el
recorrido desplegado se probó antes en la cuenta 2. Las fotos de las
conversaciones 34 y 35 indicadas por el usuario figuran leídas por WhatsApp.
No se borraron memorias. Se corrigió el almacenamiento real de fotos y se
restauraron copias de las bases y los archivos. Alcance, identificadores,
autodespliegue y pendientes en
[despliegue-smarth-portal.md](despliegue-smarth-portal.md).

### 13/09/2026 — Demo por videollamada y app para el celular

Se publicó el cambio en `main` y se desplegó únicamente `agente-ia` con
`scripts/desplegar.py`. La campaña de Meta seguía activa durante el cambio.

| Evidencia | Valor verificado |
|---|---|
| Commit de la versión desplegada | `ef42fbbab75371726586a3e4e776d59010fe88b4` |
| ID del despliegue en Coolify | `wzr74l1rzexhwcjw8tpwtrha` |
| Estado del despliegue | `finished` |
| Estado de la aplicación al finalizar | `running:healthy` |
| Salud pública | `estado: ok` |
| SHA-256 del prompt efectivo | `3065e9761ddad910bae5d2595f37c0ca760a941e0f228b6da6450e8c999709b5` |
| Pruebas automáticas | 164 aprobadas, con modelos falsos, sin consumir tokens |

El prompt efectivo coincidió con el del commit publicado. Mantiene la
mensualidad y la promoción, suma la app del celular y busca coordinar una
demo; retira la cotización fija de instalación y la mención automática de
permanencia. La [oferta comercial](#la-oferta-comercial) describe cómo
responder consultas directas y hacer el traspaso.

No se modificaron la rama ni el servicio del piloto, las variables de
producción o las automatizaciones de Chatwoot. No se borraron memorias ni
se cambiaron etiquetas. `/salud` del piloto también devolvió `ok`.

**Alcance de la verificación:** se comprobó el despliegue y la identidad del
prompt cargado. No se envió una conversación real de prueba por WhatsApp;
la validación de las respuestas del proveedor y del recorrido de aceptación
de la demo queda pendiente. No la des por hecha a partir de los tests ni de
la salud del servicio.

**Despliegue automático:** Coolify mostraba `is_auto_deploy_enabled=true`,
pero el historial no registró un despliegue nuevo después del push. Se
comprobó que no hubiera uno nuevo o pendiente antes de iniciar una única
solicitud manual con el comando compartido. En próximos cambios, consultá
el historial después del push antes de crear otro despliegue; no asumas que
el indicador por sí solo demuestra que GitHub lo haya iniciado.

Este registro describe lo verificado en esa fecha. Los commits posteriores
que solo actualizan documentación no implican otro despliegue: antes de
operar, comprobá el estado real en Coolify y la huella del prompt.

## Lo que falta antes de cobrarle a un cliente

- **No hay envío de correos.** Todas las variables `CHATWOOT_SMTP_*` están
  vacías. Consecuencias: las invitaciones a usuarios nuevos nunca llegan,
  nadie puede recuperar su contraseña y no salen notificaciones. Hoy los
  usuarios se crean por API o desde Super Admin, fijando la contraseña a mano.

- **Faltan backups automáticos fuera del VPS.** El 14/09 se respaldaron y
  restauraron memoria de la agencia, catálogo y fotografías, con copia en
  esta PC. Es una copia manual, no una política periódica para todos los
  clientes. Ver el registro de migración antes de tocar esas copias.

- **Verificar límites del modelo por aplicación.** El piloto ya tiene
  `MAX_TOKENS=4096` (comprobado el 14/09); el valor 512 documentado antes era
  histórico. El tope no sustituye probar respuestas y costos con cada negocio.

- **Migrar los permisos de la memoria heredada.** El bot de Smarth House
  todavía conecta como superusuario. Hacer una migración específica, con
  copia y comprobación del historial, antes de afirmar aislamiento completo.

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
9. **Catálogo del negocio**: alta y accesos en el portal compartido, clave
   de lectura propia, datos y fotos publicados. Configurar `PORTAL_URL`,
   `PORTAL_CLAVE_BOT`, `PORTAL_NEGOCIO_ID` y, si corresponde, `PORTAL_LINEA`.
   Usar un prompt que consulte herramientas y comprobar precio y foto desde
   su bandeja. No copiar la identidad, clave o memoria de Smarth House.

## Documentos relacionados

- [piloto-demo.md](piloto-demo.md): el detalle del piloto y qué se comprobó.
- [../AGENTS.md](../AGENTS.md): cómo está hecho el código.
- [../README.md](../README.md): cómo correrlo.
