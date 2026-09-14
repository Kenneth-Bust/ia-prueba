"""El portal de catálogos: donde cada negocio carga lo que ofrece su bot.

Es una aplicación aparte del agente y **no importa nada de `agente`** a
propósito. `agente.config` carga el `.env` del bot de la agencia, con su
clave de Gemini; el portal no la necesita y no tiene por qué tenerla en
memoria. Lo único que comparten es el repositorio.

Recorrido:

    el dueño carga ítems, fotos y «Mi negocio»     (app.py + static/)
      → se valida todo lo que llega                  (modelo.py, almacen.py)
      → se guarda por negocio                        (repositorio.py, postgres.py)
      → «Publicar» congela una versión
      → cada bot lee solo la última versión de su negocio, con su clave

El diseño está en docs/portal.md.
"""
