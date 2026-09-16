# Revisión de agenda de Smarth House y base clínica — 15/09/2026

## Resultado

**Confirmación sencilla desplegada en Smarth House**: commit `c0a6b3c`,
despliegue `hygjskxg6qw9ouywegefacj5`, finalizado y comprobado con
`running:healthy`. La salud pública informa `agenda_confirmacion: simple`.
El recorrido real debe repetirse desde WhatsApp respondiendo únicamente
`CONFIRMAR`; no se enviaron mensajes automáticos a contactos durante el cambio.

**Correcciones desplegadas en Smarth House**: commit `eeab1fe`, despliegue
`7athnkohguvmz0whcowisnug`, finalizado y comprobado con `running:healthy`.
La salud pública informa `agenda_asistencia: habilitada`. La prueba funcional
completa desde WhatsApp sigue pendiente del usuario.

Validación más reciente: **492 pruebas aprobadas, 50 omitidas** en la suite completa; las
omitidas corresponden a integraciones optativas. Además, **12 pruebas de
agenda seleccionadas aprobadas en PostgreSQL aislado**, incluida concurrencia
de cinco solicitudes para cuatro cupos. El caso final de duración y límite
compartido se volvió a comprobar en PostgreSQL tras optimizar la consulta.
La lectura del Google Calendar autorizado también respondió correctamente.
Cinco casos críticos de la confirmación sencilla pasaron también en PostgreSQL
aislado: última propuesta, aislamiento entre contactos, idempotencia,
confirmación de asistencia y cancelación segura.

La base implementada permite reservar, reprogramar y cancelar en Google
Calendar. Mantiene las operaciones pendientes y los avisos en almacenamiento
persistente, verifica el contacto y vuelve a comprobar los cupos al reservar.
Smarth House conserva videollamadas de 30 minutos, una a la vez, de lunes a
sábado entre 08:00 y 17:30, hora de Nicaragua.

La revisión encontró y corrigió estos puntos:

1. **Reserva y asistencia eran el mismo estado.** Ahora una reserva completada
   se muestra como `agendada`, con `asistencia: pendiente`. Solo el mensaje
   `CONFIRMO ASISTENCIA` del contacto correspondiente confirma su asistencia.
   El modelo puede solicitar ese paso, pero no ejecutarlo. Repetirlo no crea
   otra cita. Las reservas anteriores se consideran sin asistencia confirmada.
2. **Faltaba un límite propio del tratamiento.** El campo opcional
   `capacidad_simultanea` limita ese servicio entre todos sus profesionales,
   además de respetar la capacidad individual de cada recurso. Sin el campo,
   sigue funcionando la capacidad de los recursos existente.
3. **Un cambio pendiente con horarios superpuestos contaba dos veces a la
   misma persona.** Ahora protege la unión de ambos intervalos con un cupo.
4. **Cambiar la duración después de proponer una reserva podía conservar la
   duración anterior.** Ahora exige renovar esa propuesta antes de confirmar.

El estado interno histórico `confirmada` sigue significando reserva completada
para conservar compatibilidad con los datos existentes. La asistencia se guarda
aparte y se consulta con las herramientas del bot o la CLI de recepción. No es
un registro de llegada física ni se infiere del `status` de Google Calendar.
Tampoco se refleja como aceptación de un invitado de Google: no se recoge su
correo ni se envían invitaciones de Calendar.

Al mover la cita desde el bot o Google, se reinician la asistencia y su código;
el código anterior deja de servir. La llegada posterior del enlace de Meet no
borra una asistencia ya confirmada. Los recordatorios usan el estado vigente.

## Cupos y tratamientos: ejemplo verificable

`agendas/clinica_ejemplo.json` contiene datos ficticios:

| Servicio | Duración | Máximo simultáneo | Profesionales elegibles |
|---|---|---|---|
| Consulta | 30 minutos | 4 | Cuatro, con un paciente por profesional |
| Tratamiento largo | 60 minutos | 2 | Los mismos cuatro |

Cuatro consultas a las 09:00 liberan esos recursos a las 09:30. Un tratamiento
de una hora ocupa su recurso hasta las 10:00: no permite agregar otro paciente
a ese profesional a las 09:30. Un tratamiento puede limitarse a determinados
profesionales mediante `recursos`.

Disponibilidad informa `cupos` por recurso y `cupos_totales_horario` para el
servicio. Este último es un total compartido; no sumar las alternativas cuando
hay un límite del tratamiento. La consulta del horario es orientativa: la
transacción de confirmación decide el cupo definitivo.

Un evento manual sin vincular bloquea el recurso; como no se conoce su servicio,
también consume conservadoramente el límite de los tratamientos que usan ese
recurso. Recepción debe vincularlo al servicio y contacto reales para clasificarlo.
Google permite crear eventos superpuestos manualmente: el bot los detecta y
deja de ofrecer cupos, pero no puede impedir que recepción los cree en Google.

## Recepción

Puede mover y cancelar citas desde Google Calendar. Las altas manuales que
necesiten avisos por WhatsApp se vinculan con `agenda_admin.py vincular`.
No hay una pantalla de recepción propia. Para consultar asistencia:

```powershell
python scripts/agenda_admin.py estado
python scripts/agenda_admin.py citas --fecha 2026-09-22
```

Estos comandos leen la conexión local elegida; no necesariamente la base de
producción. Para otro negocio, `--negocio NEGOCIO` va antes del subcomando.
`citas` muestra nombres y referencias: es una consulta para el equipo autorizado.
Lee el estado persistido; el trabajador del bot mantiene la sincronización,
o se puede ejecutar `sincronizar` antes de consultar una base local.

## Prueba real de Smarth House

1. Desde tu WhatsApp de prueba escribí: “Quiero agendar una videollamada para
   mañana”. Elegí un horario disponible y proporcioná tu nombre.
2. Respondé `CONFIRMAR`, sin copiar códigos. Antes de ese mensaje solo hay una
   propuesta; aún no existe la reserva.
3. Comprobá el evento en el calendario de la agencia y el enlace de Google Meet.
4. Mandá `CONFIRMO ASISTENCIA` y luego “¿Cómo está mi cita?”. Debe
   mostrar reserva agendada y asistencia confirmada.
5. Pedí reprogramarla, respondé otra vez `CONFIRMAR` y comprobá que el mismo evento
   cambie de horario; la asistencia debe volver a pendiente.
6. Pedí cancelarla y confirmá. Debe desaparecer del calendario activo y no
   mantener recordatorios pendientes de esa reserva.

Si tu conversación está tomada por una persona o tiene la etiqueta `humano`,
el bot respeta esa condición y no responde. La prueba necesita un contacto de
prueba con el bot habilitado. No borrar conversaciones ni memorias para probar.

## Lo que aún impide dar por terminada la entrega clínica

- **WhatsApp real de extremo a extremo:** falta la prueba del usuario descrita
  arriba. Un `/salud` correcto y los tests con HTTP falso no prueban la entrega.
- **Recordatorios fuera de la ventana de atención:** falta aprobar/configurar
  la plantilla UTILITY. Sin ella, los avisos quedan bloqueados cuando Chatwoot
  no permite responder; esto también puede afectar otros avisos tardíos.
- **OAuth:** las notas locales indican que la app pasó a producción, pero el
  token se emitió en modo de prueba. Hay que completar/revisar su renovación;
  una lectura exitosa hoy no garantiza la vigencia futura del token.
- **Alta del cliente:** confirmar tratamientos, duraciones, recursos y límites
  reales; autorizar su Google, configurar calendarios, cuenta/bandeja, aplicación
  y base aisladas. El ejemplo clínico no es una configuración aprobada por él.
- **Operación:** siguen pendientes los respaldos periódicos fuera del VPS,
  documentados en `operacion.md`.

La base sirve para el piloto de Smarth House y para configurar la clínica.
No equivale a una clínica ya conectada ni a una entrega operativa completa.

## Confirmación sencilla para WhatsApp

El usuario no copia identificadores. Después del resumen de una alta,
reprogramación o cancelación responde `CONFIRMAR`. También se aceptan
`CONFIRMO` y `SÍ, CONFIRMO`. El servidor recupera la última propuesta asociada
a esa conversación y al contacto verificado, comprueba que no venció y vuelve
a validar el cupo antes de escribir en Google. Repetir la respuesta no duplica
el evento. Una conversación distinta no puede confirmar esa propuesta.

Las referencias técnicas permanecen en PostgreSQL y en la descripción privada
del evento para conciliación; no aparecen en los mensajes normales ni en los
recordatorios. Los códigos anteriores siguen siendo aceptados de forma interna
para terminar conversaciones iniciadas antes de este cambio.

Referencias: [estados de eventos y respuestas de invitados en Google](https://developers.google.com/workspace/calendar/api/v3/reference/events),
[ventana de WhatsApp en Chatwoot](https://developers.chatwoot.com/self-hosted/supported-features)
y [caducidad de tokens OAuth de Google](https://developers.google.com/identity/protocols/oauth2#expiration).
