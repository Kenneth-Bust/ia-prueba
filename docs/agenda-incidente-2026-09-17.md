# Agenda: corrección del incidente del 17/09/2026

Estado: cambios locales en `correccion/agenda-confirmaciones-hora`, partiendo
de `main` / `01265767e83b84a8c1066e0f0243b70680a255e2`. Pendiente de despliegue.
No se modificaron citas ni se enviaron mensajes a contactos reales.

## Qué mostraron las capturas y qué se encontró

- La persona eligió un rango, «de 3 a 4», y se preparó una cita a las 15:00
  mientras otra respuesta todavía preguntaba entre las 15:00 y las 16:00.
  Se reforzó la instrucción de pedir una hora exacta de inicio y explicitar
  Nicaragua al ofrecerla, sin deducir otro país por el teléfono.
- El primer `CONFIRMAR` aparece con formato. El servidor solo reconocía
  texto plano; el formato lo desviaba al modelo. La normalización nueva
  acepta negrita/cursiva y conserva el control determinista. No autoriza
  negaciones, preguntas, tachados ni mensajes que cambian la hora.
- A las 13:59 la reserva pedía `CONFIRMO ASISTENCIA`; a las 14:00 el aviso de
  una hora repetía esa solicitud. Se eliminó del alta y del aviso de enlace.
  Las 24 horas quedan como aviso informativo; el de 30 minutos solicita
  asistencia solo si sigue pendiente. El formato de plantilla respeta lo mismo.
- Después de las 15:00 el modelo repetía una hora antigua y trataba la
  propuesta como pendiente, aunque el webhook ya había reservado y confirmado
  asistencia. Las confirmaciones se resuelven fuera del modelo y antes no
  actualizaban su contexto. Ahora cada llamada recibe hora real y estado de
  agenda del contacto, incluyendo citas de las últimas 24 horas que terminaron.
  Las consultas a Google siguen siendo necesarias para cupos y cambios manuales.
- La zona leída de Google fue `America/Managua`. No se encontró evidencia de
  una zona equivocada en Calendar: la falla comprobable era el contexto viejo.
- El nombre de quien asiste cambia en una propuesta posterior. Las
  capturas no permiten conocer el contenido de esos audios, así que no se
  atribuye ese cambio a una invención comprobada. El prompt ahora exige una
  indicación clara de la persona para cambiar el nombre.

El aviso de 60 minutos guardado para una cita existente también se sustituye:
no alcanza con cambiar las reglas de citas nuevas. La adaptación conserva
asistencia y reservas, evita reenviar altas y mantiene los envíos inciertos
para conciliación. Si ya pasó la hora del aviso nuevo, no lo agrega tarde.

La mejora incluye el estado visible solicitado para las videollamadas de
Smarth House. Google Calendar muestra `⏳ Agendada` mientras la asistencia está
pendiente y `✅ Confirmada` después de `CONFIRMO ASISTENCIA`; la descripción
separa reserva y asistencia. Reprogramar reinicia la segunda. La conciliación
periódica actualiza también eventos futuros anteriores y reintenta una etiqueta
que Google no haya aceptado, sin duplicar la cita. Las notas manuales de la
descripción se conservan.

## Aviso al dueño

El usuario eligió recibirlo por Google Calendar/correo. El código no tiene un
envío de correo al dueño: crea el evento con `sendUpdates=none`, sin invitados,
y los avisos de la cola van al contacto de WhatsApp.

Lectura real con la conexión local de Google, el 17/09:

- Calendario `primary`: zona `America/Managua`.
- Recordatorios predeterminados: `[{"method": "popup", "minutes": 30}]`.
- Lectura de preferencias `CalendarList`: HTTP 403. El alcance actual permite
  eventos, pero no administrar esas preferencias. No se ampliaron permisos.
- No hubo un navegador disponible para revisar/cambiar el ajuste en la interfaz.

El popup de 30 minutos es un recordatorio previo, no un correo de nueva reserva.
Para habilitar este último, entrar con la cuenta dueña del calendario en Google
Calendar: **Configuración → Configuración de mis calendarios → calendario de
la agencia → Otras notificaciones → Nuevos eventos → Correo electrónico**.
Revisar también eventos modificados y cancelados si se necesitan esos avisos.
En **Notificaciones de eventos** se puede agregar correo a 30 minutos,
conservando el popup. Son ajustes distintos.

Google documenta las notificaciones de creación por correo en
[Recordatorios y notificaciones](https://developers.google.com/workspace/calendar/api/concepts/reminders)
y sus preferencias en
[CalendarList](https://developers.google.com/workspace/calendar/api/v3/reference/calendarList).
Hay que verificar la entrega con una reserva de prueba: no dar por hecho que
el correo llegó por ver el evento o cambiar una preferencia. Si no llega con
la misma cuenta que crea el evento, revisar el comportamiento real y elegir
un destinatario explícito para una integración de correo; no agregar invitados
ni tocar el envío de invitaciones de todos los eventos sin acordar ese alcance.

## Verificación y despliegue

Las regresiones verifican formato de
confirmación, reserva sin segunda petición, aviso a 30 minutos, actualización
de la cola anterior, asistencia ya confirmada, prohibición de avisos pasados,
aislamiento de contactos, caducidad de propuestas y contexto actualizado en el
turno posterior a una confirmación por webhook. También cubren el título y la
descripción visibles, notas manuales, reprogramación y conciliación tras una
falla temporal. Usan modelo y Calendar falsos.

Suite completa: **523 aprobadas y 68 omitidas**, sin consumir tokens. También
se repitieron los archivos de incidente, asistencia y canal: **59 aprobadas y
34 omitidas**. Las omitidas
incluyen contratos de bases aisladas que requieren activación explícita.
Además, los **7 casos del incidente pasaron contra PostgreSQL aislado**
(`catalogos_pruebas`), con negocios temporales y limpieza de sus propias filas.
Los **4 casos nuevos del estado visible** pasaron también en esa base: cambio
de etiqueta, conservación de notas, conciliación después de un rechazo de
Google y reprogramación con un `etag` modificado desde Calendar.
Se comprobó también la serialización local del contexto en los adaptadores
instalados de Gemini y Claude, sin llamadas al proveedor y conservando el
marcador de caché únicamente en las reglas estáticas.

Lectura de Coolify y `/salud`: `agente-ia`, rama `main`, `running:healthy`,
agenda habilitada y confirmación simple. Autodespliegue activado. Las huellas
siguen siendo las anteriores: prompt `fa5af023…` y reglas `5e7c3e8e…`.
No se hizo push ni se inició un despliegue con esta corrección.

Antes de desplegar: revisar el diff, correr la suite, comprobar autodespliegue
e historial y seguir `docs/despliegue.md`. No borrar memorias ni cancelar citas
del incidente. Después de desplegar, comprobar reglas `[1440, 30]` y hacer un
recorrido con un contacto de prueba, incluyendo la entrega del correo al dueño.
La plantilla UTILITY sigue siendo necesaria fuera de la ventana de WhatsApp.
