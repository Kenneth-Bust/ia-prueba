# Propuesta: citas por WhatsApp y Google Calendar

## Estado y alcance

Revisión inicial del 15/09/2026 sobre `9bf6a89`, rama
`mantenimiento/ordenar-prompts-documentacion`. **La propuesta inicial de abajo
dio paso a una implementación local en `funcionalidad/agenda-google-calendar`.**
Estado y operación de esa implementación en [agenda.md](agenda.md).
Se revisaron el agente, las herramientas, la configuración, el webhook,
Chatwoot, el modelo del portal y la documentación operativa. No se accedió
al calendario del cliente ni se modificó producción.

Necesidades transmitidas por el usuario:

- Agendar citas automáticamente.
- Cancelarlas y reprogramarlas.
- Enviar mensajes de confirmación.
- Admitir unos cuatro pacientes cada media hora.

El usuario autorizó después implementar primero las videollamadas de Smarth
House y dejar una base reutilizable para una clínica mediana. Aprobó atención
de lunes a sábado, de 08:00 a 17:30, videollamadas de 30 minutos, una a la vez,
y recordatorios de 24 horas y una hora. Indicó la cuenta Google de la agencia
en la conversación. Recepción también podrá crear y mover citas en Google.
El ejemplo clínico contempla cuatro profesionales, cada uno con capacidad 1;
todavía necesita validación y datos reales antes de incorporar ese cliente.

## Qué se puede reutilizar y qué falta

| Pieza revisada | Hallazgo y consecuencia |
|---|---|
| `src/agente/herramientas.py`, `herramientas_para()` | Ya selecciona herramientas por bot. La agenda debe habilitarse por configuración. El retorno anticipado al habilitar portal debe reorganizarse para permitir portal y agenda juntos. |
| `src/agente/agente.py`, `_construir_grafo()` | Ya ejecuta herramientas. Se conserva el ciclo; hay que pasar la configuración y el contexto confiable de las operaciones. |
| `src/agente/agente.py`, `_invocar_con_reintentos()` | Reintenta el grafo completo ante ciertos errores. Una cita creada antes de fallar la respuesta no debe volver a crearse. |
| `src/agente/web/webhook.py` | Tiene un candado por conversación. No protege un cupo solicitado desde dos conversaciones distintas. |
| `src/agente/canales/chatwoot.py` | Filtra cuenta/bandeja y duplicados recientes en memoria. Esa protección no sustituye un registro persistente de reservas y operaciones. |
| `src/agente/canales/base.py` y webhook | Llega el identificador del mensaje, pero hoy el buffer entrega texto, conversación y adjuntos al agente. Hay que conservar el contexto necesario para identificar operaciones y contactos sin pedírselo al modelo. |
| `src/portal/modelo.py` | Los horarios publicados son texto. Faltan horarios estructurados, duración, recursos y capacidad para calcular disponibilidad. |
| `src/agente/portal.py`, `REGLA_CATALOGO` | Remite disponibilidad y horarios al portal. Al combinar módulos, distinguir disponibilidad comercial de cupos de agenda y confirmar reservas únicamente desde un resultado efectivo de la agenda. |
| `docs/portal.md` | La agenda está expresamente pendiente como módulo separado del catálogo. |
| `prompts/smarth_house_portal.md` | Declara que el bot no tiene agenda. El nuevo negocio necesita prompt propio y herramientas reales; editar este prompt no implementa la función. |

## Diseño recomendado

```text
Paciente → WhatsApp → Chatwoot → agente
                                  ↓
                         herramientas de agenda
                                  ↓
                     reglas y reservas en PostgreSQL
                                  ↕
                           Google Calendar
                                  ↓
                    confirmación por Chatwoot
```

El agente interpreta la solicitud. El módulo de agenda valida las reglas,
identifica la cita y ejecuta el cambio. PostgreSQL mantiene los cupos y
las operaciones; Google Calendar muestra los eventos al equipo. La memoria
de conversación no es la fuente de disponibilidad.

Se reutiliza el código común, con aplicación, cuenta/bandeja, credenciales,
prompt y datos propios del cliente según `metodologia-clientes.md`.
La agenda queda apagada en los bots que no la configuren. No requiere
conectar este cliente a la memoria o al calendario de Smarth House.

### Cuatro pacientes por bloque

Si son cupos compartidos, un bloque de 09:00 a 09:30 admite cuatro reservas
activas. Con tres pacientes queda un cupo; con cuatro se ofrecen otros
horarios. Cada paciente tiene su propia cita y evento, para poder cancelar
o mover uno sin afectar a los demás. No agrupar pacientes como invitados
de un mismo evento.

Si son cuatro profesionales, se controla la disponibilidad de cada uno y
qué servicios atiende. El total de cuatro no autoriza a asignar dos
pacientes simultáneos al mismo profesional.

Google devuelve intervalos ocupados mediante
[FreeBusy](https://developers.google.com/workspace/calendar/api/v3/reference/freebusy/query).
Eso no equivale a contar cupos: marcar todo el bloque como lleno por su
primer evento rechazaría los otros tres pacientes. Usar reglas de capacidad
en el backend; FreeBusy puede servir para bloqueos de calendarios externos.

La capacidad debe validarse y reservarse de forma atómica en PostgreSQL:
dos solicitudes simultáneas no pueden apropiarse del último cupo. Tanto
reservas confirmadas como operaciones pendientes que consuman capacidad
cuentan para el límite. Si varias bandejas usan la misma agenda, comparten
este control aunque sus memorias conversacionales sean independientes.

### Herramientas propuestas

| Herramienta | Resultado esperado |
|---|---|
| `consultar_disponibilidad` | Horarios con cupos para el servicio y recurso permitidos. |
| `consultar_mis_citas` | Solo las citas asociadas al contacto autorizado. |
| `agendar_cita` | Reserva validada, evento registrado y referencia de cita. |
| `cancelar_cita` | Cancela la cita elegida y libera el cupo cuando se confirma el cambio. |
| `reprogramar_cita` | Valida el destino y mueve la cita conservando su referencia. |

Cliente, contacto, calendario y permisos se resuelven en el servidor. El
modelo no puede elegir otra cuenta o enviar un ID arbitrario para cancelar
citas ajenas. Asociar reservas al contacto verificado, no únicamente al
`thread_id`, porque puede abrirse una conversación nueva. Familiares que
agendan desde el mismo teléfono requieren una regla acordada con el negocio.

## Comportamiento necesario

- **Reserva:** pedir únicamente los datos que falten; proponer horarios
  reales; obtener una elección inequívoca; registrar y confirmar fecha,
  hora, zona horaria, sede y referencia. Una consulta de disponibilidad
  no equivale a autorizar una reserva.
- **Cancelación:** identificar la cita y la intención de cancelarla. Si hay
  varias, preguntar cuál. Conservar su historial y liberar capacidad una
  sola vez; no borrar mensajes de Chatwoot.
- **Reprogramación:** asegurar capacidad en destino antes de liberar el
  origen. Actualizar el evento existente y finalizar el movimiento. Si el
  resultado de Google es incierto, mantener los cupos protegidos y conciliar
  el estado antes de confirmar o liberar. Un fallo conocido conserva la
  cita original.
- **Fechas:** reglas estructuradas para días, horarios, cierres, anticipación,
  duración y separación entre citas. Resolver “mañana” usando la fecha
  actual y la zona del negocio. No interpretar horarios ambiguos sin aclarar.
- **Reintentos:** registro persistente de operación y un ID de evento
  estable por reserva. Google permite
  [asignar el ID al crear el evento](https://developers.google.com/workspace/calendar/api/guides/create-events)
  para recuperar una creación que tuvo éxito aunque la respuesta se perdiera.
  Repetir un mensaje o reiniciar el bot no debe crear otra cita.
- **Errores:** distinguir ocupado, falta de autorización y resultado
  incierto. No anunciar una cita confirmada sin resultado verificable.
  Registrar operaciones pendientes para retomarlas tras una caída.
- **Confirmaciones:** enviar por Chatwoot tras el resultado efectivo. Guardar
  el estado de envío separado del estado de la cita; un fallo al enviar
  WhatsApp no vuelve a ejecutar la reserva. Si el envío es incierto,
  comprobarlo antes de repetirlo.
- **Datos del paciente:** guardar solo lo necesario para la agenda. Evitar
  diagnósticos e historias clínicas en eventos, prompts o registros. No
  devolver nombres ni citas de otros pacientes al consultar disponibilidad.

La API permite
[crear](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert),
[modificar](https://developers.google.com/workspace/calendar/api/v3/reference/events/patch)
y [eliminar eventos](https://developers.google.com/workspace/calendar/api/v3/reference/events/delete).
Las operaciones entre PostgreSQL, Google y Chatwoot no forman una sola
transacción: necesitan estados persistentes y recuperación, no solo tres
llamadas HTTP seguidas.

### Cambios manuales desde Google Calendar

Hay que acordar si recepción también cargará o moverá citas directamente
en Google. Si lo necesita, incluir importación inicial, seguimiento de
altas/cambios/cancelaciones y reglas para distinguir citas de bloqueos.
Google documenta la
[sincronización incremental](https://developers.google.com/workspace/calendar/api/guides/sync)
y el [control de versiones](https://developers.google.com/workspace/calendar/api/guides/version-resources)
para detectar cambios antes de sobrescribir un evento.

La sincronización no impide que alguien cree manualmente una quinta cita
en Google. Para garantizar el límite, todas las altas deben pasar por el
control de cupos; si se permiten ediciones externas, hacen falta detección
de conflictos y resolución por recepción. No prometer protección absoluta
frente a modificaciones externas concurrentes.

### Conexión con Google y mensajes

Propuesta inicial: calendario dedicado del negocio y autorización OAuth
del dueño con acceso offline para el servidor. Los permisos solicitados
deben limitarse a las operaciones necesarias y el backend debe restringir
los calendarios autorizados. Los secretos se leen desde `config.py` y se
almacenan fuera de Git; nunca se piden contraseñas de Google en el chat.
Ver [OAuth para servidores](https://developers.google.com/identity/protocols/oauth2/web-server).

Antes de operar, comprobar configuración de publicación y requisitos de
verificación de OAuth. Para apps externas en estado Testing, los permisos
de Calendar están sujetos al refresh token de siete días documentado por
[Google](https://developers.google.com/identity/protocols/oauth2#expiration).
También hace falta detectar revocación de acceso y permitir reconexión.

Confirmar por WhatsApp una reserva, cambio o cancelación forma parte del
alcance solicitado. Recordatorios futuros y mensajes para preguntar si el
paciente asistirá son funciones adicionales por definir: requieren tareas
persistentes y revisar las condiciones vigentes del canal antes de enviar.
Los avisos de Google Calendar no sustituyen mensajes de WhatsApp.

## Archivos previstos al implementar

- `src/agente/agenda.py`: herramientas y reglas de las operaciones.
- `src/agente/calendario_google.py`: conexión con la API de Google.
- `src/agente/repositorio_agenda.py`: persistencia de citas, cupos,
  operaciones y envíos pendientes; migraciones separadas del checkpointer.
- `src/agente/config.py` y `.env.example`: activación y configuración.
- `src/agente/herramientas.py` y `src/agente/agente.py`: registro opcional
  y paso de contexto confiable sin rehacer el grafo.
- Reglas del portal y del prompt: separar horarios informativos del negocio
  y disponibilidad de citas cuando se habilite agenda.
- Canal, buffer y webhook: conservar identificadores y contexto autorizado
  de las solicitudes; recuperar operaciones y confirmaciones pendientes.
- Prompt propio del cliente y pruebas de agenda.

Son nombres propuestos: ninguno de los módulos nuevos existe por esta
revisión. No agregar controles a `AJUSTABLES` ni publicar secretos en el
portal. La primera configuración puede ser administrada; una pantalla de
agenda en el portal se evalúa como otra etapa.

## Pruebas y entrega propuestas

1. Reglas con modelos y Calendar falsos: cuatro reservas admitidas y quinta
   rechazada; solicitudes simultáneas por el último cupo; cancelación
   repetida; reprogramación sin cupo; fechas y cierres.
2. Persistencia real de prueba: reinicios, mensajes repetidos, error del
   modelo después de crear el evento, timeout de Google y recuperación.
3. Aislamiento: contacto o negocio ajeno no puede leer ni modificar citas;
   agenda desactivada no altera los otros bots; portal y agenda conviven.
4. Calendario y Chatwoot aislados: alta, cancelación, reprogramación y
   confirmaciones; comprobar cambios manuales si se incluyen.
5. Alta del cliente y despliegue específico una vez definido y probado el
   alcance, siguiendo operación y metodología. Comprobar autodespliegue
   antes de subir cambios a ramas desplegadas.

## Decisiones pendientes del cliente

- Cuatro cupos compartidos o cuatro profesionales; duración real de citas.
- Servicios, sede, zona horaria, días, horarios y cierres.
- Datos mínimos del paciente y citas de familiares desde un teléfono.
- Anticipación y límites para reservar, cancelar y cambiar.
- Si recepción seguirá editando el calendario directamente.
- Confirmación inmediata, recordatorios o solicitud posterior de asistencia.
- Cuenta Google del negocio, calendario de prueba y responsable del acceso.

## Evidencia de la revisión inicial

- Implementado: solamente este documento y su enlace en el índice.
- Verificación: revisión estática del código y documentación oficial de Google.
- Tests de ejecución: no realizados; no se modificó código ejecutable.
- Google/Chatwoot/Coolify: sin cambios, sin mensajes enviados, sin despliegue.
- No hay recursos creados ni credenciales registradas para este cliente.

La sección anterior describe exclusivamente la revisión inicial. Para el
desarrollo posterior, pruebas y requisitos de activación, consultar
[agenda.md](agenda.md). No interpretar el código local como un despliegue.
