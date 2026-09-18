# Agenda: Smarth House y base para otros negocios

## Estado

Desarrollado el 15/09/2026 en `funcionalidad/agenda-google-calendar`,
partiendo de `9bf6a89`. **Desplegado y probado por WhatsApp**; la revisión
vigente es `c0a6b3c`: `agente-ia` corre con agenda, asistencia y confirmación
sencilla habilitadas y atiende WhatsApp real.
El registro del despliegue, con identificadores y huellas, está en
[operacion.md](operacion.md#registro-de-despliegues-verificados).

**Corrección local del 17/09/2026, pendiente de despliegue:**
`correccion/agenda-confirmaciones-hora` corrige el incidente observado en la
conversación 57. La política de 30 minutos descrita más abajo corresponde a
esta corrección; no asumir que producción la tiene hasta verificar el despliegue.
Detalle de causas, pruebas y aviso al dueño en
[agenda-incidente-2026-09-17.md](agenda-incidente-2026-09-17.md).

La prueba funcional real creó la cita, el enlace de Meet y confirmó asistencia
con las respuestas `CONFIRMAR` y `CONFIRMO ASISTENCIA`. Falta comprobar la
entrega del recordatorio a su hora. No crear cuentas ni recursos para la clínica
sin su aceptación.

### Verificado el 15/09/2026 contra Google real

Cuenta autorizada `joelitocruz5@gmail.com`, proyecto `smarth-house-agenda`,
cliente OAuth de escritorio, alcances `calendar.events`, `userinfo.email` y
`openid`. Base local `datos/agenda-pruebas.db`, reglas de Smarth House.

| Operación | Resultado |
|---|---|
| Alta | Evento creado con enlace de Meet generado por Google. |
| Reprogramar | Conserva el mismo `evento_id`: no duplica el evento. |
| Cancelar | El evento queda `cancelled` y sale del calendario activo. |
| Baja hecha a mano en Google | `sincronizar()` la detecta, cancela la cita, **anula los recordatorios pendientes** y encola el aviso de cancelación. |
| Conversación real (Gemini) | El modelo llamó a `consultar_disponibilidad` antes de cada respuesta y a `agendar_cita` con la fecha ISO; no inventó horarios. La propuesta se devolvió literal y la confirmación la ejecutó el servidor. |

Suite completa: 492 pasaron, 50 salteados; cinco casos críticos adicionales
pasaron contra PostgreSQL aislado. El usuario eligió el calendario
`primary` de esa cuenta, no uno dedicado: las demos conviven con su agenda
personal y cualquier evento suyo ocupa el cupo. Para la clínica corresponde
revisar esa decisión, porque ahí son cuatro calendarios y datos de pacientes.

### Estado de los requisitos

1. ~~**PostgreSQL propio de la agenda.**~~ Hecho: base `agenda_smarth` con rol
   propio dentro del Postgres existente, host interno `1hrm4idgdx20aqz5grz12fqb`.
   Con la IP pública el contenedor no se alcanza a sí mismo.
2. **Plantilla de WhatsApp aprobada: pendiente.** Solo afecta a los avisos
   fuera de la ventana de 24 h, es decir los recordatorios, que quedan
   `bloqueado` en la cola. La confirmación inmediata sale como mensaje normal
   porque la conversación está abierta ([chatwoot.py](../src/agente/canales/chatwoot.py)
   solo exige plantilla cuando `can_reply` es falso).
3. ~~**Publicar la app de OAuth.**~~ Hecho el 15/09/2026: dominio verificado en
   Search Console y estado **En producción**. Google pide verificación pero no
   es necesaria para operar: solo quita la pantalla de «app no verificada», que
   ve únicamente quien autoriza. El límite de 100 usuarios es por ciclo de vida
   del proyecto y se gasta a razón de una cuenta por cliente. **Queda pendiente
   reemitir el token**: el que está en uso se emitió en modo prueba y que herede
   la vigencia de producción no está documentado. Reconectar con
   `conectar_google_agenda.py` y actualizar `AGENDA_GOOGLE_REFRESH_TOKEN` en
   Coolify. No subir un logotipo: obliga a pasar por verificación.
4. ~~**Verificar `PROMPT_SISTEMA` en el servidor.**~~ Confirmado en Coolify:
   `prompts/smarth_house_portal.md`. Un valor viejo se traduce en silencio al
   prompt archivado (`config.ruta_del_prompt()`) y dejaría al bot con las
   herramientas de agenda y un prompt que no sabe que existen.
5. ~~**Cargar las siete variables de una sola vez.**~~ Hecho. Si quedan a
   medias, la validación de `config.py` impide arrancar el contenedor.

La configuración aprobada de Smarth House es:

- Lunes a sábado, de 08:00 a 17:30, zona `America/Managua`.
- Demo por videollamada de 30 minutos, una a la vez.
- Confirmación inmediata de la reserva y recordatorios 24 horas y 30 minutos
  antes. Solo el de 30 minutos pide asistencia, si todavía no está confirmada.
- Agenda editable también desde Google Calendar por el equipo.

Supuestos iniciales editables: anticipación mínima de una hora, agenda abierta
60 días y enlace de Google Meet por cita. La cuenta indicada por el usuario
se autoriza con OAuth; nunca guardar sus contraseñas en el proyecto.

## Alta de la agenda para un cliente nuevo

**No se repite nada de Google Cloud.** El proyecto, la Calendar API, los tres
alcances, el cliente OAuth de escritorio con su JSON, las páginas públicas del
webhook, el dominio verificado y la publicación de la app son de la agencia y
están hechos desde el 15/09/2026. Como la app está publicada, **tampoco hay que
agregar la cuenta del cliente como usuario de prueba**.

Por cliente hacen falta cinco cosas:

1. **`agendas/<negocio>.json`** con sus días, horarios, servicios, duración,
   recursos y calendarios. Si ese bot además usa portal, el `negocio` del
   archivo debe coincidir con su `PORTAL_NEGOCIO_ID` o `crear_agenda()` se
   niega a arrancar.
2. **Autorizar su cuenta de Google**, indicando el negocio para no pisarle el
   token a otro cliente:

   ```powershell
   .\.venv\Scripts\python.exe scripts\conectar_google_agenda.py --credenciales datos/google-oauth.json --correo CORREO_DEL_CLIENTE --negocio NEGOCIO
   ```

   Guarda en `.env.agenda.<negocio>.local`. Sin `--negocio` escribe en
   `.env.agenda.local`, que es el de Smarth House.
3. **Base PostgreSQL propia** con rol limitado. El DSN va con el host interno
   de Docker, nunca con la IP pública del servidor.
4. **Aplicación propia en Coolify** con sus siete variables de agenda, cargadas
   de una sola vez.
5. **Plantilla UTILITY propia** aprobada en su WhatsApp Business, para los
   avisos fuera de la ventana de 24 horas.

**Qué cuenta de Google pedirle.** La que sea dueña de los calendarios donde van
las citas; sirve la del propio negocio y no hace falta crear una nueva. La
condición real es que **una sola cuenta autorizada pueda escribir en todos los
calendarios del archivo de reglas**. Para un consultorio de cuatro
profesionales, lo natural es una cuenta del negocio con cuatro calendarios
adentro, no cuatro cuentas distintas. `ReglasAgenda` exige que cada recurso
tenga un calendario **distinto**: dos recursos no pueden compartir uno.

Conviene un calendario dedicado por recurso y no el `primary` de una persona.
Smarth House usa `primary` por decisión del usuario, así que sus demos conviven
con su agenda personal y cualquier evento suyo ocupa el cupo. En un negocio con
datos de pacientes esa decisión debe revisarse.

## Implementación

| Archivo | Responsabilidad |
|---|---|
| `src/agente/agenda_modelo.py` | Horarios, zona, servicios, profesionales, cupos y superposición de intervalos. |
| `src/agente/agenda_repositorio.py` | Persistencia SQLite de prueba o PostgreSQL de producción. Tabla propia `agenda_registros`, separada del checkpointer. |
| `src/agente/agenda.py` | Herramientas, propuestas, reservas, cancelaciones, cambios, sincronización y cola de avisos. |
| `src/agente/calendario_google.py` | OAuth offline y API de Calendar; eventos con ID estable y cambios condicionados por versión. |
| `src/agente/canales/chatwoot.py` | Avisos en ventana abierta o mediante plantilla; validación de contacto/bandeja y conciliación de envíos inciertos. |
| `src/agente/web/webhook.py` | Confirmación determinista y trabajador de agenda cada 30 segundos. |
| `agendas/smarth_house.json` | Reglas de la agencia. Se incluyen en Docker. |
| `agendas/clinica_ejemplo.json` | Configuración ficticia de cuatro profesionales; no apunta a calendarios reales. |

No se añadieron dependencias Python: utiliza la biblioteca estándar, LangChain
y el conector/pool de PostgreSQL disponibles en el proyecto.

### Estado visible en Google Calendar

Las videollamadas administradas por el bot muestran la diferencia entre una
reserva y la confirmación de asistencia:

- `⏳ Agendada — Demo por videollamada — Nombre`: la cita existe, ocupa el
  horario y la asistencia todavía está pendiente.
- `✅ Confirmada — Demo por videollamada — Nombre`: la persona respondió
  `CONFIRMO ASISTENCIA`.

La descripción muestra por separado `Reserva: agendada` y `Asistencia:
pendiente` o `confirmada`, además de la referencia interna. Las notas manuales
que el equipo agregue después de ese bloque se conservan. Confirmar asistencia
actualiza el mismo evento, sin crear otro ni cambiar su hora o enlace.

Reprogramar desde el bot o mover el evento en Google reinicia la asistencia y
lo devuelve a `⏳ Agendada`. El trabajador concilia títulos y descripciones de
citas vigentes cada 30 segundos; por eso también migra las videollamadas
futuras creadas antes de esta mejora. Si Google falla después de registrar la
respuesta, la confirmación queda guardada y el trabajador vuelve a reflejarla
sin pedírsela otra vez a la persona.

`Confirmada` significa confirmación de asistencia, no que la cita ya fue
atendida. Un estado clínico posterior, como atendida o ausente, sigue fuera de
esta etapa.

La agenda se activa únicamente con `AGENDA_REGLAS_RUTA` y una configuración
completa. Portal y agenda pueden coexistir. Sin esa variable, los bots
conservan las herramientas existentes y la demo se deriva al equipo.

### Confirmación antes de modificar

Las herramientas preparan una propuesta con fecha, horario, recurso y nombre.
La persona responde `CONFIRMAR` para ejecutarla, sin copiar identificadores. El
servidor recupera la última propuesta de esa conversación. La propuesta
vence en 15 minutos y no retiene cupos. Al confirmar se valida nuevamente la
capacidad, dentro de una transacción compartida por todas las conversaciones.

El modelo no tiene una herramienta para ejecutar esa confirmación: el webhook
procesa el texto explícito y comprueba que la propuesta pertenezca al contacto
y a la conversación. La respuesta visible de una propuesta sale del resultado
validado de la herramienta, aunque el modelo redacte después otra cosa.
La confirmación sigue siendo explícita aunque la solicitud inicial llegue por
audio. También acepta `CONFIRMO` y `SÍ, CONFIRMO`; un «sí» suelto no crea ni
cancela citas. Repetir la confirmación no duplica el evento. Las referencias
técnicas quedan en PostgreSQL y en la descripción privada de Google.

La corrección del 17/09 también admite negrita y cursiva alrededor del comando,
por ejemplo `*CONFIRMAR*` o `_Confirmar_`. No interpreta una negación, una
pregunta, texto tachado ni una corrección de horario como autorización.
La reserva no pide una segunda confirmación de asistencia de inmediato.
El último recordatorio la solicita; si ya se confirmó, no vuelve a pedirla.

Cada llamada al modelo recibe hora actual en la zona del negocio y estado
persistido de propuestas y citas del contacto. Ese contexto no se guarda en
la memoria ni en el bloque de caché: evita repetir la hora de una consulta
vieja o tratar como pendiente una reserva completada por el webhook. La
disponibilidad y los cambios manuales se verifican con las herramientas.

Los IDs de contacto provienen del webhook autenticado; no son argumentos que
pueda inventar el modelo. Una conversación nueva del mismo contacto puede
consultar las mismas citas. No incluye gestión de tutores/familiares ni
historia clínica: cada cita pide solo el nombre necesario para identificarla.

### Capacidad y recuperación

- PostgreSQL serializa la asignación con un candado por negocio. El pool
  compartido usa como máximo tres conexiones por DSN en cada proceso.
- Las operaciones pendientes consumen capacidad. Una reprogramación incierta
  protege origen y destino hasta resolver qué ocurrió en Google.
- El ID del evento es estable. Después de un timeout se consulta ese mismo
  evento; no se repite la reserva con otro identificador.
- Los cambios y cancelaciones usan `etag`/`If-Match`. Un cambio concurrente
  hecho por recepción exige volver a consultar en vez de sobrescribirlo.
- Los avisos tienen clave propia por cita, versión y tipo. Una falla al enviar
  WhatsApp no vuelve a crear la cita.
- `aceptado` significa que Chatwoot recibió el mensaje, no que WhatsApp lo
  entregó o que el contacto lo leyó. Verificar entrega en Chatwoot.
- Ante un POST incierto a Chatwoot se busca la marca `agenda_envio_id`. Si
  no se encuentra en los mensajes recuperados, queda `incierto` para revisión;
  no se reenvía automáticamente. La API no garantiza idempotencia de envíos.
- Los recordatorios atrasados más de 30 minutos se omiten para no enviar
  varios avisos viejos al reiniciar. Nunca se envían después del inicio.

Las propuestas y reservas viven en la base de agenda, no en la memoria del
modelo. No borrar conversaciones ni checkpoints para cambiar la agenda.

## Recepción y Google Calendar

El trabajador consulta eventos por lotes dentro del horizonte configurado y
actualiza citas conocidas. Los cambios de horario y cancelaciones de eventos
vinculados generan avisos y sustituyen los recordatorios anteriores.

En calendarios con capacidad mayor que uno:

- Un evento normal consume un cupo.
- Un evento de todo el día o con título que empiece por `[BLOQUEO]` bloquea
  toda la capacidad en ese intervalo.
- Los eventos marcados como libre (`transparent`) no crean bloqueos externos.
  Una reserva del bot sigue consumiendo su cupo hasta cancelarla.

Recepción puede crear una cita en Google: el bot la considera ocupación.
Para que esa cita nueva reciba avisos por WhatsApp y pueda gestionarse desde
el chat, debe vincularse al contacto correcto. No deducir teléfonos a partir
del título del evento. Primera versión: vinculación administrada con la CLI:

```powershell
.\.venv\Scripts\python.exe scripts\agenda_admin.py vincular --conversacion ID --servicio demo --recurso asesor --evento ID_GOOGLE --nombre "Nombre de la persona"
```

La CLI comprueba cuenta y bandeja contra Chatwoot antes de asociar el evento.
Los avisos quedan en cola; el trabajador del webhook los entrega.

**Límites:** Google permite crear manualmente citas superpuestas. El bot
detecta esos conflictos y deja de ofrecer el cupo, pero no puede impedir
escrituras directas de Google. Revisarlos con `agenda_admin.py estado` y los
logs. Reprogramar automáticamente conserva el profesional/calendario; cambiar
de profesional o mover un evento entre calendarios requiere gestión humana.
No hay pantalla de recepción propia en esta etapa.

## Conexión inicial de Google

1. En un proyecto de Google Cloud, habilitar Google Calendar API.
2. Configurar Google Auth Platform: marca, correo, audiencia externa y usuario
   de prueba. Crear un cliente OAuth **Aplicación de escritorio**.
3. Guardar el JSON descargado en `datos/google-oauth.json` (privado e ignorado).
4. Ejecutar, indicando el correo real de la agencia:

   ```powershell
   .\.venv\Scripts\python.exe scripts\conectar_google_agenda.py --credenciales datos/google-oauth.json --correo CORREO_DE_LA_AGENCIA
   ```

5. Autorizar desde el navegador. El retorno usa localhost, `state` y PKCE;
   valida la cuenta Google elegida y guarda el token en `.env.agenda.local`
   sin mostrarlo. La conexión no activa producción.
6. Completar el resto de variables siguiendo `.env.agenda.example`. Si el
   archivo local ya contiene tokens, **no sobrescribirlo con el ejemplo**.
7. Comprobar el estado de publicación de OAuth antes de entregar. Las apps
   externas en Testing emiten refresh tokens de siete días para Calendar.
   Resolver publicación/verificación aplicable; contemplar revocación y reconexión.
   Al 15/09/2026 la app sigue en **Prueba**: «Publicar app» está deshabilitado
   hasta completar la página de marca. Que un token ya emitido en Testing se
   extienda solo al publicar no está documentado: después de publicar, volver
   a ejecutar `conectar_google_agenda.py` para emitir uno nuevo.

Un `403 access_denied` durante la autorización significa que la cuenta no
está en **Usuarios de prueba**, no que falten permisos. Y si `calendar.events`
no aparece en el selector de alcances, falta habilitar Calendar API en ese
proyecto: el recuadro «Agrega permisos manualmente» acepta el alcance, pero
habilitar la API es un paso aparte y sin él las llamadas devuelven 403.

Se solicita `calendar.events` más identidad básica para comprobar la cuenta.
El backend restringe el uso a los calendarios configurados. El perfil de
Smarth House usa `primary`; confirmar su destino en una prueba aislada antes
de activarlo. Un calendario dedicado permite separar citas de asuntos personales.

Documentación: [OAuth Desktop y PKCE](https://developers.google.com/identity/protocols/oauth2/native-app),
[caducidad de tokens](https://developers.google.com/identity/protocols/oauth2#expiration),
[creación e IDs de eventos](https://developers.google.com/workspace/calendar/api/guides/create-events),
[versiones de recursos](https://developers.google.com/workspace/calendar/api/guides/version-resources).

## Plantilla de WhatsApp y recordatorios

Fuera de la ventana de atención no alcanza un mensaje libre: configurar una
plantilla **UTILITY** aprobada y sincronizada en la bandeja de Chatwoot.
Nombre sugerido: `actualizacion_cita`. Idioma inicial: `es`, debe coincidir
exactamente con el aprobado. Cuerpo esperado, con cinco variables:

```text
Actualización de tu cita con {{1}}: {{2}}. Fecha y hora: {{3}}. Referencia: {{4}}. Información: {{5}}.
```

Variables: negocio, estado del aviso, fecha/hora/zona, referencia y enlace o
indicación de contacto. La plantilla se valida en la bandeja real; su nombre
en el `.env` no implica que Meta la haya aprobado.

Configurar `AGENDA_PLANTILLA_WHATSAPP` y `AGENDA_PLANTILLA_IDIOMA` al verificarla.
Sin plantilla, los avisos fuera de ventana quedan bloqueados en la cola.
La propuesta informa que se enviarán recordatorios. La persona puede escribir
`SIN RECORDATORIOS` para desactivarlos o `ACTIVAR RECORDATORIOS` para reactivarlos.
Cancelar recordatorios conserva las citas y sus confirmaciones operativas.

Smarth House programa WhatsApp 24 horas y 30 minutos antes. El aviso de 30 minutos
que muestra Google Calendar es la notificación predeterminada del calendario al
dueño de la cuenta; no es un mensaje de WhatsApp para el contacto. Si una cita
se crea después de la hora prevista para uno de sus avisos, ese aviso pasado no
se programa.

El trabajador adapta los avisos pendientes de citas existentes cuando cambia
la lista de minutos: anula los de una hora y agrega el de 30 minutos si su hora
todavía no pasó. Conserva los registros aceptados o inciertos para no reenviar.
La actualización no recrea eventos ni vuelve a enviar la confirmación inicial.

**Avisos al dueño:** el bot no envía un correo propio al crear una reserva.
La consulta real del 17/09 encontró `popup` a 30 minutos en los recordatorios
predeterminados de `primary`. Las notificaciones de creación se configuran
aparte en Google Calendar; no se pudo leer ni modificar esa preferencia con
el permiso actual (`CalendarList` respondió 403). Ver los pasos y el límite de
verificación en el [incidente del 17/09](agenda-incidente-2026-09-17.md#aviso-al-dueño).

Referencias: [API de mensajes y plantillas de Chatwoot](https://developers.chatwoot.com/api-reference/messages/create-new-message),
[ventana por canal](https://developers.chatwoot.com/self-hosted/supported-features).

## Preparación y despliegue

1. Configurar una base propia para la agenda de Smarth House con rol limitado,
   copia de seguridad y host Docker interno. No cambiar el DSN de la memoria
   existente ni reutilizar sus tablas. `AGENDA_DSN` debe ser PostgreSQL en producción.
2. Probar contra calendario dedicado y bandeja de pruebas, sin prospectos reales.
3. Verificar alta, Meet, cambio, cancelación, sincronización de recepción,
   confirmaciones, recordatorios y entrega de plantillas fuera de ventana.
4. Configurar las variables de agenda solo en runtime en `agente-ia`.
5. Comprobar autodespliegue e historial antes del push. Integrar a `main`
   únicamente el cambio probado y desplegar con `scripts/desplegar.py`,
   indicando `--prompt prompts/smarth_house_portal.md`.
6. Verificar `/salud`, huella de reglas de agenda, comportamiento y envío real.
   Guardar commit, ID de despliegue y alcance de la validación en operación.

El usuario autorizó el despliegue de Smarth House para este trabajo. Los pasos
de conexión de Google y aprobación de Meta son requisitos externos; no
activarlos con valores ficticios ni presentar pruebas simuladas como producción.

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

En la máquina del usuario, Norton re-firma todo el tráfico TLS con una raíz
propia que está en el almacén de Windows pero no en `certifi`. Por eso el
código que usa `urllib` funciona —incluido `calendario_google.py`— y el que
usa `httpx` falla con `CERTIFICATE_VERIFY_FAILED`, lo que alcanza a los
proveedores de IA. En scripts locales que llamen al modelo, empezar con
`import truststore; truststore.inject_into_ssl()`; el paquete ya está en el
entorno. No desactivar la verificación. No afecta al contenedor del VPS.

PostgreSQL opcional: `AGENDA_PROBAR_POSTGRES=1` habilita el contrato de agenda
en la base aislada `catalogos_pruebas`, usando la conexión privada existente
de `.env.portal.local`. Cada prueba usa un negocio aleatorio y limpia solo
sus filas de agenda. No ejecuta migraciones del portal ni borra sus tablas.

La suite prueba cupos simultáneos, aislamiento entre contactos y negocios,
reintentos, recuperación, cambios manuales, plantillas, destinatarios y el
recorrido del webhook sin llamar al proveedor. Los resultados definitivos y
las comprobaciones reales están en [operacion.md](operacion.md) y
[revision-agenda.md](revision-agenda.md).
