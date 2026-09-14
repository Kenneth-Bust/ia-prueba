"use strict";

// Portal de catálogos. Sin frameworks ni build: el DOM se arma a mano.
//
// Regla de este archivo: nunca innerHTML con datos. Todo texto que viene del
// servidor entra como nodo de texto (vía el()), así un nombre de producto con
// "<script>" se muestra tal cual y no se ejecuta. La política de seguridad
// del servidor, además, no deja correr scripts en línea.

const $ = (id) => document.getElementById(id);

const SECCIONES_ADMINISTRADOR = [
  ["catalogo", "Catálogo", "catalogo"],
  ["negocio", "Mi negocio", "negocio"],
  ["reglas", "Reglas de precio", "reglas"],
  ["publicar", "Publicar", "publicar"],
];
const SECCIONES_EMPLEADO = [
  ["publicado", "Catálogo publicado", "catalogo"],
  ["negocio-publicado", "Mi negocio", "negocio"],
];
const PLURALES = { producto: "Productos", servicio: "Servicios", promocion: "Promociones" };
const MONEDAS_LARGAS = { USD: "Dólares (US$)", NIO: "Córdobas (C$)" };
const MAXIMO_FOTO = 5 * 1024 * 1024;
const MAXIMO_FOTOS = 5;

const ICONOS = {
  marca: { caja: "0 0 32 32", trazo: 2.4, d: ["M4 15 16 5l12 10v12H4z", "M11 27v-6M16 27v-9M21 27v-4"] },
  catalogo: { d: ["M3 12V4h8l10 10-8 8z", "M9 8.5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0"] },
  negocio: { d: ["M4 10h16v10H4z", "M3 10l2-6h14l2 6", "M10 20v-5h4v5"] },
  reglas: { d: ["M19 5 5 19", "M9.5 7a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0", "M19.5 17a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0"] },
  publicar: { d: ["M12 16V4", "m7 9 5-5 5 5", "M5 20h14"] },
  mas: { trazo: 2, d: ["M12 5v14M5 12h14"] },
  buscar: { d: ["M18 11a7 7 0 1 1-14 0 7 7 0 0 1 14 0", "m20 20-3.5-3.5"] },
  editar: { d: ["M4 20h4L19 9l-4-4L4 16z"] },
  candado: { d: ["M5 11h14v10H5z", "M8 11V8a4 4 0 0 1 8 0v3"] },
  foto: { d: ["M3 4h18v16H3z", "M11 10a2 2 0 1 1-4 0 2 2 0 0 1 4 0", "m21 17-5-5-9 8"] },
  mensaje: { d: ["M4 5h16v11H9l-5 4z"] },
  info: { d: ["M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0", "M12 11v5", "M12 8h.01"] },
};

class ErrorDelPortal extends Error {
  constructor(mensaje, estado) {
    super(mensaje);
    this.estado = estado;
  }
}

const estado = {
  sesion: null,
  vista: "",
  items: [],
  ajustes: null,
  cambiosSinPublicar: false,
  // Hay cambios escritos en pantalla que todavía no se guardaron.
  sucio: false,
};

document.addEventListener("DOMContentLoaded", iniciar);
window.addEventListener("beforeunload", (evento) => {
  if (estado.sucio) {
    evento.preventDefault();
    evento.returnValue = "";
  }
});

// -- Piezas chicas ---------------------------------------------------------------

function el(etiqueta, atributos = {}, ...hijos) {
  const nodo = document.createElement(etiqueta);
  for (const [clave, valor] of Object.entries(atributos)) {
    if (valor === null || valor === undefined || valor === false) continue;
    if (clave === "class") nodo.className = valor;
    else if (clave.startsWith("on")) nodo.addEventListener(clave.slice(2), valor);
    else if (clave === "value") nodo.value = valor;
    else if (clave === "checked") nodo.checked = true;
    else nodo.setAttribute(clave, valor === true ? "" : String(valor));
  }
  for (const hijo of hijos.flat(Infinity)) {
    if (hijo === null || hijo === undefined || hijo === false) continue;
    nodo.append(hijo instanceof Node ? hijo : document.createTextNode(String(hijo)));
  }
  return nodo;
}

// replaceChildren convierte en texto todo lo que no sea un nodo: un null
// aparece escrito como "null" y una lista como "[object HTMLDivElement]".
// Por eso cada repintado pasa por acá, que descarta lo vacío y aplana listas.
function pintarEn(nodo, ...hijos) {
  nodo.replaceChildren(...hijos.flat(Infinity).filter((hijo) => hijo !== null && hijo !== undefined && hijo !== false));
}

function icono(nombre, tamano = 18) {
  const datos = ICONOS[nombre];
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const atributos = {
    width: tamano, height: tamano, viewBox: datos.caja || "0 0 24 24", fill: "none",
    stroke: "currentColor", "stroke-width": datos.trazo || 1.8,
    "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true",
  };
  for (const [clave, valor] of Object.entries(atributos)) svg.setAttribute(clave, valor);
  for (const d of datos.d) {
    const trazo = document.createElementNS("http://www.w3.org/2000/svg", "path");
    trazo.setAttribute("d", d);
    svg.append(trazo);
  }
  return svg;
}

async function api(metodo, ruta, cuerpo, { silencioso = false } = {}) {
  const pedido = { method: metodo, headers: {}, credentials: "same-origin" };
  // El servidor rechaza cualquier cambio sin esta cabecera: otra página no
  // puede ponerla, así que no puede hacer cambios en tu nombre.
  if (metodo !== "GET") pedido.headers["X-Portal"] = "1";
  if (cuerpo instanceof Blob) {
    pedido.body = cuerpo;
    pedido.headers["Content-Type"] = cuerpo.type || "application/octet-stream";
  } else if (cuerpo !== undefined) {
    pedido.body = JSON.stringify(cuerpo);
    pedido.headers["Content-Type"] = "application/json";
  }

  let respuesta;
  try {
    respuesta = await fetch(ruta, pedido);
  } catch {
    throw new ErrorDelPortal("No hay conexión con el portal. Revisá tu internet y probá de nuevo.", 0);
  }
  let datos = null;
  try {
    datos = await respuesta.json();
  } catch {
    datos = null; // una respuesta sin JSON (por ejemplo, del proxy) usa el mensaje genérico
  }
  if (respuesta.status === 401 && !silencioso) {
    mostrarLogin(datos?.error);
    throw new ErrorDelPortal(datos?.error || "Iniciá sesión.", 401);
  }
  if (!respuesta.ok) {
    throw new ErrorDelPortal(datos?.error || `Algo falló (error ${respuesta.status}). Probá de nuevo.`, respuesta.status);
  }
  return datos;
}

let temporizadorDeAviso;
function avisar(texto, esError = false) {
  const aviso = $("toast");
  aviso.textContent = texto;
  aviso.className = esError ? "toast toast-error" : "toast";
  aviso.hidden = false;
  clearTimeout(temporizadorDeAviso);
  temporizadorDeAviso = setTimeout(() => { aviso.hidden = true; }, esError ? 7000 : 4500);
}

function avisarError(error) {
  // El 401 ya llevó a la pantalla de inicio de sesión con su propio mensaje.
  if (error.estado !== 401) avisar(error.message, true);
}

const esAdministrador = () => estado.sesion?.rol === "administrador";
const simbolo = (moneda) => ({ USD: "US$", NIO: "C$" })[moneda || estado.ajustes?.moneda || "USD"] || "US$";
const dinero = (importe, moneda) => `${simbolo(moneda)} ${importe}`;

function fecha(iso) {
  if (!iso) return "";
  const [anio, mes, dia] = iso.split("-");
  return `${dia}/${mes}/${anio}`;
}

const conPunto = (texto) => (/[.!?…»]$/.test(texto) ? texto : `${texto}.`);

function fechaHora(iso) {
  const valor = new Date(iso);
  return Number.isNaN(valor.getTime()) ? iso : valor.toLocaleString("es-NI", { dateStyle: "medium", timeStyle: "short" });
}

function hoyISO() {
  const hoy = new Date();
  return `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, "0")}-${String(hoy.getDate()).padStart(2, "0")}`;
}

function campo(etiqueta, control, { ancho = false, ayuda = "" } = {}) {
  return el("label", { class: ancho ? "campo ancho-completo" : "campo" },
    el("span", {}, etiqueta), control, ayuda ? el("small", {}, ayuda) : null);
}

function interruptor(control, titulo, texto) {
  return el("label", { class: "interruptor" },
    el("span", { class: "interruptor-texto" }, el("strong", {}, titulo), el("span", {}, texto)), control);
}

function encabezado({ titulo, texto = "", migas = "", acciones = [] }) {
  return el("div", { class: "encabezado" },
    el("div", { class: "encabezado-texto" },
      migas ? el("span", { class: "migas" }, migas) : null,
      el("h1", {}, titulo),
      texto ? el("p", {}, texto) : null),
    el("div", { class: "acciones" }, acciones));
}

function estadoDePublicacion() {
  return el("span", { id: "estado-cabecera" }, contenidoDelEstado());
}

function contenidoDelEstado() {
  return estado.cambiosSinPublicar
    ? el("button", { class: "boton boton-menta", type: "button", onclick: () => irA("publicar") }, icono("publicar", 16), "Cambios sin publicar")
    : el("span", { class: "estado-publicacion" }, "Todo publicado");
}

function botonPrimario(texto, accion) {
  return el("button", { class: "boton boton-primario", type: "button", onclick: (evento) => accion(evento.currentTarget) }, texto);
}

// -- Inicio y sesión --------------------------------------------------------------

async function iniciar() {
  $("logo-login").append(icono("marca", 36));
  $("icono-candado").append(icono("candado", 20));
  $("form-login").addEventListener("submit", entrar);
  $("boton-salir").addEventListener("click", salir);

  let sesion = null;
  try {
    sesion = await api("GET", "/api/sesion", undefined, { silencioso: true });
  } catch {
    sesion = null; // sin sesión abierta: se muestra el inicio de sesión
  }
  $("cargando").hidden = true;
  if (sesion) {
    estado.sesion = sesion;
    await mostrarApp();
  } else {
    mostrarLogin();
  }
}

async function entrar(evento) {
  evento.preventDefault();
  const boton = evento.target.querySelector("button[type=submit]");
  const error = $("login-error");
  error.hidden = true;
  boton.disabled = true;
  try {
    estado.sesion = await api(
      "POST", "/api/entrar",
      { correo: $("login-correo").value, clave: $("login-clave").value },
      { silencioso: true },
    );
    $("login-clave").value = "";
    await mostrarApp();
  } catch (e) {
    error.textContent = e.message;
    error.hidden = false;
  } finally {
    boton.disabled = false;
  }
}

function mostrarLogin(mensaje) {
  estado.sesion = null;
  estado.sucio = false;
  $("cargando").hidden = true;
  $("pantalla-app").hidden = true;
  $("pantalla-login").hidden = false;
  const error = $("login-error");
  error.textContent = mensaje || "";
  error.hidden = !mensaje;
  $("login-correo").focus();
}

async function salir() {
  if (estado.sucio && !confirm("Tenés cambios sin guardar. ¿Salir igual?")) return;
  try {
    await api("POST", "/api/salir", undefined, { silencioso: true });
  } catch {
    // Aunque falle, la pantalla vuelve al inicio: la sesión vence sola.
  }
  mostrarLogin();
}

async function mostrarApp() {
  $("pantalla-login").hidden = true;
  $("pantalla-app").hidden = false;
  document.title = `${estado.sesion.negocio.nombre} · Catálogos`;
  estado.items = [];
  estado.ajustes = null;
  pintarLateral();
  if (!esAdministrador()) {
    await irA("publicado", { forzar: true });
    return;
  }
  try {
    await Promise.all([cargarAjustes(), refrescarEstado()]);
  } catch (e) {
    avisarError(e);
  }
  await irA("catalogo", { forzar: true });
}

async function cambiarNegocio(negocio) {
  if (estado.sucio && !confirm("Tenés cambios sin guardar. ¿Cambiar de negocio igual?")) {
    pintarLateral();
    return;
  }
  try {
    estado.sesion = await api("POST", "/api/sesion/negocio", { negocio });
    estado.sucio = false;
    await mostrarApp();
  } catch (e) {
    avisarError(e);
    pintarLateral();
  }
}

function pintarLateral() {
  const { sesion } = estado;
  pintarEn($("marca-app"), icono("marca", 30),
    el("div", { class: "marca-nombre" }, el("strong", {}, "Smarth House"), el("span", {}, "Catálogos")));

  const tarjeta = $("tarjeta-negocio");
  pintarEn(tarjeta, el("span", {}, "Negocio"), el("strong", {}, sesion.negocio.nombre));
  if (sesion.negocios.length > 1) {
    tarjeta.append(el("select", { "aria-label": "Cambiar de negocio", onchange: (e) => cambiarNegocio(e.target.value) },
      sesion.negocios.map((n) => el("option", { value: n.id, selected: n.id === sesion.negocio.id }, n.nombre))));
  }

  const iniciales = sesion.usuario.nombre.split(/\s+/).filter(Boolean).slice(0, 2)
    .map((parte) => parte[0].toUpperCase()).join("") || "?";
  pintarEn($("usuario"), 
    el("div", { class: esAdministrador() ? "avatar" : "avatar avatar-consulta" }, iniciales),
    el("div", { class: "usuario-datos" },
      el("strong", { title: sesion.usuario.correo }, sesion.usuario.nombre),
      el("span", {}, esAdministrador() ? "Administrador" : "Empleado · solo consulta")));
  pintarNav();
}

function pintarNav() {
  const secciones = esAdministrador() ? SECCIONES_ADMINISTRADOR : SECCIONES_EMPLEADO;
  pintarEn($("nav"), ...secciones.map(([vista, texto, nombreIcono]) => {
    const activa = estado.vista === vista || (vista === "catalogo" && estado.vista === "editor");
    return el("button", { type: "button", "aria-current": activa ? "page" : null, onclick: () => irA(vista) },
      icono(nombreIcono), texto,
      vista === "publicar" && estado.cambiosSinPublicar ? el("span", { class: "marca-cambios", title: "Hay cambios sin publicar" }) : null);
  }));
}

async function cargarAjustes() {
  estado.ajustes = await api("GET", "/api/ajustes");
}

async function refrescarEstado() {
  const datos = await api("GET", "/api/estado");
  estado.cambiosSinPublicar = datos.cambios_sin_publicar;
  pintarNav();
  const lugar = $("estado-cabecera");
  if (lugar) pintarEn(lugar, contenidoDelEstado());
  return datos;
}

function refrescarEstadoSinFrenar() {
  // Es solo el aviso de «cambios sin publicar»: lo guardado ya quedó
  // guardado, y un error acá confundiría más de lo que ayuda.
  refrescarEstado().catch(() => {});
}

const VISTAS = {
  catalogo: vistaCatalogo,
  editor: vistaEditor,
  negocio: vistaNegocio,
  reglas: vistaReglas,
  publicar: vistaPublicar,
  publicado: vistaPublicado,
  "negocio-publicado": vistaNegocioPublicado,
};

async function irA(vista, { forzar = false, datos = null } = {}) {
  if (!forzar && estado.sucio && !confirm("Tenés cambios sin guardar. ¿Salir igual?")) return;
  estado.sucio = false;
  estado.vista = vista;
  pintarNav();
  const principal = $("principal");
  pintarEn(principal, el("div", { class: "cargando" }, "Cargando…"));
  try {
    await VISTAS[vista](principal, datos);
    estado.sucio = false;
  } catch (e) {
    if (e.estado === 401) return;
    pintarEn(principal, el("div", { class: "vacio" },
      el("strong", {}, "No se pudo cargar esta sección."), el("span", {}, e.message),
      el("button", { class: "boton", type: "button", onclick: () => irA(vista, { forzar: true, datos }) }, "Reintentar")));
  }
  window.scrollTo(0, 0);
}

// -- Filas del catálogo -----------------------------------------------------------------

function miniatura(fotos) {
  if (fotos?.length) return el("img", { class: "miniatura", src: `/api/fotos/${fotos[0].id}`, alt: "", loading: "lazy" });
  return el("div", { class: "miniatura" }, icono("foto", 20));
}

function valorDeOpcion(valor) {
  // Las opciones guardadas antes del recargo eran texto suelto.
  return typeof valor === "string" ? { valor, recargo: null } : valor;
}

function nombresDeLineas(codigos, lineas) {
  return (codigos || []).map((codigo) => lineas.find((l) => l.codigo === codigo)?.nombre).filter(Boolean);
}

function resumenDelItem(item, lineas = []) {
  const partes = [];
  if (item.descripcion) partes.push(item.descripcion);
  if (item.vigente_hasta) partes.push(`hasta el ${fecha(item.vigente_hasta)}`);
  if (item.extras.length) partes.push(`extras: ${item.extras.map((e) => e.nombre.toLowerCase()).join(", ")}`);
  const soloEn = nombresDeLineas(item.lineas, lineas);
  if (soloEn.length) partes.push(`solo en ${soloEn.join(", ")}`);
  return partes.join(" · ");
}

function tipoDelItem(item) {
  const tipo = estado.sesion.listas.tipos[item.tipo] || item.tipo;
  return item.categoria ? `${tipo} · ${item.categoria}` : tipo;
}

function resumenDeOpciones(item) {
  if (!item.opciones.length) return "—";
  return item.opciones.map((o) => `${o.nombre}: ${o.valores.map(valorDeOpcion)
    .map((v) => (v.recargo ? `${v.valor} (+${v.recargo})` : v.valor)).join(" · ")}`).join(" / ");
}

function celdaDePrecio(item, moneda) {
  return el("span", { class: "celda-precio ocultable-chico" },
    item.precio === null
      ? el("small", {}, "Lo cotiza una persona")
      : [`${item.precio_desde ? "Desde " : ""}${dinero(item.precio, item.moneda || moneda)}`,
        item.unidad ? el("small", {}, item.unidad) : null]);
}

function nombreConEstado(item) {
  return el("strong", {}, item.nombre, item.agotado ? el("span", { class: "pill pill-aviso pill-en-linea" }, "Agotado") : null);
}

function filaDeEncabezado(empleado = false) {
  return el("div", { class: "fila fila-encabezado" },
    el("span", {}, "Foto"), el("span", {}, "Ítem"),
    el("span", { class: "ocultable" }, "Código"), el("span", { class: "ocultable" }, "Tipo"),
    el("span", { class: "celda-precio ocultable-chico" }, "Precio"),
    el("span", { class: "ocultable" }, "Opciones"),
    el("span", { class: "ocultable" }, empleado ? "Estado" : "Activo"),
    empleado ? null : el("span", {}));
}

// -- Catálogo (administrador) --------------------------------------------------------------

async function vistaCatalogo(principal) {
  const [items, perfil] = await Promise.all([api("GET", "/api/items"), api("GET", "/api/perfil")]);
  estado.items = items;
  const { lineas } = perfil;
  let texto = "";
  let tipo = "";
  let linea = "";
  const chips = el("div", { class: "chips" });
  const cuerpo = el("div", { class: "columna" });
  const agregar = () => irA("editor");

  function pintar() {
    const tipos = Object.keys(PLURALES).filter((t) => estado.items.some((i) => i.tipo === t));
    pintarEn(chips, ...[["", `Todos · ${estado.items.length}`],
      ...tipos.map((t) => [t, `${PLURALES[t]} · ${estado.items.filter((i) => i.tipo === t).length}`])]
      .map(([valor, rotulo]) => el("button", {
        type: "button", class: "chip", "aria-pressed": String(tipo === valor),
        onclick: () => { tipo = valor; pintar(); },
      }, rotulo)));

    if (!estado.items.length) {
      pintarEn(cuerpo, el("div", { class: "tabla" }, el("div", { class: "vacio" },
        el("strong", {}, "Todavía no cargaste nada"),
        el("span", {}, "Empezá por lo que más te consultan: una promoción, un producto o un servicio."),
        el("button", { class: "boton boton-primario", type: "button", onclick: agregar }, icono("mas", 16), "Agregar el primero"))));
      return;
    }
    const visibles = estado.items.filter((i) => (!tipo || i.tipo === tipo)
      && (!linea || !i.lineas?.length || i.lineas.includes(linea))
      && (!texto || `${i.nombre} ${i.sku} ${i.categoria}`.toLowerCase().includes(texto)));
    const activos = estado.items.filter((i) => i.activo).length;
    const descuentos = estado.ajustes?.descuentos || [];
    pintarEn(cuerpo, 
      el("div", { class: "tabla" }, filaDeEncabezado(),
        visibles.length ? visibles.map((item) => filaDelCatalogo(item, lineas)) : el("div", { class: "vacio" }, "Nada coincide con la búsqueda.")),
      el("div", { class: "pie-tabla" },
        el("span", {}, `${activos} activos de ${estado.items.length}`),
        el("span", {}, descuentos.length
          ? `Descuentos: ${descuentos.map((d) => `desde ${d.desde} unidades ${d.porcentaje} %`).join(" · ")}`
          : "Sin descuentos por cantidad")));
  }

  pintarEn(principal, 
    encabezado({
      titulo: "Catálogo",
      texto: "Lo que cargás acá es lo único que tu bot ofrece por WhatsApp: productos, servicios y promociones, con sus fotos y precios.",
      acciones: [estadoDePublicacion(), el("button", { class: "boton boton-primario", type: "button", onclick: agregar }, icono("mas", 16), "Agregar")],
    }),
    el("div", { class: "filtros" },
      el("label", { class: "buscador" }, icono("buscar"),
        el("input", { type: "search", placeholder: "Buscar por nombre, código o categoría", "aria-label": "Buscar",
          oninput: (e) => { texto = e.target.value.trim().toLowerCase(); pintar(); } })),
      chips,
      lineas.length
        ? el("select", { class: "filtro-linea", "aria-label": "Filtrar por línea o sucursal",
          onchange: (e) => { linea = e.target.value; pintar(); } },
        el("option", { value: "" }, "Todas las líneas"), lineas.map((l) => el("option", { value: l.codigo }, l.nombre)))
        : null),
    cuerpo);
  pintar();
}

function filaDelCatalogo(item, lineas = []) {
  const resumen = resumenDelItem(item, lineas);
  return el("div", { class: "fila" },
    miniatura(item.fotos),
    el("div", { class: "nombre-item" }, nombreConEstado(item), el("span", { title: resumen }, resumen || tipoDelItem(item))),
    el("span", { class: "celda mono ocultable" }, item.sku),
    el("span", { class: "celda ocultable" }, tipoDelItem(item)),
    celdaDePrecio(item),
    el("span", { class: "celda-opciones ocultable" }, resumenDeOpciones(item)),
    el("span", { class: item.activo ? "punto punto-encendido ocultable" : "punto ocultable", role: "img", "aria-label": item.activo ? "Activo" : "Apagado", title: item.activo ? "Activo" : "Apagado" }),
    el("button", { class: "editar", type: "button", onclick: () => irA("editor", { datos: item }) }, icono("editar", 15), "Editar"));
}

// -- Editor de un ítem ------------------------------------------------------------------------

async function vistaEditor(principal, original) {
  if (!estado.ajustes) await cargarAjustes();
  const { lineas } = await api("GET", "/api/perfil");
  const nuevo = !original;
  const b = original ? structuredClone(original) : {
    tipo: "producto", sku: "", nombre: "", categoria: "", descripcion: "", precio: null, moneda: estado.ajustes?.moneda || "USD",
    precio_desde: false, unidad: "", vigente_desde: null, vigente_hasta: null, opciones: [], extras: [], lineas: [],
    cotizacion_automatica: false, agotado: false, activo: true, fotos: [],
  };
  // En pantalla cada valor de opción es {valor, recargo}, con el recargo como texto editable.
  b.opciones = b.opciones.map((o) => ({
    nombre: o.nombre, valores: o.valores.map(valorDeOpcion).map((v) => ({ valor: v.valor, recargo: v.recargo ?? "" })),
  }));
  b.lineas = b.lineas || [];

  const tipo = el("select", {}, Object.entries(estado.sesion.listas.tipos)
    .map(([valor, texto]) => el("option", { value: valor, selected: b.tipo === valor }, texto)));
  const sku = el("input", { type: "text", value: b.sku, maxlength: 32, disabled: !nuevo, placeholder: "PLAN-45", spellcheck: "false" });
  const nombre = el("input", { type: "text", value: b.nombre, maxlength: 120 });
  const categoria = el("input", { type: "text", value: b.categoria, maxlength: 60, placeholder: "Opcional" });
  const unidad = el("input", { type: "text", value: b.unidad, maxlength: 40, placeholder: "por unidad, al mes, por persona" });
  const precio = el("input", { type: "text", inputmode: "decimal", value: b.precio ?? "", placeholder: "0.00", "aria-label": "Precio" });
  const moneda = el("select", { "aria-label": "Moneda del precio" },
    Object.keys(MONEDAS_LARGAS).map((valor) => el("option", { value: valor, selected: (b.moneda || "USD") === valor }, simbolo(valor))));
  // Extras y recargos se cobran en la misma moneda: al cambiarla, cambia su prefijo.
  moneda.addEventListener("change", () => { pintarExtras(); pintarOpciones(); });
  const descripcion = el("textarea", { maxlength: 600, rows: 3, value: b.descripcion });
  const desde = el("input", { type: "date", value: b.vigente_desde || "" });
  const hasta = el("input", { type: "date", value: b.vigente_hasta || "" });
  const activo = el("input", { type: "checkbox", checked: b.activo });
  const cotizacion = el("input", { type: "checkbox", checked: b.cotizacion_automatica });
  const precioDesde = el("input", { type: "checkbox", checked: b.precio_desde });
  const agotado = el("input", { type: "checkbox", checked: b.agotado });
  const casillasDeLineas = lineas.map((l) => el("input", { type: "checkbox", value: l.codigo, checked: b.lineas.includes(l.codigo) }));
  // Un precio «desde» lo confirma una persona: no lo puede calcular el bot.
  precioDesde.addEventListener("change", () => { if (precioDesde.checked) cotizacion.checked = false; });
  cotizacion.addEventListener("change", () => { if (cotizacion.checked) precioDesde.checked = false; });
  const vistaDelBot = el("p", {});
  const contOpciones = el("div", { class: "columna" });
  const contExtras = el("div", { class: "lista" });
  const contFotos = el("div", { class: "columna" });
  // Fuera del formulario: subir una foto no es un cambio sin guardar.
  const selectorDeFoto = el("input", { type: "file", accept: "image/jpeg,image/png", hidden: true });
  selectorDeFoto.addEventListener("change", subirFoto);

  function cambio() {
    estado.sucio = true;
    vistaDelBot.textContent = textoDelBot();
  }

  function textoDelBot() {
    if (!activo.checked) return "Apagado: el bot no lo ofrece.";
    const partes = [];
    const importe = precio.value.trim().replace(",", ".");
    const nombreVisible = nombre.value.trim() || "Nombre del ítem";
    const conMoneda = (valor) => `${simbolo(moneda.value)} ${Number(valor).toFixed(2)}`;
    const porUnidad = unidad.value.trim() ? ` ${unidad.value.trim()}` : "";
    if (!/^\d+(\.\d{1,2})?$/.test(importe)) {
      partes.push(`${nombreVisible}. El precio te lo confirma una persona del equipo.`);
    } else if (precioDesde.checked) {
      partes.push(`${nombreVisible}: desde ${conMoneda(importe)}${porUnidad}. El precio final te lo confirma una persona del equipo.`);
    } else {
      partes.push(`${nombreVisible}: ${conMoneda(importe)}${porUnidad}.`);
    }
    if (descripcion.value.trim()) partes.push(conPunto(descripcion.value.trim()));
    if (hasta.value) partes.push(`Válido hasta el ${fecha(hasta.value)}.`);
    const recargo = (valor) => {
      const limpio = String(valor ?? "").trim().replace(",", ".");
      return /^\d+(\.\d{1,2})?$/.test(limpio) && Number(limpio) > 0 ? ` (+${conMoneda(limpio)})` : "";
    };
    const opciones = b.opciones.filter((o) => o.nombre.trim() && o.valores.length);
    if (opciones.length) {
      partes.push(`${opciones.map((o) => `${o.nombre.trim()}: ${o.valores.map((v) => `${v.valor}${recargo(v.recargo)}`).join(", ")}`).join(". ")}.`);
    }
    const extras = b.extras.filter((e) => e.nombre.trim());
    if (extras.length) partes.push(`Podés sumarle ${extras.map((e) => e.nombre.trim().toLowerCase()).join(" o ")}.`);
    if (agotado.checked) partes.push("Por ahora está agotado.");
    return `«${partes.join(" ")}»`;
  }

  function pintarOpciones() {
    pintarEn(contOpciones,
      b.opciones.map((opcion, i) => el("div", { class: "opcion-editor" },
        el("div", { class: "opcion-cabecera" },
          el("input", { type: "text", value: opcion.nombre, maxlength: 40, placeholder: "Talla, color, tamaño…", "aria-label": "Nombre de la opción",
            oninput: (e) => { opcion.nombre = e.target.value; } }),
          el("button", { class: "quitar", type: "button", title: "Quitar opción", "aria-label": "Quitar opción",
            onclick: () => { b.opciones.splice(i, 1); pintarOpciones(); cambio(); } }, "×")),
        opcion.valores.length
          ? el("div", { class: "valores-lista" },
            el("div", { class: "valor-fila valor-encabezado" }, el("span", {}, "Valor"), el("span", {}, "Cuesta más (opcional)"), el("span", {})),
            opcion.valores.map((valor, j) => el("div", { class: "valor-fila" },
              el("span", { class: "valor" }, valor.valor),
              el("label", { class: "con-prefijo" }, el("span", {}, `+ ${simbolo(moneda.value)}`),
                el("input", { type: "text", inputmode: "decimal", value: valor.recargo, placeholder: "0.00", "aria-label": `Recargo de ${valor.valor}`,
                  oninput: (e) => { valor.recargo = e.target.value; } })),
              el("button", { class: "quitar", type: "button", "aria-label": `Quitar ${valor.valor}`,
                onclick: () => { opcion.valores.splice(j, 1); pintarOpciones(); cambio(); } }, "×"))))
          : null,
        el("input", { class: "nuevo-valor", type: "text", maxlength: 40, placeholder: "Agregar valor y Enter",
          title: "Escribí el valor y apretá Enter. Podés separar varios con comas.", "aria-label": "Agregar un valor", "data-opcion": i,
          onkeydown: (e) => {
            if (e.key === "Enter" || e.key === ",") { e.preventDefault(); agregarValores(i, e.target.value); }
          },
          onblur: (e) => { if (e.target.value.trim()) agregarValores(i, e.target.value, false); } }))),
      el("button", { class: "agregar", type: "button",
        onclick: () => { b.opciones.push({ nombre: "", valores: [] }); pintarOpciones(); cambio(); } }, "+ Agregar opción"));
  }

  function agregarValores(indice, texto, enfocar = true) {
    const opcion = b.opciones[indice];
    if (!opcion) return;
    for (const valor of texto.split(",").map((v) => v.trim()).filter(Boolean)) {
      if (!opcion.valores.some((v) => v.valor.toLowerCase() === valor.toLowerCase())) opcion.valores.push({ valor, recargo: "" });
    }
    pintarOpciones();
    cambio();
    if (enfocar) contOpciones.querySelector(`[data-opcion="${indice}"]`)?.focus();
  }

  function pintarExtras() {
    pintarEn(contExtras, 
      ...b.extras.map((extra, i) => el("div", { class: "lista-fila" },
        el("input", { type: "text", value: extra.nombre, maxlength: 60, placeholder: "Nombre estampado", "aria-label": "Nombre del extra",
          oninput: (e) => { extra.nombre = e.target.value; } }),
        el("label", { class: "con-prefijo" }, el("span", {}, `+ ${simbolo(moneda.value)}`),
          el("input", { type: "text", inputmode: "decimal", value: extra.precio ?? "", "aria-label": "Precio del extra",
            oninput: (e) => { extra.precio = e.target.value; } })),
        el("button", { class: "quitar", type: "button", "aria-label": "Quitar extra",
          onclick: () => { b.extras.splice(i, 1); pintarExtras(); cambio(); } }, "×"))),
      el("button", { class: "agregar", type: "button",
        onclick: () => { b.extras.push({ nombre: "", precio: "" }); pintarExtras(); cambio(); } }, "+ Agregar extra"));
  }

  function pintarFotos() {
    if (nuevo) {
      pintarEn(contFotos, el("div", { class: "sin-foto" }, "Guardá el ítem y después le subís las fotos."));
      return;
    }
    pintarEn(contFotos, 
      b.fotos.length
        ? el("div", { class: "fotos" }, b.fotos.map((foto, i) => el("div", { class: i === 0 ? "foto foto-principal" : "foto" },
          el("img", { src: `/api/fotos/${foto.id}`, alt: i === 0 ? "Foto principal" : `Foto ${i + 1}` }),
          el("button", { type: "button", onclick: () => quitarFoto(foto) }, "Quitar"))))
        : el("div", { class: "sin-foto" }, "Sin fotos todavía."),
      b.fotos.length < MAXIMO_FOTOS
        ? el("button", { class: "subir", type: "button", onclick: () => selectorDeFoto.click() }, icono("foto", 17), b.fotos.length ? "Agregar otra foto" : "Subir foto")
        : null,
      el("span", { class: "tenue" }, "JPG o PNG de hasta 5 MB, hasta 5 por ítem. La primera es la que manda el bot cuando alguien pide verlo."));
  }

  async function subirFoto() {
    const archivo = selectorDeFoto.files[0];
    selectorDeFoto.value = "";
    if (!archivo) return;
    if (archivo.size > MAXIMO_FOTO) {
      avisar("La foto pesa más de 5 MB. Achicala y probá de nuevo.", true);
      return;
    }
    try {
      b.fotos.push(await api("POST", `/api/items/${b.id}/fotos`, archivo));
      pintarFotos();
      avisar("Foto subida. Publicá para que el bot la use.");
      refrescarEstadoSinFrenar();
    } catch (e) {
      avisarError(e);
    }
  }

  async function quitarFoto(foto) {
    if (!confirm("¿Quitar esta foto? El bot la deja de mandar cuando publiques.")) return;
    try {
      await api("DELETE", `/api/items/${b.id}/fotos/${foto.id}`);
      b.fotos = b.fotos.filter((f) => f.id !== foto.id);
      pintarFotos();
      refrescarEstadoSinFrenar();
    } catch (e) {
      avisarError(e);
    }
  }

  function datosDelFormulario() {
    return {
      tipo: tipo.value, sku: sku.value, nombre: nombre.value, categoria: categoria.value,
      descripcion: descripcion.value, precio: precio.value.trim() || null, moneda: moneda.value,
      precio_desde: precioDesde.checked, unidad: unidad.value,
      vigente_desde: desde.value || null, vigente_hasta: hasta.value || null,
      opciones: b.opciones.filter((o) => o.nombre.trim() || o.valores.length).map((o) => ({
        nombre: o.nombre,
        valores: o.valores.map((v) => ({ valor: v.valor, recargo: String(v.recargo ?? "").trim() || null })),
      })),
      extras: b.extras.filter((e) => e.nombre.trim() || String(e.precio ?? "").trim()).map((e) => ({ nombre: e.nombre, precio: e.precio })),
      lineas: casillasDeLineas.filter((c) => c.checked).map((c) => c.value),
      cotizacion_automatica: cotizacion.checked,
      agotado: agotado.checked,
      activo: activo.checked,
    };
  }

  async function guardar(boton) {
    boton.disabled = true;
    try {
      const guardado = nuevo
        ? await api("POST", "/api/items", datosDelFormulario())
        : await api("PUT", `/api/items/${b.id}`, datosDelFormulario());
      estado.sucio = false;
      avisar(nuevo ? "Listo, quedó guardado. Ahora podés subirle fotos." : "Cambios guardados. Publicá para que el bot los use.");
      refrescarEstadoSinFrenar();
      await irA("editor", { forzar: true, datos: guardado });
    } catch (e) {
      avisarError(e);
      boton.disabled = false;
    }
  }

  async function borrar() {
    if (!confirm(`¿Borrar «${b.nombre}»? El bot lo sigue ofreciendo hasta que publiques de nuevo.`)) return;
    try {
      await api("DELETE", `/api/items/${b.id}`);
      estado.sucio = false;
      avisar("Ítem borrado. Publicá para que el bot deje de ofrecerlo.");
      refrescarEstadoSinFrenar();
      await irA("catalogo", { forzar: true });
    } catch (e) {
      avisarError(e);
    }
  }

  pintarEn(principal, 
    encabezado({
      migas: nuevo ? "Catálogo / Nuevo" : `Catálogo / ${b.sku}`,
      titulo: nuevo ? "Nuevo ítem" : b.nombre,
      acciones: [
        el("button", { class: "boton", type: "button", onclick: () => irA("catalogo") }, "Volver"),
        nuevo ? null : el("button", { class: "boton boton-peligro", type: "button", onclick: borrar }, "Borrar"),
        botonPrimario(nuevo ? "Guardar ítem" : "Guardar cambios", guardar),
      ],
    }),
    el("div", { class: "editor", oninput: cambio, onchange: cambio },
      el("div", { class: "columna" },
        el("section", { class: "tarjeta" }, el("h2", {}, "Fotos"), contFotos),
        el("section", { class: "vista-bot" }, el("span", {}, icono("mensaje", 15), "Así lo ofrece el bot"), vistaDelBot)),
      el("div", { class: "columna" },
        el("section", { class: "tarjeta" }, el("h2", {}, "Datos"),
          el("div", { class: "rejilla-2" },
            campo("Tipo", tipo),
            campo("Código", sku, { ayuda: nuevo ? "Letras, números y guiones. Después no se cambia." : "No se cambia: lo usan las fotos y las publicaciones." }),
            campo("Nombre", nombre, { ancho: true }),
            campo("Precio", el("div", { class: "precio-con-moneda" }, moneda, precio), { ayuda: "Vacío: lo cotiza una persona del equipo." }),
            campo("Unidad", unidad),
            el("label", { class: "casilla-simple ancho-completo" }, precioDesde,
              el("span", {}, "Es un precio «desde»: el bot da esta referencia y el precio final lo confirma una persona.")),
            campo("Categoría", categoria, { ancho: true }),
            campo("Descripción o qué incluye", descripcion, { ancho: true }),
            campo("Vigente desde", desde, { ayuda: "Opcional." }),
            campo("Vigente hasta", hasta, { ayuda: "Opcional. Fuera de las fechas, el bot no lo ofrece." }))),
        el("section", { class: "tarjeta" }, el("h2", {}, "Opciones y extras"),
          el("p", { class: "tarjeta-ayuda" }, "Opciones como talla, color o tamaño; si un valor cuesta más, poné cuánto más. Extras con precio por unidad, como nombre estampado."),
          contOpciones, contExtras),
        lineas.length
          ? el("section", { class: "tarjeta" }, el("h2", {}, "Dónde se ofrece"),
            el("p", { class: "tarjeta-ayuda" }, "Marcá las líneas de WhatsApp o sucursales donde el bot lo ofrece. Si no marcás ninguna, se ofrece en todas."),
            el("div", { class: "casillas" }, casillasDeLineas.map((casilla, i) => el("label", { class: "casilla" }, casilla, lineas[i].nombre))))
          : null,
        el("section", { class: "tarjeta interruptores" },
          interruptor(activo, "Activo", "Si lo apagás, el bot deja de ofrecerlo."),
          interruptor(agotado, "Agotado", "El bot lo sigue mostrando, pero avisa que no hay y no toma el pedido."),
          interruptor(cotizacion, "Cotización automática", "Encendida, el bot calcula el precio con tus reglas. Apagada, pasa el pedido a una persona del equipo.")))),
    selectorDeFoto);

  pintarOpciones();
  pintarExtras();
  pintarFotos();
  vistaDelBot.textContent = textoDelBot();
}

// -- Mi negocio (administrador) -------------------------------------------------------------

async function vistaNegocio(principal) {
  const perfil = await api("GET", "/api/perfil");
  const { formas_de_pago: formasDePago } = estado.sesion.listas;
  const texto = (clave, maximo, placeholder = "", area = false) =>
    el(area ? "textarea" : "input", { type: area ? null : "text", maxlength: maximo, placeholder, rows: area ? 3 : null, value: perfil[clave] || "" });

  const controles = {
    nombre_publico: texto("nombre_publico", 120),
    mapa_url: texto("mapa_url", 500, "https://maps.app.goo.gl/…"),
    descripcion: texto("descripcion", 600, "A qué se dedica el negocio, en dos o tres líneas.", true),
    direccion: texto("direccion", 300, "", true),
    horarios: texto("horarios", 600, "Lunes a viernes de 8:00 a 17:00. Sábados de 8:00 a 12:00.", true),
    nota_pagos: texto("nota_pagos", 300, "Por ejemplo: pedimos 50 % de adelanto en pedidos grandes.", true),
    envios: texto("envios", 800, "Zonas, costos y plazos de entrega.", true),
    politicas: texto("politicas", 1500, "Cambios, devoluciones y garantías.", true),
  };
  const casillas = Object.keys(formasDePago)
    .map((valor) => el("input", { type: "checkbox", value: valor, checked: perfil.formas_de_pago.includes(valor) }));
  const preguntas = structuredClone(perfil.preguntas || []);
  const contPreguntas = el("div", { class: "columna" });
  const lineas = structuredClone(perfil.lineas || []).map((l) => ({ direccion: "", horarios: "", ...l }));
  const contLineas = el("div", { class: "columna" });

  function pintarLineas() {
    pintarEn(contLineas,
      lineas.map((linea, i) => el("div", { class: "pregunta" },
        el("div", { class: "pregunta-cabecera" },
          el("input", { type: "text", value: linea.nombre, maxlength: 60, placeholder: "Por ejemplo: Uniformes, Sucursal Masaya",
            "aria-label": "Nombre de la línea o sucursal", oninput: (e) => { linea.nombre = e.target.value; } }),
          el("button", { class: "quitar", type: "button", "aria-label": "Quitar línea o sucursal",
            onclick: () => {
              if (linea.codigo && !confirm(`¿Quitar «${linea.nombre}»? Los ítems que solo se ofrecían ahí dejan de ofrecerse hasta que les elijas otra línea.`)) return;
              lineas.splice(i, 1);
              pintarLineas();
              estado.sucio = true;
            } }, "×")),
        el("div", { class: "rejilla-2" },
          campo("Dirección, si es distinta", el("textarea", { rows: 2, maxlength: 300, value: linea.direccion,
            oninput: (e) => { linea.direccion = e.target.value; } })),
          campo("Horarios, si son distintos", el("textarea", { rows: 2, maxlength: 600, value: linea.horarios,
            oninput: (e) => { linea.horarios = e.target.value; } }))))),
      lineas.length < 20
        ? el("button", { class: "agregar", type: "button",
          onclick: () => { lineas.push({ nombre: "", direccion: "", horarios: "" }); pintarLineas(); estado.sucio = true; } }, "+ Agregar línea o sucursal")
        : null);
  }

  function pintarPreguntas() {
    pintarEn(contPreguntas, 
      ...preguntas.map((p, i) => el("div", { class: "pregunta" },
        el("div", { class: "pregunta-cabecera" },
          el("input", { type: "text", value: p.pregunta, maxlength: 200, placeholder: "Pregunta", "aria-label": "Pregunta",
            oninput: (e) => { p.pregunta = e.target.value; } }),
          el("button", { class: "quitar", type: "button", "aria-label": "Quitar pregunta",
            onclick: () => { preguntas.splice(i, 1); pintarPreguntas(); estado.sucio = true; } }, "×")),
        el("textarea", { maxlength: 800, rows: 2, placeholder: "Respuesta", "aria-label": "Respuesta", value: p.respuesta,
          oninput: (e) => { p.respuesta = e.target.value; } }))),
      preguntas.length < 30
        ? el("button", { class: "agregar", type: "button",
          onclick: () => { preguntas.push({ pregunta: "", respuesta: "" }); pintarPreguntas(); estado.sucio = true; } }, "+ Agregar pregunta")
        : null);
  }

  async function guardar(boton) {
    const datos = Object.fromEntries(Object.entries(controles).map(([clave, control]) => [clave, control.value]));
    datos.formas_de_pago = casillas.filter((c) => c.checked).map((c) => c.value);
    datos.preguntas = preguntas.filter((p) => p.pregunta.trim() || p.respuesta.trim());
    datos.lineas = lineas.filter((l) => l.nombre.trim() || l.direccion.trim() || l.horarios.trim());
    boton.disabled = true;
    try {
      const guardado = await api("PUT", "/api/perfil", datos);
      // Las líneas nuevas vuelven con su código. Sin esto, un segundo guardado
      // les armaría otro y los ítems perderían la referencia.
      lineas.splice(0, lineas.length, ...guardado.lineas);
      pintarLineas();
      estado.sucio = false;
      avisar("Guardado. Publicá para que el bot use estos datos.");
      refrescarEstadoSinFrenar();
    } catch (e) {
      avisarError(e);
    } finally {
      boton.disabled = false;
    }
  }

  const marcarSucio = () => { estado.sucio = true; };
  pintarEn(principal, 
    encabezado({
      titulo: "Mi negocio",
      texto: "Lo que el bot responde cuando preguntan dónde están, en qué horario atienden, cómo se paga o si hacen envíos.",
      acciones: [estadoDePublicacion(), botonPrimario("Guardar cambios", guardar)],
    }),
    el("div", { class: "formulario", oninput: marcarSucio, onchange: marcarSucio },
      el("section", { class: "tarjeta" }, el("h2", {}, "Datos generales"),
        el("div", { class: "rejilla-2" },
          campo("Nombre del negocio", controles.nombre_publico),
          campo("Enlace de Google Maps", controles.mapa_url),
          campo("A qué se dedica", controles.descripcion, { ancho: true }),
          campo("Dirección", controles.direccion),
          campo("Horarios", controles.horarios))),
      el("section", { class: "tarjeta" }, el("h2", {}, "Líneas de WhatsApp y sucursales"),
        el("p", { class: "tarjeta-ayuda" }, "Solo si tenés más de un WhatsApp o más de una sucursal. Después, en cada ítem elegís dónde se ofrece. Con uno solo, dejalo vacío."),
        contLineas),
      el("section", { class: "tarjeta" }, el("h2", {}, "Pagos"),
        el("div", { class: "aviso" }, icono("info", 20), el("span", {},
          "Los pagos los atiende una persona del equipo. El bot puede decir qué formas de pago aceptás, pero cuando alguien quiere pagar, pide una cuenta o manda un comprobante, le pasa la conversación a una persona. Por eso acá no se cargan números de cuenta.")),
        el("div", { class: "casillas" }, casillas.map((c) => el("label", { class: "casilla" }, c, formasDePago[c.value]))),
        campo("Nota sobre pagos", controles.nota_pagos, { ayuda: "Opcional. Sin números de cuenta." })),
      el("section", { class: "tarjeta" }, el("h2", {}, "Envíos y entregas"), campo("Cómo entregan", controles.envios)),
      el("section", { class: "tarjeta" }, el("h2", {}, "Políticas"), campo("Cambios, devoluciones y garantías", controles.politicas)),
      el("section", { class: "tarjeta" }, el("h2", {}, "Preguntas frecuentes"),
        el("p", { class: "tarjeta-ayuda" }, "Las preguntas que te hacen seguido, con la respuesta que querés que dé el bot."),
        contPreguntas),
      el("div", { class: "acciones" }, botonPrimario("Guardar cambios", guardar))));
  pintarPreguntas();
  pintarLineas();
}

// -- Reglas de precio (administrador) ----------------------------------------------------------
//
// Todo es opcional y cada regla se enciende aparte, para que un negocio que
// no hace descuentos no tenga que entender tramos. A la derecha se ve, en
// palabras, cómo va a cobrar el bot, y se puede probar con una cantidad.

async function vistaReglas(principal) {
  const [ajustes, items] = await Promise.all([api("GET", "/api/ajustes"), api("GET", "/api/items")]);
  estado.ajustes = ajustes;
  estado.items = items;

  const habitual = el("select", { "aria-label": "Moneda habitual" },
    Object.entries(MONEDAS_LARGAS).map(([valor, texto]) => el("option", { value: valor, selected: ajustes.moneda === valor }, texto)));
  const conDescuentos = el("input", { type: "checkbox", checked: ajustes.descuentos.length > 0 });
  const conLimite = el("input", { type: "checkbox", checked: ajustes.cantidad_maxima !== null });
  const limite = el("input", { type: "text", inputmode: "numeric", value: ajustes.cantidad_maxima ?? "", placeholder: "200",
    "aria-label": "Hasta cuántas unidades cotiza el bot" });
  const tramos = ajustes.descuentos.map((t) => ({ desde: String(t.desde), porcentaje: t.porcentaje }));

  const contTramos = el("div", { class: "columna" });
  const seccionTramos = el("div", { class: "columna" },
    el("p", { class: "tarjeta-ayuda" },
      "Se aplican al precio base de los ítems con cotización automática, no a los extras. Agregá una línea por cada cantidad desde la que cambia el descuento."),
    contTramos);
  const seccionLimite = el("div", { class: "columna" },
    el("div", { class: "fila-regla" }, el("span", {}, "El bot cotiza solo hasta"), limite, el("span", {}, "unidades por pedido.")),
    el("p", { class: "tarjeta-ayuda" }, "Si piden más, el bot no da precio y le pasa el pedido a una persona del equipo."));
  const avisos = el("div", { class: "aviso aviso-amarillo", role: "alert", hidden: true });

  const resumen = el("div", { class: "columna resumen" });
  // Los descuentos solo los usa el bot en ítems con precio y cotización automática.
  const paraProbar = items.filter((i) => i.precio !== null && i.cotizacion_automatica && !i.agotado && !i.precio_desde);
  const itemDePrueba = el("select", { "aria-label": "Ítem para probar" },
    paraProbar.map((i) => el("option", { value: i.id }, i.nombre)));
  const cantidadDePrueba = el("input", { type: "text", inputmode: "numeric", "aria-label": "Cantidad para probar" });
  const calculo = el("div", { class: "columna calculo" });

  function leer() {
    const problemas = [];
    let maxima = null;
    if (conLimite.checked) {
      const texto = limite.value.trim();
      if (/^\d+$/.test(texto) && Number(texto) >= 1) maxima = Number(texto);
      else problemas.push("Escribí hasta cuántas unidades cotiza el bot, con un número entero.");
    }

    const descuentos = [];
    if (conDescuentos.checked) {
      for (const tramo of tramos) {
        const desde = tramo.desde.trim();
        const porcentaje = tramo.porcentaje.trim().replace(",", ".");
        if (!desde && !porcentaje) continue;
        if (!/^\d+$/.test(desde) || Number(desde) < 2) {
          problemas.push("Cada descuento empieza desde 2 unidades o más.");
        } else if (!/^\d{1,2}(\.\d{1,2})?$/.test(porcentaje) || Number(porcentaje) <= 0) {
          problemas.push(`El descuento desde ${desde} unidades necesita un porcentaje mayor que 0 y menor que 100.`);
        } else {
          descuentos.push({ desde: Number(desde), porcentaje });
        }
      }
      descuentos.sort((a, b) => a.desde - b.desde);
      descuentos.forEach((tramo, i) => {
        if (i > 0 && tramo.desde === descuentos[i - 1].desde) problemas.push(`Hay dos descuentos desde ${tramo.desde} unidades.`);
        if (maxima !== null && tramo.desde > maxima) {
          problemas.push(`El descuento desde ${tramo.desde} unidades no se usaría nunca: el bot cotiza solo hasta ${maxima}.`);
        }
      });
    }
    return { datos: { moneda: habitual.value, cantidad_maxima: maxima, descuentos }, problemas: [...new Set(problemas)] };
  }

  function pintarTramos() {
    pintarEn(contTramos,
      tramos.map((tramo, i) => el("div", { class: "fila-regla" },
        el("span", {}, "Desde"),
        el("input", { type: "text", inputmode: "numeric", value: tramo.desde, placeholder: String(12 * (i + 1)),
          "aria-label": "Desde cuántas unidades", oninput: (e) => { tramo.desde = e.target.value; actualizar(); } }),
        el("span", {}, "unidades:"),
        el("input", { type: "text", inputmode: "decimal", value: tramo.porcentaje, placeholder: String(5 * (i + 1)),
          "aria-label": "Porcentaje de descuento", oninput: (e) => { tramo.porcentaje = e.target.value; actualizar(); } }),
        el("span", {}, "% de descuento"),
        el("button", { class: "quitar", type: "button", "aria-label": "Quitar este descuento",
          onclick: () => { tramos.splice(i, 1); pintarTramos(); actualizar(); estado.sucio = true; } }, "×"))),
      tramos.length < 10
        ? el("button", { class: "agregar", type: "button",
          onclick: () => { tramos.push({ desde: "", porcentaje: "" }); pintarTramos(); estado.sucio = true; } }, "+ Agregar otro descuento")
        : null);
  }

  function rango(desde, hasta) {
    if (desde === 1 && hasta === Infinity) return "Cualquier cantidad";
    if (hasta === Infinity) return `${desde} unidades o más`;
    if (desde === hasta) return desde === 1 ? "1 unidad" : `${desde} unidades`;
    return `${desde} a ${hasta} unidades`;
  }

  function pintarResumen({ cantidad_maxima: maxima, descuentos }) {
    const tope = maxima ?? Infinity;
    const lineas = [];
    const primero = descuentos.find((t) => t.desde <= tope);
    lineas.push([rango(1, Math.min(primero ? primero.desde - 1 : Infinity, tope)), "Precio normal", ""]);
    descuentos.forEach((tramo, i) => {
      if (tramo.desde > tope) return;
      const siguiente = descuentos[i + 1];
      lineas.push([rango(tramo.desde, Math.min(siguiente ? siguiente.desde - 1 : Infinity, tope)), `${tramo.porcentaje} % de descuento`, ""]);
    });
    if (maxima !== null) lineas.push([`Más de ${maxima} unidades`, "Lo cotiza una persona", "resumen-persona"]);
    pintarEn(resumen, lineas.map(([cantidad, trato, clase]) => el("div", { class: `resumen-fila ${clase}` },
      el("span", {}, cantidad), el("strong", {}, trato))));
  }

  function pintarCalculo({ cantidad_maxima: maxima, descuentos }) {
    const item = paraProbar.find((i) => String(i.id) === itemDePrueba.value) || null;
    const monedaDePrueba = item ? item.moneda : habitual.value;
    const texto = cantidadDePrueba.value.trim();
    const sugerida = descuentos[0]?.desde || 10;
    cantidadDePrueba.placeholder = String(sugerida);
    const cantidad = /^\d+$/.test(texto) && Number(texto) > 0 ? Number(texto) : sugerida;
    const importe = (centavos) => `${simbolo(monedaDePrueba)} ${(centavos / 100).toFixed(2)}`;
    const linea = (izquierda, derecha) => el("div", { class: "ejemplo-linea" }, el("span", {}, izquierda), el("span", {}, derecha));

    if (maxima !== null && cantidad > maxima) {
      pintarEn(calculo, el("p", { class: "calculo-persona" },
        `Con ${cantidad} unidades el bot no da precio: le pasa el pedido a una persona del equipo.`));
      return;
    }
    const aplicado = descuentos.filter((t) => t.desde <= cantidad).pop();
    // En centavos, para no arrastrar los redondeos de los números con coma.
    const base = Math.round(Number(item ? item.precio : "100.00") * 100);
    const descuento = aplicado ? Math.round(Number(aplicado.porcentaje) * 100) : 0;
    const porUnidad = Math.round((base * (10000 - descuento)) / 10000);
    pintarEn(calculo,
      linea("Precio base", importe(base)),
      aplicado ? linea(`Descuento del ${aplicado.porcentaje} %`, `− ${importe(base - porUnidad)}`) : linea("Descuento", "No aplica"),
      linea("Precio por unidad", importe(porUnidad)),
      el("div", { class: "ejemplo-total" }, el("span", {}, `Total por ${cantidad} ${cantidad === 1 ? "unidad" : "unidades"}`),
        el("strong", {}, importe(porUnidad * cantidad))),
      item ? null : el("small", { class: "tenue" },
        `Con un precio de ejemplo de ${importe(10000)}. Cuando tengas un ítem con precio y cotización automática, podés probar con ese.`));
  }

  function actualizar() {
    seccionTramos.hidden = !conDescuentos.checked;
    seccionLimite.hidden = !conLimite.checked;
    const { datos, problemas } = leer();
    avisos.hidden = problemas.length === 0;
    pintarEn(avisos, problemas.length ? el("ul", { class: "lista-avisos" }, problemas.map((p) => el("li", {}, p))) : null);
    pintarResumen(datos);
    pintarCalculo(datos);
  }

  async function guardar(boton) {
    const { datos, problemas } = leer();
    if (problemas.length) {
      avisar(problemas[0], true);
      return;
    }
    boton.disabled = true;
    try {
      estado.ajustes = await api("PUT", "/api/ajustes", datos);
      estado.sucio = false;
      avisar("Reglas guardadas. Publicá para que el bot las use.");
      refrescarEstadoSinFrenar();
      await irA("reglas", { forzar: true });
    } catch (e) {
      avisarError(e);
      boton.disabled = false;
    }
  }

  conDescuentos.addEventListener("change", () => {
    if (conDescuentos.checked && tramos.length === 0) {
      tramos.push({ desde: "", porcentaje: "" });
      pintarTramos();
    }
    actualizar();
  });
  for (const control of [conLimite, habitual, itemDePrueba]) control.addEventListener("change", actualizar);
  for (const control of [limite, cantidadDePrueba]) control.addEventListener("input", actualizar);

  const marcarSucio = () => { estado.sucio = true; };
  pintarEn(principal,
    encabezado({
      titulo: "Reglas de precio",
      texto: "Todo es opcional. Encendé solo lo que use tu negocio: si no hacés descuentos ni tenés pedidos que prefieras cotizar a mano, dejalo apagado.",
      acciones: [estadoDePublicacion(), botonPrimario("Guardar cambios", guardar)],
    }),
    el("div", { class: "reglas" },
      // Solo el formulario marca cambios sin guardar: probar una cantidad no.
      el("div", { class: "columna", oninput: marcarSucio, onchange: marcarSucio },
        el("section", { class: "tarjeta" }, el("h2", {}, "Moneda habitual"),
          el("p", { class: "tarjeta-ayuda" }, "Es la que aparece al crear un ítem nuevo. Cada ítem puede tener su propia moneda, junto al precio."),
          campo("Moneda", habitual)),
        el("section", { class: "tarjeta" },
          interruptor(conDescuentos, "Descuentos por cantidad", "Por ejemplo: 5 % menos cuando piden 12 unidades o más."),
          seccionTramos),
        el("section", { class: "tarjeta" },
          interruptor(conLimite, "Los pedidos grandes los cotiza una persona", "Por encima de una cantidad, el bot no da precio y le pasa el pedido al equipo."),
          seccionLimite),
        avisos),
      el("div", { class: "columna" },
        el("section", { class: "ejemplo" }, el("span", {}, "Así cobra el bot"), resumen),
        el("section", { class: "tarjeta" }, el("h2", {}, "Probá con un pedido"),
          el("div", { class: "rejilla-2" },
            campo("Cantidad", cantidadDePrueba),
            paraProbar.length ? campo("Ítem", itemDePrueba) : null),
          calculo))));
  pintarTramos();
  actualizar();
}

// -- Publicar (administrador) -------------------------------------------------------------------

async function vistaPublicar(principal) {
  const [datos, actividad] = await Promise.all([refrescarEstado(), api("GET", "/api/actividad")]);
  const ultima = datos.historial[0];

  const botonPublicar = el("button", { class: "boton boton-primario boton-grande", type: "button" }, icono("publicar", 18), "Publicar ahora");
  botonPublicar.addEventListener("click", async () => {
    botonPublicar.disabled = true;
    try {
      const resultado = await api("POST", "/api/publicar");
      avisar(resultado.sin_cambios
        ? "No había cambios: el bot ya usa lo último."
        : `Publicado: versión ${resultado.version}. El bot ya puede usarlo.`);
      await irA("publicar", { forzar: true });
    } catch (e) {
      avisarError(e);
      botonPublicar.disabled = false;
    }
  });

  let titulo;
  let explicacion;
  if (!datos.cambios_sin_publicar) {
    titulo = `El bot usa la versión ${ultima.version}`;
    explicacion = `Publicada el ${fechaHora(ultima.publicada_en)}${ultima.publicada_por ? ` por ${ultima.publicada_por}` : ""}. Cuando cambies algo, volvé acá para publicarlo.`;
  } else if (ultima) {
    titulo = "Tenés cambios que el bot todavía no ve";
    explicacion = `El bot sigue con la versión ${ultima.version}, del ${fechaHora(ultima.publicada_en)}. Publicá para que empiece a usar lo nuevo.`;
  } else {
    titulo = "Todavía no publicaste nada";
    explicacion = "Tu bot no ve el catálogo ni los datos del negocio hasta la primera publicación.";
  }

  const acciones = {
    entrar: () => "Inició sesión",
    crear_item: (d) => `Creó ${d.sku}`,
    editar_item: (d) => `Editó ${d.sku}`,
    borrar_item: (d) => `Borró ${d.sku}`,
    subir_foto: () => "Subió una foto",
    quitar_foto: () => "Quitó una foto",
    guardar_mi_negocio: () => "Guardó Mi negocio",
    guardar_reglas: () => "Guardó las reglas de precio",
    publicar: (d) => `Publicó la versión ${d.version}`,
    agencia_crear_negocio: () => "La agencia creó el negocio",
    agencia_crear_usuario: (d) => `La agencia creó la cuenta ${d.correo} (${d.rol})`,
    agencia_dar_acceso: (d) => `La agencia dio acceso a ${d.correo} (${d.rol})`,
    agencia_cambiar_correo: (d) => `La agencia cambió el correo de ${d.de} a ${d.a}`,
    agencia_clave_bot: (d) => `La agencia creó una clave para el bot ${d.nombre}`,
    agencia_revocar_claves_bot: () => "La agencia anuló las claves del bot",
  };

  pintarEn(principal, 
    encabezado({ titulo: "Publicar", texto: "Lo que guardás queda como borrador. El bot usa solo lo publicado, así podés preparar los cambios con calma." }),
    el("div", { class: "publicar" },
      el("section", { class: "estado-grande" },
        datos.cambios_sin_publicar
          ? el("span", { class: "pill pill-aviso" }, "Cambios sin publicar")
          : el("span", { class: "pill pill-ok" }, "Todo publicado"),
        el("h2", {}, titulo),
        el("p", {}, explicacion),
        datos.cambios_sin_publicar ? botonPublicar : null),
      el("div", { class: "columna" },
        el("section", { class: "tarjeta" }, el("h2", {}, "Versiones publicadas"),
          datos.historial.length
            ? el("div", { class: "historial" }, datos.historial.map((p) => el("div", { class: "historial-fila" },
              el("strong", {}, `Versión ${p.version}`),
              el("span", { class: "tenue" }, `${fechaHora(p.publicada_en)}${p.publicada_por ? ` · ${p.publicada_por}` : ""}`))))
            : el("p", { class: "tenue" }, "Todavía no hay versiones.")),
        el("section", { class: "tarjeta" }, el("h2", {}, "Actividad reciente"),
          el("div", { class: "historial" }, actividad.map((a) => el("div", { class: "historial-fila" },
            el("span", {}, (acciones[a.accion] || (() => a.accion))(a.detalle || {})),
            el("span", { class: "tenue" }, fechaHora(a.en)))))))));
}

// -- Vistas de consulta (empleado) ------------------------------------------------------------------

function avisoDeConsulta() {
  return el("div", { class: "aviso" }, icono("candado", 20),
    el("span", {}, "Tenés acceso de consulta. Los precios, las fotos y las reglas los cambia el administrador del negocio."));
}

async function vistaPublicado(principal) {
  const { publicacion } = await api("GET", "/api/publicado");
  if (!publicacion) {
    pintarEn(principal, avisoDeConsulta(), encabezado({ titulo: "Catálogo publicado" }),
      el("div", { class: "tabla" }, el("div", { class: "vacio" },
        el("strong", {}, "Todavía no hay nada publicado"),
        el("span", {}, "Cuando el administrador publique, acá vas a ver lo mismo que ofrece el bot."))));
    return;
  }
  const { contenido } = publicacion;
  const hoy = hoyISO();
  let texto = "";
  const cuerpo = el("div", { class: "tabla tabla-empleado" });

  function pintar() {
    const visibles = contenido.items.filter((i) => `${i.nombre} ${i.sku} ${i.categoria}`.toLowerCase().includes(texto));
    pintarEn(cuerpo, filaDeEncabezado(true),
      ...(visibles.length
        ? visibles.map((i) => filaPublicada(i, contenido.moneda, hoy, contenido.perfil.lineas || []))
        : [el("div", { class: "vacio" }, "Nada coincide con la búsqueda.")]));
  }

  pintarEn(principal, 
    avisoDeConsulta(),
    encabezado({
      titulo: "Catálogo publicado",
      texto: `Versión ${publicacion.version}, publicada el ${fechaHora(publicacion.publicada_en)}. Es lo mismo que ofrece el bot.`,
      acciones: [el("label", { class: "buscador" }, icono("buscar"),
        el("input", { type: "search", placeholder: "Buscar por nombre o código", "aria-label": "Buscar",
          oninput: (e) => { texto = e.target.value.trim().toLowerCase(); pintar(); } }))],
    }),
    cuerpo);
  pintar();
}

function filaPublicada(item, moneda, hoy, lineas = []) {
  let pill = el("span", { class: "pill pill-ok ocultable" }, "Disponible");
  if (item.vigente_hasta && item.vigente_hasta < hoy) pill = el("span", { class: "pill pill-apagado ocultable" }, "Vencido");
  else if (item.agotado) pill = el("span", { class: "pill pill-aviso ocultable" }, "Agotado");
  else if (item.vigente_desde && item.vigente_desde > hoy) pill = el("span", { class: "pill pill-aviso ocultable" }, `Desde ${fecha(item.vigente_desde)}`);
  const resumen = resumenDelItem(item, lineas);
  return el("div", { class: "fila" },
    miniatura(item.fotos),
    el("div", { class: "nombre-item" }, nombreConEstado(item), el("span", { title: resumen }, resumen || tipoDelItem(item))),
    el("span", { class: "celda mono ocultable" }, item.sku),
    el("span", { class: "celda ocultable" }, tipoDelItem(item)),
    celdaDePrecio(item, moneda),
    el("span", { class: "celda-opciones ocultable" }, resumenDeOpciones(item)),
    pill);
}

async function vistaNegocioPublicado(principal) {
  const { publicacion } = await api("GET", "/api/publicado");
  const perfil = publicacion?.contenido.perfil;
  const filas = perfil ? [
    ["Nombre", perfil.nombre_publico], ["A qué se dedica", perfil.descripcion], ["Dirección", perfil.direccion],
    ["Mapa", perfil.mapa_url], ["Horarios", perfil.horarios], ["Formas de pago", perfil.formas_de_pago.join(", ")],
    ["Nota sobre pagos", perfil.nota_pagos], ["Envíos y entregas", perfil.envios], ["Políticas", perfil.politicas],
  ].filter(([, valor]) => valor) : [];

  pintarEn(principal, 
    avisoDeConsulta(),
    encabezado({ titulo: "Mi negocio", texto: "Lo que el bot sabe del negocio, según la última publicación." }),
    el("div", { class: "formulario" },
      el("section", { class: "tarjeta" },
        filas.length
          ? el("dl", { class: "datos-lectura" }, filas.flatMap(([clave, valor]) => [el("dt", {}, clave), el("dd", {}, valor)]))
          : el("p", { class: "tenue" }, "Todavía no hay datos publicados.")),
      perfil?.lineas?.length
        ? el("section", { class: "tarjeta" }, el("h2", {}, "Líneas de WhatsApp y sucursales"),
          el("dl", { class: "datos-lectura" }, perfil.lineas.flatMap((l) => [el("dt", {}, l.nombre),
            el("dd", {}, [l.direccion, l.horarios].filter(Boolean).join(" · ") || "Misma dirección y horarios del negocio.")])))
        : null,
      perfil?.preguntas.length
        ? el("section", { class: "tarjeta" }, el("h2", {}, "Preguntas frecuentes"),
          el("dl", { class: "datos-lectura" }, perfil.preguntas.flatMap((p) => [el("dt", {}, p.pregunta), el("dd", {}, p.respuesta)])))
        : null));
}
