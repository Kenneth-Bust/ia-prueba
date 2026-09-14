# Metodología para incorporar clientes y administrar catálogos

Este documento define la forma de crecer el servicio sin convertir cada
cliente en una copia distinta del programa. Deben leerlo los agentes de IA
antes de diseñar una incorporación, un catálogo o un cambio compartido.

## Principio de trabajo

El código del agente es un producto común. Cada negocio conserva de manera
independiente su configuración, prompt, catálogo, fotografías, credenciales,
cuenta y bandejas de Chatwoot, memoria y cotizaciones.

Las ramas se usan para desarrollar y probar cambios. No crear una rama
permanente por cliente como mecanismo principal de aislamiento: obligaría a
repetir cada corrección en todas las ramas. Durante la transición actual:

- `main` es la versión desplegada para Smarth House. No modificarla ni
  desplegarla como parte de un trabajo para otro cliente.
- `piloto-demo` es el lugar autorizado para construir y comprobar la nueva
  capacidad de catálogos, cotizaciones, fotografías y varias bandejas.
- Cuando la capacidad esté probada, se prepara una versión común estable.
  Cada cliente la ejecutará en una aplicación separada con sus propios datos.

Dos números de un mismo negocio no requieren dos ramas ni dos catálogos.
Son dos bandejas de WhatsApp dentro de la cuenta de ese negocio. La
configuración decide qué categorías atiende cada bandeja.

## Aislamiento mínimo por cliente

Cada alta real necesita:

1. Identificador estable de cliente, que no dependa del nombre visible.
2. Aplicación propia y variables propias en Coolify.
3. Cuenta de Chatwoot propia y lista explícita de bandejas permitidas.
4. Credencial técnica propia, separada de las cuentas humanas.
5. Base PostgreSQL o permisos de base limitados a ese cliente.
6. Prompt, catálogo, reglas de cotización y usuarios propios.
7. Espacio propio para fotografías y otros archivos.
8. Copias de seguridad y registro del commit desplegado.

Los secretos viven en variables del servidor o archivos locales ignorados.
Nunca escribir tokens, contraseñas, códigos OTP ni DSN con credenciales en
Git, documentos o mensajes de soporte.

## Fuente de productos, precios y fotografías

La memoria conversacional no es un catálogo. Gemini tampoco es la fuente de
precios ni decide una ruta de archivo. Hay tres responsabilidades distintas:

- El **catálogo** contiene los datos autorizados y vigentes.
- El **cotizador** aplica con código las reglas, descuentos y redondeos.
- Gemini entiende el mensaje y redacta usando el resultado validado.

### Demostraciones

Una demo pequeña y ficticia puede usar un archivo como
`catalogos/demo_uniformes.json` y archivos en
`recursos/demo_uniformes/`. Es reproducible y se puede revisar en Git. Debe
mostrar claramente que son datos ficticios. Las imágenes se incluyen en la
imagen Docker y cambiar el catálogo exige un nuevo despliegue del piloto.

### Clientes reales

No guardar el catálogo real ni sus fotografías dentro del repositorio
público. Guardar los datos en PostgreSQL y las fotografías en almacenamiento
persistente para objetos, compatible con S3, o temporalmente en un volumen
persistente dedicado. Se prefiere almacenamiento de objetos porque sobrevive
a despliegues y permite crecer sin agrandar la imagen Docker.

La tabla de productos debe incluir como mínimo:

| Campo | Función |
|---|---|
| `cliente_id` | Dueño del producto; obligatorio en todas las consultas |
| `sku` | Código estable y único dentro del cliente |
| `nombre` y `categoria` | Búsqueda y presentación |
| `precio_base` y `moneda` | Fuente autorizada de precio |
| `reglas_version` | Identifica descuentos y extras vigentes |
| `imagen_id` | Referencia a una fotografía registrada |
| `cotizacion_automatica` | Decide si calcula o deriva a una persona |
| `activo` | Impide ofrecer productos retirados |

El registro de la imagen contiene `cliente_id`, clave interna del objeto,
tipo MIME, tamaño y huella del archivo. La combinación `(cliente_id, sku)`
es única. El servidor comprueba que producto e imagen pertenezcan al mismo
cliente antes de enviar el adjunto.

Una cotización guarda una copia del nombre, precio, reglas y extras usados.
Así un cambio posterior del catálogo no modifica una cotización ya emitida.

## Portal del catálogo y separación entre negocios

> **Estado al 14/09/2026: propuesta, todavía sin implementar.** No existen
> la aplicación, el dominio ni la base del portal. No lo des por hecho.
>
> Decisiones que tomó el usuario ese día:
>
> - Construirlo ya, empezando por Smarth House, y extenderlo después a los
>   demás clientes.
> - Una sola URL para todos los negocios.
> - Usuarios propios del portal, no las cuentas de Chatwoot.
> - La imagen de la promoción de Smarth House espera al portal; no se
>   publica antes con el catálogo en archivo.
>
> Mientras tanto, los catálogos de demostración son JSON leídos por
> `src/agente/catalogo.py` y `src/agente/promociones.py`. El portal cambia
> esa fuente de datos; las herramientas y el envío de fotos por Chatwoot se
> conservan.
>
> Propuesta técnica presentada, pendiente de confirmar al diseñar el portal:
> base propia en el PostgreSQL existente con productos y fotos, y cada bot
> leyendo solo su catálogo desde el portal con una clave propia.

La opción predeterminada es una sola aplicación web para administrar todos
los catálogos, por ejemplo `catalogos.automaticnic.online`. No se crea otro
programa ni otra URL obligatoria por cliente. Cada persona inicia sesión y el
servidor obtiene de su membresía a qué `cliente_id` puede acceder.

La separación no depende de que la persona conozca una URL distinta. En cada
lectura, edición, carga de fotografía y publicación, el backend aplica el
`cliente_id` de la sesión autenticada. Debe ignorar un `cliente_id` enviado
libremente por el navegador y comprobar la pertenencia también en la base de
datos. Un administrador de un negocio no puede consultar otro catálogo
cambiando la dirección o un identificador en la petición.

Roles previstos:

- El administrador del negocio crea, edita, desactiva y publica sus productos.
- Los empleados pueden consultar el catálogo publicado, pero no cambiar
  precios, reglas ni fotografías.
- La agencia conserva una cuenta técnica auditada para soporte. No modifica
  información comercial sin autorización del cliente.

Todos usan el mismo portal y cada negocio ve un catálogo diferente. Si más
adelante se desea una dirección con su marca, como
`catalogo.cliente.example`, puede ser un alias del mismo portal; no implica
duplicar el código. Una instalación separada queda como opción para un cliente
que requiera aislamiento contractual o de infraestructura superior.

Las fotografías se guardan bajo un espacio propio, por ejemplo
`catalogos/<cliente_id>/<sku>/principal.jpg`, y nunca se listan solo por una
ruta que entregue el navegador. El backend comprueba sesión, producto e
imagen antes de generar el acceso o enviar el archivo a Chatwoot.

## Cómo el bot elige la fotografía correcta

El recorrido autorizado es:

```text
mensaje entrante
  → validar cuenta y bandeja
  → Gemini identifica intención y filtros
  → herramienta busca dentro del catálogo de ese cliente
  → catálogo devuelve pocos SKU válidos
  → si hay ambigüedad, el bot pregunta o muestra opciones
  → el servidor valida el SKU elegido
  → consulta la imagen registrada para ese producto y cliente
  → obtiene el archivo del almacenamiento
  → lo sube como adjunto a Chatwoot
  → Chatwoot lo entrega por la bandeja de origen
```

Gemini recibe nombres, características, SKU y precios necesarios para
redactar. No recibe permiso para inventar una URL, leer una ruta arbitraria
ni escoger un archivo fuera del resultado de la herramienta. El servidor
resuelve `imagen_id` después de validar el producto.

Si hay dos modelos posibles, se pueden enviar como máximo unas pocas opciones
y conservar sus SKU en el estado de la conversación. Una respuesta como «el
azul» se resuelve únicamente entre esas opciones. Si la fotografía falta o
falla el envío, se conserva la cotización en texto y no se afirma que la foto
fue enviada.

Enviar una fotografía propia desde almacenamiento hacia Chatwoot no requiere
que Gemini analice sus píxeles y no suma tokens de visión. Sí hay consumo de
visión cuando el cliente envía una imagen y se decide analizarla con Gemini.

## Continuidad entre agentes y sesiones

Al comenzar una sesión, el agente debe:

1. Leer `AGENTS.md`.
2. Leer `docs/operacion.md` para conocer lo que está desplegado.
3. Leer este documento para conservar la arquitectura multicliente.
4. Leer el plan específico del cliente y comprobar sus casillas pendientes.
5. Ejecutar `git status`, confirmar la rama y revisar cambios sin guardar.
6. Verificar el destino antes de cualquier push o despliegue.

Al terminar una etapa, debe actualizar el plan específico con:

- Qué quedó implementado y qué sigue pendiente.
- Pruebas ejecutadas y su resultado.
- IDs de recursos sin credenciales.
- Rama y commit exactos.
- Despliegue realizado o constancia explícita de que no se desplegó.
- Riesgos o decisiones que el siguiente agente no debe redescubrir.

Un plan no demuestra que una función exista. Mantener listas separadas de lo
planificado, lo implementado, lo probado localmente y lo verificado en vivo.
No marcar una tarea como terminada hasta tener la evidencia correspondiente.
