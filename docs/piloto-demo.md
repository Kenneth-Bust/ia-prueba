# Piloto actual: uniformes y sublimación

Último despliegue verificado: **14/09/2026**. Guía reorganizada el 15/09;
esta limpieza no despliega ni cambia la demo. La preparación original de
Cliente Demo está en el [archivo histórico](archivo/piloto-inicial.md).

| Recurso | Estado verificado |
|---|---|
| Aplicación / rama | `bot-demo` / `piloto-demo` |
| UUID en Coolify | `x2qnwcfwio5vpahcfzdrbsts` |
| Dominio | `https://bot-demo.automaticnic.online` |
| Prompt activo | `prompts/demo_uniformes.md` |
| Catálogo | `catalogos/demo_uniformes.json`, datos e imágenes ficticios |
| Chatwoot | Cuenta 2, bandeja API 2 `Pruebas Demo` |
| Memoria | PostgreSQL `memoria_demo`, rol `bot_demo` |
| Modelo / máximo de salida | `gemini-3.8-flash` / `MAX_TOKENS=4096` |
| Despliegue automático | Desactivado en la última comprobación |
| Commit desplegado | `922dc11db114bafa37610dda6d984a03b9a9d414` |
| Despliegue | `80ah9vrn0ryelecyts6amzgs`, terminado y verificado |

La referencia `piloto-demo` en `e36ac73` incluye documentación posterior a
esa imagen. Consultar la API antes de operar: ni una rama ni una guía
sustituyen comprobar el contenedor que realmente está ejecutándose.

## Qué se puede mostrar

El bot consulta uniformes y sublimación, envía imágenes ficticias de
catálogo y calcula cantidades y opciones publicadas. Los trabajos a medida
pasan a una persona. Las pruebas de la bandeja API comprobaron textos,
fotografías y cotizaciones; no certifican entrega a los números nuevos del
prospecto, que todavía no están conectados.

`scripts/chat_demo.py` permite conversar desde la PC a través de esa bandeja
API. Usa las credenciales de `.env.demo.local`, que no viajan en Git.
Consultar el docstring del script antes de usarlo: crea conversaciones y
envía mensajes sintéticos. No usar chats de la agencia para la demo.

La cuenta 2 también conserva la bandeja API 3 de la prueba del portal de
Smarth House. Su webhook temporal fue retirado; no es la bandeja de uniformes.

## Qué sigue pendiente

El [plan de uniformes](demo-uniformes-plan.md) conserva el alcance aprobado
y la lista completa de avances. Siguen pendientes dos líneas/bandejas,
simulador, persistencia independiente de cotizaciones y prueba del bloqueo
de borrado de conversaciones **y mensajes individuales** en un Chatwoot
aislado. No probar ese bloqueo modificando el servicio de la campaña.

La guía vieja y `scripts/probar_bandeja_demo.py` describen el escenario de
libreta/taza. Su plantilla ahora está en
`prompts/plantillas/cliente_demo.md`; no sustituir el prompt de uniformes
para ejecutar esa prueba histórica. `scripts/probar_memoria_demo.py` usa
esa plantilla con un modelo falso y se limita a su conversación sintética
en `memoria_demo`; tampoco es una prueba del catálogo actual.

Antes de incorporar al cliente real, usar la
[metodología común](metodologia-clientes.md) y revisar
[operación](operacion.md). No recrear cuentas o bases existentes ni modificar
Smarth House como parte del trabajo para este prospecto.
