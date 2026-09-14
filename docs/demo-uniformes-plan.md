# Demo de uniformes y sublimación — plan y contexto de continuidad

Actualizado: **14/09/2026**. Objetivo de presentación: **15/09/2026**, según
el pedido del dueño. Este documento es un plan: **la nueva demo todavía no
está implementada ni desplegada**. No interpretar la fecha como una promesa
de entrega o una prueba de funcionamiento.

## 1. Pedido confirmado y alcance

El prospecto tiene un negocio de sublimación y uniformes deportivos. Está
interesado en ver una demo antes de confirmar la contratación.

Requisitos confirmados y propuesta para organizar la demo:

- Trabajar en la rama existente **`piloto-demo`**, no crear otra rama para
  esta demo ni modificar el bot de la campaña en `main`.
- Inventar por ahora la marca, el catálogo, los precios y las imágenes.
  Todo debe identificarse como ficticio; no son tarifas del prospecto.
- Combinar productos con tarifas definidas y trabajos a medida que evalúa
  una persona. Las fotos son imágenes de catálogo, no un generador de
  diseños personalizados con el logo del comprador.
- El cliente usará **dos números nuevos** cuando confirme. La demo inicial
  simula dos líneas con bandejas API; no hay que comprar ni registrar
  números de WhatsApp para presentarla.
- Un administrador para el dueño dentro de su equipo y empleados con rol
  Agente. El usuario confirmó que deben tener prohibido borrar **tanto
  conversaciones completas como mensajes individuales**.
- El bloqueo de edición de teléfonos y contactos no es requisito de esta
  primera versión. No expandir ese alcance por la lista anterior del chat.
- La solicitud de esta etapa es **entregar el plan y guardarlo para otro
  agente**. La implementación, generación de imágenes y creación de
  servicios se ejecutarán en la etapa siguiente.

No incluye pagos, pedidos reales, facturación fiscal, inventario en tiempo
real, una agenda de llamadas ni promesas de entrega de prendas.

## 2. Punto de partida comprobado

| Recurso | Estado conocido al preparar el plan |
|---|---|
| Repositorio | `Kenneth-Bust/ia-prueba`, público |
| `main` en GitHub | `44bc631a3b33c406fab5f3fe0c34476c2febb90a` |
| `piloto-demo` antes de documentar este plan | `6186b5cafa0b94795cd439c6ff575a4d76beff40` |
| Bot de la campaña | `agente-ia`, rama `main`, UUID `inuqmphtxqxzzrw3pyp724kk` |
| Versión de producción verificada en la sesión | `ef42fbbab75371726586a3e4e776d59010fe88b4` |
| Huella del prompt de producción | `3065e9761ddad910bae5d2595f37c0ca760a941e0f228b6da6450e8c999709b5` |
| Bot de prueba | `bot-demo`, rama `piloto-demo`, UUID `x2qnwcfwio5vpahcfzdrbsts` |
| Dominio del bot de prueba | `https://bot-demo.automaticnic.online` |
| Chatwoot compartido | `https://appchatwoot.automaticnic.online`, versión informada `4.17.1` |
| Cuenta de prueba existente en Chatwoot compartido | `Cliente Demo`, ID 2 |
| Bandeja de prueba existente | `Pruebas Demo`, ID 2, tipo API |
| Memoria de prueba existente | PostgreSQL `memoria_demo`, rol `bot_demo` |
| Host interno del PostgreSQL de memorias | `1hrm4idgdx20aqz5grz12fqb` |

Se consultaron ambos bots en lectura: los dos estaban `running:healthy`,
con salud `ok` y memoria PostgreSQL. El piloto todavía vende la libreta y la
taza ficticias de `prompts/demo.md`; todavía no envía imágenes.

**Hallazgo que corrige una suposición de la guía vieja:** Coolify devuelve
`is_auto_deploy_enabled=true` para **ambos** bots. No confiar en el paso
histórico que decía desactivar el automático. Antes de cualquier push de
implementación, verificar y desactivar el automático solamente de
`bot-demo`, con autorización de ejecución del piloto. Nunca modificar el
ajuste de `agente-ia`. El plan se guarda inicialmente con commit local,
sin push, para no disparar un despliegue mientras solo se documenta.

El 14/09/2026 se integró localmente `origin/main` en `piloto-demo`, desde la
revisión `44bc631a3b33c406fab5f3fe0c34476c2febb90a`. Se conservaron los filtros,
archivos y documentación del piloto, además de la huella del prompt, la espera
mínima y las herramientas de operación agregadas en `main`. La suite combinada
aprobó 203 pruebas con modelos falsos. Esta integración no modifica `main` ni
significa que los filtros del piloto hayan llegado a producción.

## 3. Demo que vamos a mostrar

Nombre ficticio: **Uniformes y Sublimación Demo**. Interfaz en español con
voseo nicaragüense. Mostrar permanentemente «Demostración: productos,
imágenes y precios ficticios. No se procesan compras».

Dos bandejas API representan las líneas futuras: **Uniformes · Demo** y
**Sublimación · Demo**. Los IDs se obtienen al crearlas y se registran;
nunca reutilizar un ID supuesto de otra instalación.

Un simulador web permite elegir la línea, iniciar una conversación nueva y
enviar mensajes como prospecto. Muestra los textos, fotos y cotizaciones
que realmente devuelve el bot a través de Chatwoot. En otra ventana se
muestra Chatwoot con las cuentas de administrador y empleado.

No usar respuestas precargadas para fingir un recorrido terminado. La
demostración por bandeja API no certifica entrega por WhatsApp; esa prueba
queda para cuando se registren los números nuevos del cliente.

### Catálogo y reglas ficticias de la primera versión

| Código | Producto | Incluye | Base por unidad (USD) |
|---|---|---|---:|
| FUT-01 | Uniforme de fútbol azul y blanco | Camiseta y pantalón | 22.00 |
| FUT-02 | Uniforme de fútbol rojo y negro | Camiseta y pantalón | 24.00 |
| BEI-01 | Uniforme de béisbol blanco y azul | Camiseta y pantalón | 32.00 |
| BEI-02 | Uniforme de béisbol gris y rojo | Camiseta y pantalón | 34.00 |
| SUB-01 | Taza blanca sublimada | Una taza con diseño de muestra | 8.00 |
| SUB-02 | Camiseta sublimada | Una camiseta con diseño de muestra | 15.00 |

- Cantidades enteras de 1 a 200. Por encima de 200, cotización humana.
- Descuento sobre el precio base: 1–11 unidades, 0 %; 12–23, 5 %;
  24–200, 10 %. No aplicar descuentos sobre extras.
- En FUT y BEI: nombre, +US$ 1 por unidad; número, +US$ 1 por unidad.
  Tallaje ficticio S/M/L/XL, sin recargo. Otras tallas requieren revisión.
- En SUB-01/SUB-02: solo diseño de muestra automático. Logos o diseños
  nuevos se derivan a una persona, sin inventar precio ni plazo.
- Fórmula con `Decimal`: base con descuento, redondeada a centavos, más
  extras por unidad; multiplicar por la cantidad. Mostrar desglose y total.
- Son importes de demostración del producto; no calcular ni prometer
  envío, impuestos o plazos de fabricación. Si se consultan, indicarlos
  como pendientes de confirmación del asesor en una contratación real.
- Ejemplo de aceptación: 18 FUT-01 con nombre y número → base descontada
  20.90, extras 2.00, unitario 22.90, total **US$ 412.20 ficticios**.
- Si falta producto, cantidad, talla o elección de extras, preguntar solo
  lo necesario. No suponer opciones que cambien el precio.

Generar seis imágenes de muestra con la herramienta de imágenes y su skill
correspondiente. Fondos limpios, producto claramente visible, sin marcas
reales ni escudos de equipos. Indicar «DEMO» en la presentación. Guardar
los archivos en el repositorio porque son ficticios y reproducibles.

## 4. Arquitectura propuesta para implementar

Esta demo aplica la metodología general de
[incorporación de clientes y administración de catálogos](metodologia-clientes.md).
El archivo y las imágenes locales descritos abajo son adecuados para datos
ficticios. Si el prospecto contrata, el catálogo real pasa a PostgreSQL y las
fotografías a almacenamiento persistente, sin guardar datos reales en este
repositorio público.

El panel futuro usa el portal multicliente común descrito en la metodología.
El dueño entra con su propia cuenta y el servidor limita todas las operaciones
al catálogo de este negocio. Otro cliente puede usar la misma URL, pero verá
otros productos, precios y fotografías. Para la demo inicial solo hace falta
una vista de los datos ficticios; la edición completa se habilita después de
la contratación.

### Catálogo, cotización y salida con imágenes

- Catálogo versionado en `catalogos/demo_uniformes.json`; imágenes en
  `recursos/demo_uniformes/`. Configuración de rutas solo mediante
  `config.py`. El Dockerfile debe copiar ambos directorios.
- Agregar herramientas para buscar productos y calcular cotizaciones. Las
  herramientas devuelven datos validados e identificadores de producto;
  Gemini interpreta la consulta y redacta, pero no determina tarifas ni
  realiza por su cuenta el cálculo comercial.
- Mantener compatibilidad de las respuestas de texto de consola, web y
  Telegram. Incorporar metadatos opcionales de adjuntos a la respuesta del
  agente y hacer que el adaptador Chatwoot los envíe. Nunca obtener rutas o
  URLs ejecutables leyendo instrucciones libres del texto generado.
- Resolver imágenes solo desde el catálogo autorizado. Validar archivo,
  tamaño y MIME; preparar JPEG/PNG menores de 5 MB. Enviar adjuntos reales
  por `multipart/form-data` con `attachments[]` a la API de Chatwoot.
- Si la foto falla, no afirmar que se envió. Informar el problema sin
  perder el texto de la cotización y dejar un diagnóstico en logs.
- Guardar cotizaciones como registros propios en `memoria_demo`, con un
  identificador, producto, opciones, cantidad, desglose, total, versión de
  tarifa y conversación. No usar tablas del checkpointer como catálogo.
  Conservar una copia de los datos usados para que una tarifa futura no
  cambie una cotización ya emitida.
- Evitar duplicar cotizaciones y adjuntos ante eventos repetidos mediante
  el identificador del mensaje entrante. Un timeout de envío exige revisar
  el resultado antes de repetir el POST, no reenviar a ciegas.

### Bandejas, memoria y simulador

- Una instancia de `bot-demo` atiende las dos bandejas permitidas del
  entorno de demo. Extender el filtro a una lista explícita, preservando
  compatibilidad con `CHATWOOT_BANDEJA_ID` y rechazando configuraciones
  contradictorias. Incorporar `CHATWOOT_BANDEJAS_IDS` en `config.py` y en
  los ejemplos, sin agregarlo a `AJUSTABLES`.
- Los mensajes conservan su ID de conversación de Chatwoot para el envío.
  La clave de memoria se separa de ese ID e incluye entorno, cuenta,
  bandeja y conversación. Esto evita colisiones al pasar el bot a otra
  instalación de Chatwoot sin borrar las memorias del piloto anterior.
- Mantener PostgreSQL para memoria y cotizaciones. El buffer puede seguir
  en RAM con un solo proceso; no incorporar Redis al bot para esta demo.
- Servir el simulador desde una ruta habilitada únicamente en modo demo.
  El backend crea contactos sintéticos sin teléfono ni correo y conversa
  solo con las dos bandejas API autorizadas. Los tokens de Chatwoot y
  Gemini nunca llegan al navegador.
- Proteger el simulador con una clave de demo guardada en configuración y
  una sesión; no colocar la clave en la URL. Limitar tamaño y frecuencia
  de mensajes, y ligar cada sesión a sus propios IDs de conversación.
  No aceptar del navegador una cuenta o conversación arbitraria.
- La foto se obtiene mediante una ruta autorizada del backend para esa
  sesión; no copiar al navegador credenciales para descargar adjuntos.
- Usar `MAX_TOKENS=4096`, `BUFFER_SEGUNDOS=1`,
  `RESPUESTA_MINIMA_SEGUNDOS=0` y `RITMO_HUMANO=false` solo en la demo.
  No cambiar los tiempos de respuesta de la agencia.

### Atención humana y permisos: no modificar el Chatwoot compartido

La revisión del código oficial de Chatwoot **4.17.1** encontró:

- El borrado de contactos, bandejas y conversaciones completas exige
  administrador en sus políticas.
- La ruta de borrado de mensajes individuales usa la autorización de
  acceso a la conversación; no muestra la misma exigencia de administrador.
  El requisito completo no se debe dar por cumplido por ocultar un botón.

Para demostrar el bloqueo completo sin cambiar el CRM de la campaña:

1. Preparar una **instalación de Chatwoot exclusiva de la demo**, partiendo
   de la versión `4.17.1`, con PostgreSQL, Redis y archivos propios. No
   copiar la base ni los contactos del Chatwoot compartido. Revisar primero
   RAM, CPU y disco actuales del VPS; si no hay margen, mantener esta parte
   en un entorno Docker aislado de desarrollo y no cargar el VPS a costa
   del bot de la agencia.
2. Conservar el cambio de permisos como parche reproducible de esa versión
   dentro de `infra/chatwoot-demo/`. Agregar una autorización en el servidor
   que exija administrador para borrar mensajes individuales y adjuntos;
   mantener el bloqueo de conversaciones completas. Ajustar también la
   interfaz para no ofrecer al agente una acción que el servidor rechaza.
   No alterar el Chatwoot compartido ni aplicar parches manuales efímeros.
3. Crear en la copia la cuenta de la marca ficticia, las dos bandejas API,
   un administrador de demostración y un empleado. Mantener separada la
   identidad técnica del bot; sus credenciales no se entregan al empleado.
   No decir que el dueño es el único administrador de toda la plataforma:
   la agencia conserva acceso técnico y de infraestructura.
4. Actualizar **solo el destino de `bot-demo`** para esa instalación cuando
   esté sana. Guardar antes la configuración anterior en un archivo local
   ignorado y conservar la cuenta 2 y bandeja 2 actuales sin borrarlas.
5. Adaptar las protecciones de los scripts: validar conjuntamente host,
   cuenta, usuario técnico, nombre y tipo API de las bandejas. Rechazar
   expresamente el host/cuenta de la agencia. Un ID 1 de una instalación
   nueva no identifica por sí solo la cuenta 1 de producción.
6. Probar con el usuario Agente desde la web y mediante la API: borrar una
   conversación completa y un mensaje individual debe devolver rechazo y
   dejar ambos intactos. Hacer las pruebas solo con objetos sintéticos
   registrados en la copia. Conservar la posibilidad de responder, dejar
   notas y resolver/reabrir: resolver una conversación no es borrarla.

La cotización a medida debe activar atención humana: configurar en la
cuenta de demo una automatización limitada a esa cuenta que reconozca la
frase «Perfecto, te paso con una persona del equipo y te escribe por aquí
mismo.», aplique `humano` y asigne al administrador de demo. No reutilizar
por suposición la automatización ni el usuario ID 1 de la agencia.

No ofrecer como validado el bloqueo completo si la copia aislada y las
pruebas de API no están listas. La parte de catálogo puede demostrarse
antes, informando expresamente que permisos sigue pendiente.

## 5. Orden de trabajo y comprobaciones

1. Leer este plan, `AGENTS.md` y las guías de operación/piloto. Comprobar
   ramas, cambios locales, estado de ambos bots y despliegues en curso.
   Fijar el despliegue de `bot-demo` como manual antes de publicar código.
2. Integrar `origin/main` hacia `piloto-demo`; conservar filtros y docs de
   la demo. Ejecutar la suite existente con modelos falsos como referencia.
3. Implementar catálogo, imágenes y cotizador. Probar importes y límites
   sin proveedor: cantidades 1, 11, 12, 23, 24, 200, inválidas y superiores;
   extras, redondeo, diseño a medida, opciones faltantes y producto ausente.
4. Implementar adjuntos y persistencia de cotizaciones. Probar archivo
   inexistente, formato/tamaño inválido, foto de otro producto, fallo de
   envío y evento repetido. Un reinicio no debe cambiar la cotización.
5. Implementar dos bandejas y simulador; probar que una sesión, cuenta o
   bandeja ajena no pueda leer ni escribir otra conversación ni consumir
   el modelo. Mantener las pruebas de etiqueta `humano` y duplicados.
6. Preparar y verificar Chatwoot aislado y el parche de permisos. Las
   pruebas de autorización deben cubrir backend y frontend, no solo el
   aspecto del menú. Probar la restauración de un respaldo sintético de
   base y adjuntos antes de usar esto como argumento comercial.
7. Desplegar únicamente la demo con comando dedicado y destino fijo
   `bot-demo / x2qnwcfwio5vpahcfzdrbsts / piloto-demo`. El comando de
   `main`, `scripts/desplegar.py`, apunta exclusivamente a **agente-ia**:
   **no usarlo para desplegar el piloto**. El comando demo debe verificar
   rama limpia/subida, destino, tests, una sola solicitud, ID, commit y
   huella del prompt; consultar historial antes de repetir ante un timeout.
8. Hacer una prueba funcional acotada con Gemini en contactos sintéticos
   de las bandejas API. Esta comprobación sí consume tokens; los tests
   automáticos permanecen con modelos falsos. No enviar mensajes a
   prospectos de la campaña ni a números reales.
9. Verificar que `agente-ia` mantenga salud `ok` y su huella anterior.
   Registrar demo URL, cuentas/roles sin contraseñas, IDs, commit, despliegue,
   evidencias y pendientes aquí y en `docs/piloto-demo.md`.

### Guion de presentación y aceptación

- «Quiero ver uniformes de fútbol»: se recibe como adjunto una imagen del
  catálogo ficticio y se distingue correctamente entre modelos.
- «18 del azul, talla M, con nombre y número»: se muestra el desglose de
  US$ 412.20, código de cotización y aviso de demo.
- Consulta de béisbol: imagen y tarifa del SKU de béisbol, sin mezclarlo
  con fútbol ni con otra conversación.
- Segunda línea, «12 tazas del diseño de muestra»: total US$ 91.20; llega
  a Sublimación y se responde por esa misma bandeja.
- «Quiero un diseño nuevo con mi logo»: recopila datos y deriva a una
  persona; no presenta como definitivo un precio que no tiene regla.
- Empleado: puede atender y resolver; no puede borrar conversación ni
  mensaje por interfaz o API. El contenido sigue presente tras el rechazo.
- Reinicio controlado de la demo: persisten historial, cotización y fotos.
- La agencia continúa sana y sin cambios de prompt, credenciales o memoria.

## 6. Continuidad, límites y estado de esta sesión

Documentación de partida: [piloto actual](piloto-demo.md) y
[operación](operacion.md). La versión de `main` contiene notas más recientes
hasta que se complete la integración pendiente hacia esta rama.

Credenciales locales: `.env.demo.local`, `.env.admin.local`,
`.env.coolify.local` y `.credenciales-demo.local`, cuando existan. Leerlas
solo desde la configuración correspondiente. No imprimir valores, incluir
secretos en el plan ni copiarlos al repositorio público. Para la copia
aislada, usar credenciales nuevas guardadas en archivos ignorados.

No borrar memorias como paso de actualización, no reiniciar PostgreSQL o
Chatwoot compartidos, no comprar servicios ni registrar números para una
demostración ficticia. Si hay un problema de capacidad o credenciales,
registrarlo y continuar las partes locales que no dependan de él.

- [x] Pedido y alcance de permisos confirmados con el usuario.
- [x] Ramas y recursos existentes revisados en lectura.
- [x] Plan y guion ficticio escritos para continuidad.
- [x] Integración de `main` hacia `piloto-demo`; 203 pruebas de referencia
  aprobadas localmente, sin llamadas a Gemini.
- [ ] Catálogo, imágenes y cotizador implementados.
- [ ] Envío de adjuntos y cotizaciones persistentes implementados.
- [ ] Dos bandejas y simulador disponibles.
- [ ] Chatwoot aislado y bloqueo de borrado verificados.
- [ ] Despliegue demo y prueba real con Gemini completados.
- [ ] Validación de entrega por WhatsApp con los números nuevos, después
  de la confirmación del cliente; no forma parte de la demo API inicial.

**Primer paso para el siguiente agente:** comprobar el estado de Git, leer
este documento y confirmar qué casillas siguen pendientes. No rehacer el
piloto de cero ni suponer que el plan ya se ejecutó. Actualizar esta lista
después de cada avance y conservar IDs de recursos, pruebas y despliegues.

## Referencias verificadas en la investigación

- [Adjuntos por API de Chatwoot](https://developers.chatwoot.com/api-reference/messages/create-new-message).
- [Varios números y bandejas de WhatsApp](https://www.chatwoot.com/hc/user-guide/articles/1756799850-how-to-setup-a-whats_app-channel-manual-flow).
- [Política de conversaciones v4.17.1](https://github.com/chatwoot/chatwoot/blob/v4.17.1/app/policies/conversation_policy.rb).
- [Borrado de mensajes v4.17.1](https://github.com/chatwoot/chatwoot/blob/v4.17.1/app/controllers/api/v1/accounts/conversations/messages_controller.rb).
- [Autorización del acceso a conversaciones v4.17.1](https://github.com/chatwoot/chatwoot/blob/v4.17.1/app/controllers/api/v1/accounts/conversations/base_controller.rb).
- [Permisos personalizados y disponibilidad](https://www.chatwoot.com/features/roles-permissions). No asumir que comprar una licencia resuelve el bloqueo específico sin verificarlo.
