# Despliegue desde Codex, Claude o una terminal

Los dos agentes usan el mismo archivo local de credenciales y el mismo
comando. `CLAUDE.md` remite a `AGENTS.md`, donde se indica este procedimiento.
No hace falta instalar un plugin de Coolify.

## Conectar esta computadora una vez

1. En Coolify, seleccioná el equipo que administra `agente-ia`.
2. Abrí **Keys & Tokens → API Tokens**. Creá un token llamado, por ejemplo,
   `agentes-despliegue-pc`, con **Read y Deploy** y una vigencia adecuada.
   Si la versión del panel solo permite Deploy por separado, creá también
   uno Read y usá `COOLIFY_READ_TOKEN` para el segundo. No hace falta Root,
   Write ni acceso a secretos del servidor.
3. En la raíz del proyecto, guardá el valor en **`.env.coolify.local`**:

   ```dotenv
   COOLIFY_TOKEN=
   COOLIFY_READ_TOKEN=
   ```

   Pegá el valor después del primer `=`. Dejá la segunda variable vacía si
   el primero ya permite lectura. No pegues el token en un chat ni en una
   línea de comandos. Si reutilizás uno anterior, debe seguir vigente.
4. La API de Coolify debe estar habilitada. Si devuelve 403, revisá el equipo,
   los permisos y **Settings → Configuration → Advanced → API Access**, así
   como una posible restricción de IP. No desactives la verificación TLS.

El archivo ya está excluido por `.gitignore` y `.dockerignore`. Se lee cada
vez que se ejecuta el comando, sin reiniciar los agentes. Las variables del
proceso tienen prioridad si también están configuradas. En otra computadora
hay que configurar el acceso local una vez: la credencial no viaja con Git.

## Usarlo

Desde la raíz, en Windows:

```powershell
.\.venv\Scripts\python.exe scripts\desplegar.py comprobar
.\.venv\Scripts\python.exe scripts\desplegar.py desplegar
```

Con un entorno virtual activado también sirve `python scripts/desplegar.py`.

- **comprobar:** verifica la credencial de lectura, el destino y que `main`
  esté limpia y coincida con GitHub. No prueba el permiso Deploy mediante
  una mutación; ese permiso se comprueba al desplegar.
- **desplegar:** corre los tests sin gastar tokens, vuelve a comprobar la
  revisión, inicia el despliegue y consulta su estado por hasta cinco minutos.
  Solo informa éxito si terminó con el commit esperado y la salud pública
  devuelve el prompt de ese commit.
- **estado:** sigue un despliegue ya iniciado, sin crear otro. Usá el ID y el
  commit completos que imprimió el comando anterior:

  ```text
  python scripts/desplegar.py estado ID_DEL_DESPLIEGUE --commit COMMIT_COMPLETO
  ```

En `estado`, salida 0 significa terminado y verificado, 2 significa pendiente
y 1 indica un error que revisar. Si una llamada de despliegue pierde la
conexión, revisá el historial antes de repetir: Coolify pudo haberla recibido.
La compatibilidad con el método GET de versiones anteriores solo se intenta
cuando POST devuelve específicamente HTTP 405.

El comando está limitado a `agente-ia`, rama `main`, del repositorio
`Kenneth-Bust/ia-prueba`. No modifica el piloto, la memoria, las etiquetas de
Chatwoot ni las variables de producción. La comprobación de salud no
sustituye una prueba funcional desde WhatsApp ni confirma el saldo de Gemini.

## Referencias

- [Crear y administrar tokens de Coolify](https://coolify.io/docs/core/security/credentials/api-tokens)
- [Desplegar por API](https://coolify.io/docs/api/endpoints/deployments/deploy-by-tag-or-uuid)
- [Consultar un despliegue](https://coolify.io/docs/api/endpoints/deployments/get-deployment-by-uuid)
