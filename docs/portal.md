# Portal de catálogos — `catalogos.automaticnic.online`

> **Estado al 14/09/2026: portal conectado con Smarth House en producción.**
> `agente-ia` ejecuta la integración desde `main`, con el prompt
> `prompts/smarth_house_portal.md` y la oferta publicada. Ya envía fotos por
> WhatsApp. `bot-demo` conserva la demo de uniformes.

**El registro actual está en
[despliegue-smarth-portal.md](despliegue-smarth-portal.md).** Incluye la
corrección del almacenamiento persistente real, respaldos restaurados,
despliegues y alcance de pruebas. La revisión anterior queda como historial.

Las decisiones de negocio están en
[la metodología](metodologia-clientes.md#portal-del-catálogo-y-separación-entre-negocios).
Este documento explica cómo está hecho y cómo seguirlo.

## Qué hace

Cada negocio entra con su cuenta y carga:

- **Catálogo**: productos, servicios y promociones de cualquier rubro. Cada
  ítem lleva:
  - Precio con su propia moneda (US$ o C$) y unidad.
  - La opción de que ese precio sea «desde»: el bot da la referencia y el
    precio final lo confirma una persona.
  - Vigencia.
  - Opciones (talla, color, tamaño), donde un valor puede costar más.
  - Extras con precio, en la misma moneda.
  - Fotos.
  - Dónde se ofrece, si el negocio tiene varias líneas o sucursales.
  - Cotización automática, agotado y activo.
- **Mi negocio**: nombre, a qué se dedica, dirección, mapa, horarios, formas
  de pago aceptadas, nota sobre pagos, envíos, políticas y preguntas
  frecuentes. También las **líneas de WhatsApp o sucursales**, cada una con
  su dirección y horarios si son distintos. Tienen un código estable, y cada
  bot va a usar el suyo para saber qué línea atiende.
- **Reglas de precio**, todas opcionales y con su propio interruptor:
  - Moneda habitual: la que aparece al crear un ítem.
  - Descuentos por cantidad.
  - Cantidad a partir de la cual cotiza una persona.

  A la derecha se ve en palabras cómo cobra el bot, y se puede probar una
  cantidad.
- **Publicar**: todo lo anterior es un borrador. «Publicar» guarda una
  versión fija, y el bot usa solo la última versión publicada.

**Pagos:** el portal no guarda números de cuenta. La validación rechaza tiras
de dígitos en la nota de pagos, y también en los otros textos cuando además
mencionan cuentas o bancos. El bot puede decir qué formas de pago se aceptan;
todo lo demás sobre pagos lo pasa a una persona. Es una decisión del usuario
del 14/09.

Roles:

- **administrador**: carga, edita y publica.
- **empleado**: solo ve lo publicado.
- **Agencia**: no tiene pantalla. Usa `scripts/portal_admin.py`, que queda
  registrado en la actividad del negocio.

## Piezas

| Archivo | Qué resuelve |
|---|---|
| `portal_catalogos.py` | Punto de entrada: prepara la base y levanta el servidor |
| `src/portal/app.py` | Rutas para personas (`/api/...`) y para bots (`/api/bot/...`) |
| `src/portal/modelo.py` | Qué datos acepta y cómo se arma una publicación |
| `src/portal/repositorio.py` | Contrato de datos e implementación en memoria para los tests |
| `src/portal/postgres.py` | Esquema e implementación en PostgreSQL |
| `src/portal/almacen.py` | Fotos en disco, una carpeta por negocio |
| `src/portal/seguridad.py` | Contraseñas con scrypt, tokens y límite de intentos |
| `src/portal/config.py` | Variables `PORTAL_*`; no usa el `.env` del bot |
| `src/portal/static/` | `portal.html`, `portal.css` y `portal.js`, sin build |
| `scripts/portal_admin.py` | Negocios, cuentas, accesos y claves de bot |

El paquete `portal` **no importa nada de `agente`**. Así no carga el `.env` de
la agencia ni sus claves.

## En producción

Desplegado el 14/09/2026:

| Cosa | Valor |
|---|---|
| URL | `https://catalogos.automaticnic.online`, HTTPS válido |
| App en Coolify | `portal-catalogos`, uuid `vhvndsnvosry83dqlztwontm`, rama `portal` |
| Imagen | `Dockerfile.portal` (no el `Dockerfile` del agente) |
| Base | `catalogos`, rol `portal_catalogos`, mismo PostgreSQL de las memorias |
| Fotos | Bind mount de `/data/coolify/applications/vhvndsnvosry83dqlztwontm/catalogo-fotos` a `/app/datos/portal`, registrado en Coolify y verificado en el contenedor |
| Despliegue automático | Apagado, igual que `bot-demo` |
| Negocios cargados | `smarth-house`, oferta y «Mi negocio» publicados; revisión de la conexión en el documento enlazado arriba |

**Corrección del 14/09:** el despliegue original no tenía montajes, aunque
la documentación afirmaba que había un volumen Docker. Se respaldaron las
fotos antes de reiniciar y se configuró el bind mount anterior. La publicación
y las imágenes se verificaron después del despliegue; no recrear el almacén.

**Antes de tocar esto:** confirmar rama y que no haya cambios locales sin
commit, y recordar que ahora sí es producción — no es la base de pruebas
`catalogos_pruebas`.

**Pendiente chico:** `PORTAL_PROXIES=*` confía en cualquier proxy. Es
razonable acá porque el contenedor no tiene el puerto publicado al host
(`ports_mappings` vacío): solo Traefik llega. Si eso cambia, hay que fijar
el rango real de la red `coolify` en vez de `*`.

## Correrlo en tu computadora

`.env.portal.local` (ignorado por Git y Docker) ya existe con:

- `PORTAL_DSN`: base `catalogos_pruebas`, usuario `portal_pruebas`.
- `PORTAL_ARCHIVOS=datos/portal`
- `PORTAL_COOKIE_SEGURA=false`

```powershell
.\.venv\Scripts\python.exe portal_catalogos.py      # http://127.0.0.1:8010
.\.venv\Scripts\python.exe scripts\portal_admin.py --help
```

Las contraseñas generadas con `--generar` y las claves de bot se guardan en
`.credenciales-portal.local`, que Git ignora. **Nunca se imprimen.**

Datos cargados en `catalogos_pruebas`:

- `smarth-house`: vacío, con la cuenta de administrador del usuario.
- `prueba-visual`: ejemplo con una promoción, un producto con opciones y
  extras, un servicio sin precio y un ítem apagado, todo publicado. Tiene una
  cuenta de administradora y una de empleado, ambas de prueba.

## Seguridad que ya está

- **El negocio sale de la sesión.** En cada consulta el repositorio filtra
  por `cliente_id`, y las fotos tienen una clave foránea compuesta (negocio,
  ítem). Hay tests que prueban que un negocio no puede leer, editar, borrar
  ni subir fotos a otro.
- **Sesiones:**
  - Cookie `HttpOnly` y `SameSite=Strict`, con `Secure` en el servidor.
  - Duran 12 horas y en la base solo se guarda la huella SHA-256 del token.
  - La sesión deja de servir si se retira el acceso o se desactiva la cuenta.
- **Cambios desde otros sitios:** todo cambio exige la cabecera `X-Portal: 1`.
- **Cabeceras del navegador:** CSP sin scripts ni estilos en línea,
  `X-Frame-Options: DENY` y `nosniff`. El JavaScript no usa `innerHTML` con
  datos.
- **Inicio de sesión:**
  - Límite de 5 fallos por correo y 20 por dirección cada 15 minutos.
  - El mismo mensaje y un tiempo parecido exista o no la cuenta.
- **Fotos:**
  - Solo JPG o PNG, reconocidos por su firma, de hasta 5 MB y hasta 5 por
    ítem.
  - Nunca se pisan ni se borran del disco: la versión publicada sigue
    pudiendo mandarlas.
- **Otras direcciones:** con `PORTAL_HOSTS` se rechaza cualquier otro Host.
  `/salud` queda libre para Coolify.

## Qué lee el bot

```text
GET /api/bot/catalogo              Authorization: Bearer <clave del negocio>
  → 200 {version, publicada_en, huella, contenido}   (ETag = huella)
  → 304 si manda If-None-Match con la misma huella
  → 404 si el negocio todavía no publicó
GET /api/bot/fotos/<id>            misma clave → la imagen
```

`contenido` (formato 1):

```json
{
  "formato": 1,
  "negocio": {"id": "smarth-house", "nombre": "Smarth House"},
  "perfil": {
    "direccion": "…", "horarios": "…", "formas_de_pago": ["Transferencia bancaria"], "preguntas": [],
    "lineas": [{"codigo": "uniformes", "nombre": "Uniformes", "direccion": "", "horarios": ""}]
  },
  "reglas": {"cantidad_maxima": 200, "descuentos": [{"desde": 12, "porcentaje": "5"}]},
  "items": [{
    "sku": "FUT-01", "tipo": "producto", "nombre": "…", "precio": "22.00", "moneda": "USD",
    "precio_desde": false, "unidad": "por unidad", "vigente_desde": null, "vigente_hasta": null,
    "opciones": [{"nombre": "Talla", "valores": [{"valor": "M", "recargo": null}, {"valor": "XXL", "recargo": "2.00"}]}],
    "extras": [{"codigo": "nombre_estampado", "nombre": "Nombre estampado", "precio": "1.00"}],
    "lineas": ["uniformes"],
    "cotizacion_automatica": true, "agotado": false,
    "fotos": [{"id": "…", "mime": "image/png", "bytes": 112233, "sha256": "…"}]
  }]
}
```

Qué trae:

- Solo ítems activos. Cada ítem trae su moneda: no hay una moneda general.
- Los importes van como texto, para no perder centavos.
- `lineas` vacío quiere decir que se ofrece en todas las líneas. Si se
  borraron todas las líneas de un ítem, ese ítem no se publica.
- Un ítem `agotado` se muestra, pero no se toma el pedido.
- `precio_desde` nunca se cotiza solo.
- El recargo de una opción se suma por unidad, igual que un extra, y no
  lleva descuento. Las rutas internas de los archivos no salen del portal.

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_portal_*.py
```

- Corren sin base ni red, con `RepositorioEnMemoria`.
- Para correr también el contrato contra PostgreSQL, definí
  `PORTAL_PRUEBAS_DSN`. Las pruebas solo aceptan la base `catalogos_pruebas`
  y borran lo que crean.

Verificación inicial del 14/09 (los resultados posteriores están en el
[registro de despliegue](despliegue-smarth-portal.md#comprobaciones)):

- Suite completa: 358 aprobadas y 8 omitidas, las de PostgreSQL opcional.
- Contrato contra `catalogos_pruebas`: 8 de 8.
- Recorrido real contra el portal local, 26 de 26:
  - inicio de sesión, cookie y rechazo de número de cuenta;
  - carga de ítems y fotos, rechazo de GIF, publicación y 304;
  - lectura del bot con su clave y descarga exacta de la foto;
  - empleado sin acceso al borrador.
- Capturas con Chrome sin ventana, en escritorio y celular, sin errores de
  CSP en la consola.

## Base de pruebas

La base `catalogos_pruebas` y el rol `portal_pruebas` se crearon el 14/09 en
el PostgreSQL de las memorias. El acceso de administrador salió de la API de
Coolify y no se imprimió. Configuración:

- El rol no es superusuario, no crea bases ni roles y admite 5 conexiones.
- Tiene CONNECT y TEMPORARY en su base, y USAGE y CREATE en `public`.
- Se retiraron los permisos de PUBLIC sobre la base y el esquema.
- Se comprobó que no puede conectarse a `memoria_demo`.

**Conexiones colgadas (14/09).** Detener el portal a la fuerza varias veces
dejó sesiones abiertas del lado del servidor, que llenaron el límite de 5 del
rol. Mientras duran, las pruebas contra PostgreSQL esperan y fallan.

- El pool ahora usa como máximo 3 conexiones, confirma que cada una siga viva
  antes de usarla y suelta las que sobran.
- Liberar las sesiones colgadas o subir el límite del rol requiere el acceso
  de administrador del PostgreSQL, y eso lo decide el usuario. Si no, se
  cierran solas cuando el servidor detecta el corte.

## Lo que falta

**Para que sirva a más rubros.** Revisión del 14/09, ordenada por cuántos
negocios cubre cada punto. Ese mismo día, con el OK del usuario, se hicieron
estos tres:

1. ✅ **Opciones con precio**: talla XXL +US$ 2, tamaño grande +C$ 40.
2. ✅ **Líneas de WhatsApp o sucursales**: cada ítem elige dónde se ofrece,
   y cada línea puede tener su dirección y horarios.
3. ✅ **Estados «Agotado» y «Precio desde»**.

Siguen pendientes:

4. **Carga desde Excel o CSV** para catálogos grandes, como ferreterías o
   farmacias.
5. Más adelante:
   - Campos propios por ítem (año, kilometraje, zona).
   - Descuentos por ítem o por categoría.
   - Costo de envío por zona.
   - Duración de un servicio.
6. **Fuera del portal por ahora:** agenda de citas, reservas y cupos. Es otro
   producto, conectado a un calendario.

**Fase 2: publicarlo** (despliegue inicial completado el 14/09)

La aplicación, la base y el almacenamiento persistente ya existen; no
recrearlos. Los respaldos manuales de bases y fotos se restauraron y
verificaron; faltan copias automáticas periódicas fuera del VPS.

- `Dockerfile` propio del portal, o un CMD alternativo:
  - Mismo repositorio, puerto propio y health check a `/salud`.
- Aplicación nueva en Coolify, con despliegue automático apagado.
- Base `catalogos` con su propio rol. El DSN va con el host interno de
  Docker, no con la IP pública.
- Volumen persistente para `PORTAL_ARCHIVOS`, con respaldo.
- Variables:
  - `PORTAL_HOSTS=catalogos.automaticnic.online`
  - `PORTAL_COOKIE_SEGURA=true`
  - `PORTAL_PROXIES` con la red del proxy
  - `PORTAL_HOST=0.0.0.0`
- El DNS `catalogos` ya apunta a `2.25.112.244`.
- Pendientes chicos:
  - Borrar las sesiones vencidas.
  - Versionar el esquema cuando cambie una tabla existente.
  - Cambiar la contraseña desde el portal.

**Fase 3: Smarth House con el portal** (desplegada el 14/09)

- ✅ `src/agente/fuente_portal.py` consulta y valida la publicación. La caché
  se separa por URL, clave y negocio esperado; nunca se busca «la única
  carpeta que haya». Solo se usa hasta cinco minutos ante fallos transitorios,
  y nunca para calcular una cotización nueva. Los rechazos de credenciales
  invalidan la copia. Las descargas verifican tamaño, firma y SHA-256.
- ✅ `src/agente/portal.py` consulta promociones, productos, servicios, perfil
  y fotos; calcula opciones, extras y descuentos con Decimal. Si no hay
  promoción, muestra servicios regulares publicados. Si no hay ninguno,
  confirma con una persona, según decisión del usuario.
- ✅ La configuración exige `PORTAL_URL`, `PORTAL_CLAVE_BOT` y
  `PORTAL_NEGOCIO_ID`. `PORTAL_LINEA` es obligatorio si se publicaron líneas
  del negocio. No combina estas fuentes con `CATALOGO_RUTA` o
  `PROMOCIONES_RUTA`. El piloto de uniformes mantiene su fuente local.
- ✅ Smarth House publicó PLAN-1 y Mi negocio. Se corrigieron tipo, unidad y
  descripción con confirmación del usuario; la clave de lectura ya existe.
  Su archivo local es `.env.bot-portal.local`, ignorado por Git y Docker.
- ✅ El prompt activo está en `prompts/smarth_house_portal.md` y responde
  progresivamente según la pregunta. El prompt anterior se conserva en `prompts/archivo/smarth_house_sin_portal.md`.
- ✅ Recorrido completo del webhook en contenedor aislado, con Gemini y
  Chatwoot cuenta 2, bandeja 3, conversación 5; foto comprobada por sus bytes.
  El webhook temporal se retiró; la demo original siguió atendiendo.
- ✅ Integración llevada a `main` y desplegada con autorización del usuario;
  portal y bot sanos, huellas verificadas. Fotos leídas en las conversaciones
  34 y 35 de WhatsApp que mostró el usuario.
- ⏳ La redacción breve se probó en diez turnos aislados con Gemini y ya está
  desplegada. El usuario decidió comprobarla en su teléfono más adelante.
  El traspaso mantiene su frase y la automatización existente; no se forzó
  un traspaso de un prospecto para probarlo.
