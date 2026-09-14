"""Chat local para mostrar la demo escribiendo como si fueras el cliente.

    python scripts/chat_demo.py

Abre http://127.0.0.1:8765. Cada «Nueva conversación» crea un contacto
sintético en la bandeja API Pruebas Demo, y lo que escribís entra como un
mensaje del cliente: bot-demo lo contesta de verdad por Chatwoot, con Gemini
y con las fotos del catálogo. Es la misma conversación que se ve en la
bandeja, así que podés tener las dos pantallas abiertas a la vez.

Solo escucha en tu computadora. La credencial de Chatwoot se lee de
.env.demo.local y nunca llega al navegador. Usa las comprobaciones de
probar_bandeja_demo.py: no admite la cuenta de la agencia, usuarios
SuperAdmin ni otra bandeja que la API de prueba. Cada mensaje consume Gemini.
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from uuid import uuid4

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "scripts"))

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, Response  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from agente.config import variables_demo  # noqa: E402
from probar_bandeja_demo import validar_destino  # noqa: E402

PUERTO = 8765
HOSTS_PERMITIDOS = {f"127.0.0.1:{PUERTO}", f"localhost:{PUERTO}"}
LARGO_MAXIMO = 1000
MAXIMO_FOTO = 6 * 1024 * 1024


class SinSalirDeChatwoot(urllib.request.HTTPRedirectHandler):
    """Deja seguir redirecciones solo dentro del mismo Chatwoot.

    urllib reenvía los headers al destino de la redirección: sin esto, una
    foto guardada en otro servidor se llevaría la credencial de la cuenta.
    """

    def __init__(self, origen: str) -> None:
        self.origen = urllib.parse.urlsplit(origen).netloc

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).netloc != self.origen:
            raise urllib.error.URLError("La foto redirige fuera de Chatwoot.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ChatwootDemo:
    """La conversación sintética activa, contra la bandeja API de la demo."""

    def __init__(self, valores: dict) -> None:
        self.url = valores.get("CHATWOOT_URL", "").rstrip("/")
        self.token = valores.get("CHATWOOT_TOKEN", "")
        self.prefijo, self.bandeja = validar_destino(valores, self.consultar)
        self.conversacion: int | None = None
        self._candado = threading.Lock()

    def consultar(self, metodo: str, camino: str, datos=None) -> dict:
        pedido = urllib.request.Request(
            self.url + camino,
            data=json.dumps(datos).encode("utf-8") if datos is not None else None,
            method=metodo,
            headers={"api_access_token": self.token, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(pedido, timeout=20) as respuesta:
            return json.load(respuesta)

    def nueva_conversacion(self) -> int:
        with self._candado:
            creado = self.consultar("POST", f"{self.prefijo}/contacts", {
                "inbox_id": self.bandeja,
                "name": "Cliente de la demo",
                "identifier": f"chat-demo-{uuid4().hex}",
            })
            datos = creado.get("payload", creado)
            contacto = datos[0] if isinstance(datos, list) else datos.get("contact", datos)
            vinculo = next(
                (
                    v for v in contacto.get("contact_inboxes", [])
                    if v.get("inbox", {}).get("id") == self.bandeja
                ),
                None,
            )
            if not vinculo and isinstance(datos, dict):
                vinculo = datos.get("contact_inbox")
            if not vinculo or not vinculo.get("source_id") or not contacto.get("id"):
                raise RuntimeError("Chatwoot no informó el vínculo del contacto con la bandeja.")
            conversacion = self.consultar("POST", f"{self.prefijo}/conversations", {
                "source_id": vinculo["source_id"],
                "inbox_id": self.bandeja,
                "contact_id": contacto["id"],
                "status": "open",
            })
            self.conversacion = int(conversacion["id"])
            return self.conversacion

    def enviar(self, texto: str) -> None:
        conversacion = self._actual()
        # Sin reintento: una respuesta perdida no significa que Chatwoot no lo
        # recibió, y repetirlo duplicaría el mensaje y el gasto de Gemini.
        self.consultar("POST", f"{self.prefijo}/conversations/{conversacion}/messages", {
            "content": texto,
            "message_type": "incoming",
            "private": False,
        })

    def mensajes(self) -> tuple[int, list[dict]]:
        conversacion = self._actual()
        datos = self.consultar("GET", f"{self.prefijo}/conversations/{conversacion}/messages")
        return conversacion, mensajes_para_pantalla(datos.get("payload", []))

    def foto(self, mensaje_id: int, adjunto_id: int) -> tuple[bytes, str]:
        """Baja una foto de la conversación activa. El navegador nunca manda una URL."""
        conversacion = self._actual()
        datos = self.consultar("GET", f"{self.prefijo}/conversations/{conversacion}/messages")
        url = next(
            (
                adjunto.get("data_url")
                for mensaje in datos.get("payload", [])
                if mensaje.get("id") == mensaje_id
                for adjunto in mensaje.get("attachments") or []
                if adjunto.get("id") == adjunto_id and adjunto.get("file_type") == "image"
            ),
            None,
        )
        if not url or urllib.parse.urlsplit(url).netloc != urllib.parse.urlsplit(self.url).netloc:
            raise LookupError("La foto no pertenece a esta conversación.")

        cliente = urllib.request.build_opener(SinSalirDeChatwoot(self.url))
        pedido = urllib.request.Request(url, headers={"api_access_token": self.token})
        with cliente.open(pedido, timeout=30) as respuesta:
            contenido = respuesta.read(MAXIMO_FOTO + 1)
            tipo = (respuesta.headers.get("Content-Type") or "").split(";")[0].strip()
        if len(contenido) > MAXIMO_FOTO or not tipo.startswith("image/"):
            raise LookupError("El archivo no es una foto válida.")
        return contenido, tipo

    def _actual(self) -> int:
        if self.conversacion is None:
            raise LookupError("Todavía no empezaste una conversación.")
        return self.conversacion


def mensajes_para_pantalla(payload: list) -> list[dict]:
    """Deja solo lo que ve el cliente: sin notas privadas ni avisos de actividad."""
    salida: list[dict] = []
    for mensaje in sorted(payload, key=lambda m: m.get("id") or 0):
        if mensaje.get("private"):
            continue
        tipo = mensaje.get("message_type")
        if tipo in (0, "incoming"):
            autor = "cliente"
        elif tipo in (1, "outgoing"):
            autor = "negocio"
        else:
            continue
        fotos = [
            {"mensaje": mensaje["id"], "adjunto": adjunto["id"]}
            for adjunto in mensaje.get("attachments") or []
            if adjunto.get("file_type") == "image" and adjunto.get("id")
        ]
        texto = mensaje.get("content") or ""
        if not texto and not fotos:
            continue
        salida.append({"id": mensaje.get("id"), "autor": autor, "texto": texto, "fotos": fotos})
    return salida


class MensajeNuevo(BaseModel):
    texto: str = Field(min_length=1, max_length=LARGO_MAXIMO)


def crear_app(demo) -> FastAPI:
    app = FastAPI(title="Chat de la demo", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def solo_esta_pagina(pedido: Request, siguiente):
        # El Host corta el DNS rebinding. El header propio obliga a una
        # verificación CORS que otra página abierta en el navegador no pasa:
        # sin esto cualquier sitio podría escribir en la demo y gastar Gemini.
        if pedido.headers.get("host") not in HOSTS_PERMITIDOS:
            return JSONResponse({"error": "host no permitido"}, status_code=400)
        if pedido.url.path.startswith("/api/") and pedido.headers.get("x-chat-demo") != "1":
            return JSONResponse({"error": "no autorizado"}, status_code=403)
        return await siguiente(pedido)

    @app.get("/", response_class=HTMLResponse)
    def pagina() -> str:
        return PAGINA

    @app.post("/api/nueva")
    def nueva() -> dict:
        return {"conversacion": _o_502(demo.nueva_conversacion)}

    @app.post("/api/mensaje")
    def mensaje(nuevo: MensajeNuevo) -> dict:
        _o_502(demo.enviar, nuevo.texto.strip())
        return {"estado": "enviado"}

    @app.get("/api/mensajes")
    def mensajes() -> dict:
        conversacion, lista = _o_502(demo.mensajes)
        return {"conversacion": conversacion, "mensajes": lista}

    @app.get("/api/foto/{mensaje_id}/{adjunto_id}")
    def foto(mensaje_id: int, adjunto_id: int) -> Response:
        contenido, tipo = _o_502(demo.foto, mensaje_id, adjunto_id)
        return Response(contenido, media_type=tipo, headers={"Cache-Control": "private, max-age=3600"})

    return app


def _o_502(funcion, *argumentos):
    try:
        return funcion(*argumentos)
    except LookupError as error:
        raise HTTPException(404, str(error)) from None
    except Exception as error:
        # El detalle queda en esta consola; la página solo avisa que falló.
        print(f"Chatwoot falló: {type(error).__name__}: {error}", file=sys.stderr)
        raise HTTPException(502, "Chatwoot no respondió. Probá de nuevo en unos segundos.") from None


PAGINA = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Uniformes y Sublimación Demo · chat</title>
<style>
  :root { --fondo:#eef1f4; --panel:#ffffff; --texto:#17212b; --tenue:#667380; --borde:#d9dfe5;
          --cliente:#1f6f5c; --negocio:#ffffff; --acento:#1f6f5c; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--fondo); color:var(--texto);
         font-family:"Segoe UI", system-ui, -apple-system, sans-serif; }
  .app { max-width:760px; height:100vh; margin:0 auto; display:flex; flex-direction:column;
         background:var(--panel); border-left:1px solid var(--borde); border-right:1px solid var(--borde); }
  header { display:flex; align-items:center; gap:14px; padding:14px 20px; border-bottom:1px solid var(--borde); }
  .avatar { width:42px; height:42px; border-radius:50%; background:var(--acento); color:#fff;
            display:grid; place-items:center; font-weight:700; }
  .titulo { flex:1; min-width:0; }
  .titulo strong { display:block; font-size:16px; }
  .titulo span { font-size:13px; color:var(--tenue); }
  button { font:inherit; border-radius:8px; border:1px solid var(--borde); background:#fff;
           padding:8px 14px; cursor:pointer; color:var(--texto); }
  button.primario { background:var(--acento); color:#fff; border-color:var(--acento); }
  button:disabled { opacity:.5; cursor:default; }
  .aviso { padding:8px 20px; font-size:13px; color:#6b4e00; background:#fff6db; border-bottom:1px solid #f0e2b0; }
  .mensajes { flex:1; overflow-y:auto; padding:20px; display:flex; flex-direction:column; gap:8px; background:var(--fondo); }
  .vacio { margin:auto; text-align:center; color:var(--tenue); max-width:360px; line-height:1.5; }
  .globo { max-width:78%; padding:9px 12px; border-radius:12px; white-space:pre-wrap; line-height:1.45;
           font-size:15px; box-shadow:0 1px 1px rgba(0,0,0,.06); }
  .cliente { align-self:flex-end; background:var(--cliente); color:#fff; border-bottom-right-radius:4px; }
  .negocio { align-self:flex-start; background:var(--negocio); border-bottom-left-radius:4px; }
  .globo img { display:block; width:100%; max-width:320px; border-radius:8px; margin-bottom:6px; cursor:zoom-in; }
  .globo img:last-child { margin-bottom:0; }
  .esperando { align-self:flex-start; color:var(--tenue); font-size:13px; padding:4px 2px; }
  .sugerencias { display:flex; flex-wrap:wrap; gap:6px; padding:10px 20px 0; }
  .sugerencias button { font-size:13px; padding:6px 10px; border-radius:16px; }
  form { display:flex; gap:10px; padding:12px 20px 16px; }
  input { flex:1; font:inherit; padding:11px 14px; border-radius:22px; border:1px solid var(--borde); outline:none; }
  input:focus { border-color:var(--acento); }
  .error { color:#a3261b; font-size:13px; padding:0 20px 8px; min-height:18px; }
</style>
</head>
<body>
<div class="app">
  <header>
    <div class="avatar">US</div>
    <div class="titulo">
      <strong>Uniformes y Sublimación Demo</strong>
      <span id="estado">Sin conversación</span>
    </div>
    <button id="nueva" class="primario">Nueva conversación</button>
  </header>
  <div class="aviso">Demostración: productos, imágenes y precios ficticios. No se procesan compras.</div>
  <div class="mensajes" id="mensajes">
    <div class="vacio">Tocá «Nueva conversación» y escribí como si fueras un cliente.
      Las respuestas llegan del bot real, igual que en la bandeja de Chatwoot.</div>
  </div>
  <div class="sugerencias" id="sugerencias">
    <button type="button">¿Qué uniformes de fútbol tienen?</button>
    <button type="button">Mostrame el azul</button>
    <button type="button">18 del azul, talla M, con nombre y número</button>
    <button type="button">¿Y los de béisbol?</button>
    <button type="button">12 tazas con el diseño de muestra</button>
    <button type="button">Quiero el logo de mi equipo en 10 camisetas</button>
  </div>
  <form id="formulario">
    <input id="texto" maxlength="1000" autocomplete="off" placeholder="Escribí un mensaje" disabled>
    <button id="enviar" class="primario" disabled>Enviar</button>
  </form>
  <div class="error" id="error"></div>
</div>
<script>
const estado = { conversacion: null, mensajes: new Map(), enviando: false };
const $ = (id) => document.getElementById(id);

async function api(camino, opciones = {}) {
  const respuesta = await fetch(camino, {
    ...opciones,
    headers: { "X-Chat-Demo": "1", "Content-Type": "application/json", ...(opciones.headers || {}) },
  });
  if (!respuesta.ok) {
    let detalle = "No se pudo completar la acción.";
    try { detalle = (await respuesta.json()).detail || detalle; } catch (e) {}
    throw new Error(detalle);
  }
  return respuesta.json();
}

function mostrarError(texto) { $("error").textContent = texto || ""; }

function dibujar() {
  const caja = $("mensajes");
  const abajo = caja.scrollHeight - caja.scrollTop - caja.clientHeight < 80;
  caja.replaceChildren();
  const lista = [...estado.mensajes.values()].sort((a, b) => a.id - b.id);
  for (const mensaje of lista) {
    const globo = document.createElement("div");
    globo.className = "globo " + mensaje.autor;
    for (const foto of mensaje.fotos) {
      const imagen = document.createElement("img");
      imagen.src = `/api/foto/${foto.mensaje}/${foto.adjunto}`;
      imagen.alt = "Foto del catálogo";
      imagen.addEventListener("click", () => window.open(imagen.src, "_blank"));
      imagen.addEventListener("load", () => { caja.scrollTop = caja.scrollHeight; });
      globo.appendChild(imagen);
    }
    if (mensaje.texto) globo.appendChild(document.createTextNode(mensaje.texto));
    caja.appendChild(globo);
  }
  const ultimo = lista[lista.length - 1];
  if (ultimo && ultimo.autor === "cliente") {
    const espera = document.createElement("div");
    espera.className = "esperando";
    espera.textContent = "Esperando respuesta del bot…";
    caja.appendChild(espera);
  }
  if (abajo || (ultimo && ultimo.autor === "cliente")) caja.scrollTop = caja.scrollHeight;
}

async function actualizar() {
  if (!estado.conversacion) return;
  try {
    const datos = await api("/api/mensajes");
    if (datos.conversacion !== estado.conversacion) return;
    let cambio = false;
    for (const mensaje of datos.mensajes) {
      if (!estado.mensajes.has(mensaje.id)) { estado.mensajes.set(mensaje.id, mensaje); cambio = true; }
    }
    if (cambio) dibujar();
    mostrarError("");
  } catch (error) { mostrarError(error.message); }
}

$("nueva").addEventListener("click", async () => {
  $("nueva").disabled = true;
  mostrarError("");
  try {
    const datos = await api("/api/nueva", { method: "POST" });
    estado.conversacion = datos.conversacion;
    estado.mensajes.clear();
    $("estado").textContent = `Conversación ${datos.conversacion} en Chatwoot`;
    $("texto").disabled = false;
    $("enviar").disabled = false;
    $("mensajes").replaceChildren();
    $("texto").focus();
  } catch (error) { mostrarError(error.message); }
  finally { $("nueva").disabled = false; }
});

$("formulario").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const texto = $("texto").value.trim();
  if (!texto || !estado.conversacion || estado.enviando) return;
  estado.enviando = true;
  $("enviar").disabled = true;
  try {
    await api("/api/mensaje", { method: "POST", body: JSON.stringify({ texto }) });
    $("texto").value = "";
    await actualizar();
  } catch (error) { mostrarError(error.message); }
  finally { estado.enviando = false; $("enviar").disabled = false; $("texto").focus(); }
});

for (const boton of $("sugerencias").querySelectorAll("button")) {
  boton.addEventListener("click", () => { $("texto").value = boton.textContent; $("texto").focus(); });
}

setInterval(actualizar, 2000);
</script>
</body>
</html>
"""


def main() -> int:
    import uvicorn

    try:
        demo = ChatwootDemo(variables_demo())
    except Exception as error:
        print(f"No se pudo validar la bandeja de la demo: {error}", file=sys.stderr)
        return 1
    direccion = f"http://127.0.0.1:{PUERTO}"
    print(f"Bandeja validada. Abrí {direccion}  (Ctrl+C para cerrar)")
    threading.Timer(1.5, webbrowser.open, args=(direccion,)).start()
    uvicorn.run(crear_app(demo), host="127.0.0.1", port=PUERTO, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
