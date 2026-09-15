# Smarth House: catálogo conectado y respuestas breves

Registro del **14/09/2026, hora de Nicaragua** (las operaciones posteriores
a las 18:00 aparecen como 15/09 en UTC). Sustituye los pendientes de
[la revisión previa](revision-portal-smarth-house.md). El usuario autorizó
continuar hasta dejar la actualización funcionando, y después pidió reducir
las respuestas del bot y revisar el aviso de seguridad de Coolify.

## Qué corre ahora

| Aplicación | Revisión desplegada | Despliegue de Coolify |
|---|---|---|
| agente-ia: integración inicial | `45bdb54368dd63761ab04784b289bc47a543f54c` | `ispbjxswherbpqcqpy8kbhcc` |
| agente-ia: conversación breve | `aed3a697d57fb01b95ffeb90b2c4efa1dada3f73` | `r36z1nw75tsfvys4ykmz98m9` |
| portal-catalogos | `45bdb54368dd63761ab04784b289bc47a543f54c` | `oh23cd5hq4gdsuvswowmn2gl` |

Los despliegues indicados terminaron en `finished`, con salud pública
verificada. Los commits posteriores que solo documenten estas operaciones
no necesitan otro despliegue.

`agente-ia` ejecuta `main`, con
`PROMPT_SISTEMA=prompts/smarth_house_portal.md`, `PORTAL_NEGOCIO_ID=smarth-house`
y la clave de lectura ya existente. No recrearla. `PORTAL_LINEA`,
`CATALOGO_RUTA` y `PROMOCIONES_RUTA` están vacíos. Cuenta y bandeja de
Chatwoot: **1 y 1**, con filtros activos. La memoria conserva su DSN y sus
`thread_id`; no se borraron conversaciones ni se modificaron etiquetas de
prospectos. Buffer 5 s, mínimo de respuesta 15 s y ritmo humano activado.

El prompt anterior `prompts/sistema.md` se conserva igual que en `44bc631`
para referencia y reversión. **Editar ese archivo ya no cambia el bot de
Smarth House.** El prompt del portal contiene conducta y política comercial;
los precios, vigencias y beneficios del plan salen de la publicación.

`bot-demo` y `piloto-demo` se conservaron. El contenedor del piloto sigue
ejecutando `922dc11db114bafa37610dda6d984a03b9a9d414`; la referencia Git
`e36ac7371380087f5022d3c3685047cde3a7520e` incluye documentación posterior.
No conectar los números del prospecto de uniformes por interpretar esta
migración de la agencia como autorización para su alta.

## Oferta y conversación

La versión 4 del portal sigue ofreciendo PLAN-1, tipo Promoción, **US$45 al
mes por número de WhatsApp**, hasta el 11/10/2026 inclusive. Incluye hasta
1.000 conversaciones mensuales, CRM, app móvil, soporte y capacitación;
la conservación de tarifa tiene las condiciones aprobadas en la descripción.
No hay plan regular publicado ni cotización automática habilitada para este
ítem: el equipo confirma tarifas posteriores y propuestas para varios números.

El ajuste de conversación usa este recorrido:

- Saludo: respuesta corta, sin oferta automática.
- “Cómo funciona”, aunque llegue de un anuncio: explicación breve y pregunta
  del rubro si falta; no acumula precio, foto y cierre comercial.
- Precio: consulta el portal sin adjuntar foto, informa importe, unidad,
  límite, vigencia y hasta dos beneficios.
- Promociones disponibles o solicitud de imagen: foto registrada y texto
  breve. Las repreguntas consultan datos sin repetir la imagen.
- Aceptación de demo: conserva exactamente “Perfecto, te paso con una persona
  del equipo y te escribe por aquí mismo.” La automatización existente de
  Chatwoot asigna al equipo y aplica `humano`.

Instalación y contratación siguen con el asesor. No se introdujeron tarifas
futuras, aumentos, cupos, servidores nuevos ni vencimientos anticipados.
Una nueva publicación cambia las condiciones consultadas, sin modificar
acuerdos o cotizaciones históricas. **Si cambia un precio que está dibujado
en una foto, hay que actualizar también esa foto y publicar ambos cambios.**
El bot no reescribe ni interpreta la imagen del catálogo para corregirla.

## Comprobaciones

- Suite completa antes del despliegue inicial: **405 aprobadas, 8 omitidas**
  (contrato PostgreSQL opcional), una advertencia existente de Starlette.
  Las ocho pruebas de PostgreSQL ya habían pasado en `catalogos_pruebas`
  durante la revisión anterior. Los tests usan modelos falsos.
- El comando de despliegue volvió a ejecutar la suite del ajuste de
  conversación: **405 aprobadas, 8 omitidas, una advertencia**, en 132,97 s.
- Imagen Docker construida en el VPS y prueba completa aislada con Gemini,
  publicación real, memoria SQLite propia y Chatwoot cuenta 2, bandeja API
  **3**, conversación **5**. Verificó promoción, precio antiguo corregido,
  cotización de dos números derivada y frase exacta de traspaso. La foto del
  mensaje 518, adjunto 19, coincide byte por byte con el portal.
- El webhook temporal fue retirado y el contenedor de prueba eliminado al
  terminar; la demo de uniformes nunca fue sustituida. Se conservó la
  conversación sintética como evidencia. La protección SSRF de Chatwoot
  rechazó inicialmente la URL interna: se usó una ruta HTTPS temporal sin
  desactivar esa protección. No repetir el intento fallido ni los envíos.
- Diez turnos manuales con Gemini y memoria RAM aislada probaron el ajuste
  de brevedad. La consulta de anuncio de la captura produjo **48 palabras,
  sin foto ni precio**; la de promociones produjo **36 palabras y una foto**;
  precio y beneficios consultaron `ver_catalogo` sin adjuntos. La aceptación
  de demo conservó la frase exacta. No enviaron mensajes a Chatwoot.
- En las dos conversaciones señaladas por el usuario, **34 y 35 de cuenta
  1**, la API confirma imágenes **leídas** (mensajes 568/588, adjuntos 26/27).
  Es evidencia de entrega por WhatsApp de la integración inicial. Solo se
  consultaron esos chats; no se les enviaron mensajes de prueba.
- El WhatsApp propio identificado por el usuario ya probó la integración
  inicial en conversación **3**. Sus respuestas de texto figuran entregadas;
  su foto figuraba `sent` al consultar. La prueba de la redacción breve
  después del segundo despliegue queda pendiente: el usuario respondió
  **“Lo probaré después”**. No confundir las pruebas iniciales con la revisión
  posterior del prompt ni enviar mensajes por su cuenta para reemplazarla.

Huella del prompt después del ajuste: `1f32fe5efcd5b56552c392839c2c551ba21867c7c80e8ce9b718c9b39f1ea3f2`.
Huella de `REGLA_CATALOGO`: `65deb39cd50609b4bd9c4f497148f9602d3e70b05b9b56ab7995184c2bdb7a54`.
`/salud` devuelve `catalogo_fuente: portal`; esto identifica configuración,
no sustituye una consulta funcional al portal.

Después del despliegue breve, una lectura de herramientas dentro del
contenedor de agente-ia confirmó versión 4, US$45 y un adjunto del portal,
sin enviar mensajes al CRM. También se comprobó que sus variables runtime
coincidieran con la configuración aprobada y que portal y demo siguieran sanos.

El modelo decide cuándo llamar las herramientas: el prompt exige consultar
en el turno actual. Se comprobó en los casos descritos, sin prometer que una
IA nunca repetirá información antigua. Si ocurre, investigar la respuesta
y la herramienta usada; no borrar todas las memorias.

## Persistencia corregida y respaldos

**Se corrigió una afirmación anterior de la documentación:** el contenedor
original del portal no tenía montajes (`Mounts=[]`), aunque los documentos
decían que usaba un volumen Docker. Antes de reiniciarlo se copiaron y
verificaron las dos fotografías.

Ahora Coolify registra almacenamiento persistente `vejadtccuy4zeox0ztodvxgk`:

```text
Tipo: bind mount
Host: /data/coolify/applications/vhvndsnvosry83dqlztwontm/catalogo-fotos
Contenedor: /app/datos/portal
```

Se verificó el montaje real en el contenedor nuevo, la publicación v4 y
la foto tras el despliegue. Los dos archivos tienen la misma huella:
`5eaabf3d9eccf50aea57b504d463b21de075a2056de74288ddd9da47d1d71364`.
Los registros duplicados no se borraron. La selección sigue usando la primera
foto del ítem. Esto persiste entre despliegues, pero comparte el disco del VPS.

Respaldos manuales: `/data/coolify/backups/manual-smarth-20260914/`, con
copia descargada y verificada en `datos/despliegue-smarth-20260914/` de esta PC:

| Archivo | Bytes | SHA-256 |
|---|---:|---|
| postgres.dump | 2420253 | `08dab3e06bea099b16b6affccb772e2269c37db9f9c04a43859d429700567870` |
| catalogos.dump | 28766 | `c5bb0139073f2feafbf24545ea9a968a6abddb8a39039b704780f421dc31c646` |
| fotos.tar.gz | 3020432 | `5d7b897814c70d9644401a9f3699acb394e0f49e76854c81747839be867e40fa` |

Ambos dumps se restauraron en bases temporales. Los conteos coinciden:
249 checkpoints, blobs y writes; portal con 1 negocio, 1 ítem, 2 fotos y
4 publicaciones, además de usuarios, accesos y registros. El checkpointer
del código nuevo pudo leer tres estados restaurados. Se verificaron también
los bytes del archivo de fotografías. Las bases temporales se retiraron;
los respaldos y las bases originales se conservaron.

La memoria de producción sigue usando el superusuario `postgres`. Se dejó
pendiente una migración específica a permisos limitados, con historial
conservado. No afirmar aislamiento por mínimos privilegios que aún no existe.
También faltan respaldos **automáticos y periódicos fuera del VPS**: esta
copia manual no los reemplaza. No se realizó una prueba de carga.

## Coolify, secretos y continuidad

El acceso correcto es **https://appcoolify.automaticnic.online**. Se verificó
HTTPS y el certificado de origen Let’s Encrypt, válido hasta el 07/12/2026.
HTTP por dominio redirige a HTTPS. `http://2.25.112.244:8000` permanece en HTTP
y por eso el navegador dice “No es seguro”. No se cambió el firewall ni se
bloqueó ese acceso durante la campaña.

Las cinco variables sensibles del bot (proveedor, Postgres, Chatwoot,
secreto del webhook y clave del portal) quedaron habilitadas solo en tiempo
de ejecución, excluidas de la construcción de la imagen. No se publican
valores ni archivos locales de acceso.

El autodespliegue de `agente-ia` se pausó durante los pushes y despliegues
controlados, y se restauró a su valor original activado al finalizar.
Portal y demo permanecen con autodespliegue desactivado. Antes de un próximo
push o despliegue, verificar estos indicadores y el historial real.

Para continuar desde otra PC: actualizar Git y leer AGENTS, operación y este
registro. Las credenciales y los respaldos privados **no viajan en Git**.
No recrear la clave `agente-ia-portal`, la aplicación, el almacenamiento o las
cuentas ya existentes. Para desplegar el bot, indicar siempre:

```text
python scripts/desplegar.py desplegar --prompt prompts/smarth_house_portal.md
```

Si ya hay un despliegue iniciado, usar `estado` con su ID, commit y `--prompt`
en vez de iniciar otro. Una reversión debe restaurar una combinación coherente
de código, prompt y variables; conservar memoria, publicación y fotos.
Los respaldos privados incluyen la configuración anterior para esa revisión.

Para otro negocio se reutiliza el código común, con alta en el portal, clave
propia, publicación, aplicación del bot, cuenta/bandeja y memoria con permisos
propios. El alta sigue siendo administrada; el portal no configura WhatsApp
ni Coolify automáticamente. Las restricciones de borrado de Chatwoot del
prospecto de uniformes siguen pendientes de probar en un entorno aislado.
