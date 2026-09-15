# Qué prompt usa cada entorno

El bot lee un solo archivo, elegido por `PROMPT_SISTEMA`. Tener otros
Markdown guardados no los agrega al contexto ni gasta tokens del modelo.
Cuando hay portal, el agente añade sus reglas de uso de herramientas.

| Archivo | Función |
|---|---|
| `prompts/smarth_house_portal.md` | Activo de Smarth House; consulta la publicación del portal |
| `prompts/demo_uniformes.md` | Activo de bot-demo; usa el catálogo ficticio de uniformes |
| `prompts/plantillas/general.md` | Predeterminado para nuevas pruebas locales; sin identidad ni precios de un negocio |
| `prompts/plantillas/cliente_demo.md` | Plantilla ficticia de libreta y taza para pruebas de aislamiento |
| `prompts/archivo/smarth_house_sin_portal.md` | Oferta anterior de Smarth House, conservada sin editar para consulta histórica |

Los dos prompts activos conservaron ruta y contenido durante esta limpieza.
Las variables de Coolify siguen seleccionándolos. No hay que desplegar por
mover documentación o reorganizar plantillas fuera de producción.

## Cambiar información

Para modificar el tono o la forma de conversar, editar el prompt del negocio
correspondiente y seguir el proceso de pruebas y despliegue. En el servidor
el archivo vive dentro de la imagen Docker; guardar un archivo en esta PC
no lo reemplaza en producción.

Para cambiar productos, servicios, promociones, precios, fotos o datos de
Smarth House, editar y **Publicar en el portal**. No copiar esas tarifas a
las plantillas ni al prompt activo. Si una fotografía contiene un precio,
actualizarla también. La memoria conserva el contexto de la conversación,
pero las condiciones vigentes se consultan en el catálogo.

## Configuraciones anteriores

Desde la reorganización del 15/09, el código reconoce estas rutas antiguas
de `.env` y las dirige al mismo contenido en su ubicación nueva:

| Valor anterior de `PROMPT_SISTEMA` | Archivo que se abre |
|---|---|
| `prompts/sistema.md` | `prompts/archivo/smarth_house_sin_portal.md` |
| `prompts/demo.md` | `prompts/plantillas/cliente_demo.md` |

Así actualizar el repositorio en otra PC no obliga a publicar ni reescribir
credenciales privadas. Esta compatibilidad aplica a la configuración del
agente y al editor web local. El nuevo `.env.example` usa la plantilla
general; un `.env` existente conserva el contenido que había seleccionado.
Código externo que construya `Config` directamente con una ruta vieja debe
pasar la nueva ruta.

El comando de despliegue, que solo administra agente-ia, espera por defecto
`prompts/smarth_house_portal.md`. Para comprobar despliegues históricos hay
que indicar el prompt que existía en aquel commit, por ejemplo
`--prompt prompts/sistema.md`. No apuntar el bot del portal a la oferta
archivada para una reversión improvisada: revisar también código y variables.
