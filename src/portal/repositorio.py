"""Dónde se guardan los datos del portal, visto desde la aplicación.

`Repositorio` es la forma; hay dos implementaciones con el mismo contrato:

- `RepositorioEnMemoria` (acá): para los tests, sin base ni red.
- `RepositorioPostgres` (`postgres.py`): el de verdad.

Los dos pasan las mismas pruebas (`tests/test_portal_repositorio.py`). Si
agregás un método, va en los dos y en esas pruebas.

**Todo lo de un negocio se pide con su `cliente_id`.** No hay un "dame el
ítem 7" suelto: es "dame el ítem 7 del negocio X", y si el 7 es de otro
negocio no existe. Esa es la separación entre clientes, y vive acá abajo y
no solo en la pantalla.

Las fechas salen como texto ISO y los importes como texto con dos
decimales, igual en las dos implementaciones.
"""

from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone
from typing import Protocol

from .modelo import ajustes_por_defecto, perfil_vacio


class YaExiste(Exception):
    """Ya hay un registro con ese identificador (negocio, correo o código)."""


class Repositorio(Protocol):
    # Negocios, usuarios y accesos
    def crear_cliente(self, cliente_id: str, nombre: str) -> None: ...
    def cliente(self, cliente_id: str) -> dict | None: ...
    def borrar_cliente(self, cliente_id: str) -> None: ...
    def crear_usuario(self, correo: str, nombre: str, clave_hash: str) -> int: ...
    def usuario_por_correo(self, correo: str) -> dict | None: ...
    def borrar_usuario(self, usuario_id: int) -> None: ...
    def cambiar_clave(self, usuario_id: int, clave_hash: str) -> None: ...
    def dar_acceso(self, usuario_id: int, cliente_id: str, rol: str) -> None: ...
    def accesos(self, usuario_id: int) -> list[dict]: ...

    # Sesiones
    def crear_sesion(self, huella: str, usuario_id: int, cliente_id: str, expira_en: datetime) -> None: ...
    def sesion(self, huella: str, ahora: datetime) -> dict | None: ...
    def cambiar_negocio_de_sesion(self, huella: str, cliente_id: str) -> None: ...
    def borrar_sesion(self, huella: str) -> None: ...
    def borrar_sesiones_de(self, usuario_id: int) -> None: ...

    # Mi negocio y reglas de precio
    def perfil(self, cliente_id: str) -> dict: ...
    def guardar_perfil(self, cliente_id: str, datos: dict, usuario_id: int | None) -> None: ...
    def ajustes(self, cliente_id: str) -> dict: ...
    def guardar_ajustes(self, cliente_id: str, datos: dict, usuario_id: int | None) -> None: ...

    # Ítems y fotos
    def items(self, cliente_id: str) -> list[dict]: ...
    def item(self, cliente_id: str, item_id: int) -> dict | None: ...
    def crear_item(self, cliente_id: str, datos: dict) -> dict: ...
    def actualizar_item(self, cliente_id: str, item_id: int, datos: dict) -> dict | None: ...
    def borrar_item(self, cliente_id: str, item_id: int) -> bool: ...
    def agregar_foto(self, cliente_id: str, item_id: int, foto: dict) -> dict: ...
    def foto(self, cliente_id: str, foto_id: str) -> dict | None: ...
    def fotos_vigentes(self, cliente_id: str) -> list[dict]: ...
    def retirar_foto(self, cliente_id: str, item_id: int, foto_id: str) -> bool: ...

    # Publicaciones
    def publicar(self, cliente_id: str, contenido: dict, huella: str, usuario_id: int | None) -> dict: ...
    def ultima_publicacion(self, cliente_id: str) -> dict | None: ...
    def publicaciones(self, cliente_id: str, limite: int = 20) -> list[dict]: ...

    # Claves de los bots y auditoría
    def crear_clave_bot(self, huella: str, cliente_id: str, nombre: str) -> None: ...
    def cliente_de_clave_bot(self, huella: str) -> str | None: ...
    def revocar_claves_bot(self, cliente_id: str) -> int: ...
    def auditar(self, cliente_id: str | None, usuario_id: int | None, accion: str, detalle: dict) -> None: ...
    def auditoria(self, cliente_id: str, limite: int = 50) -> list[dict]: ...


def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RepositorioEnMemoria:
    """El mismo contrato que Postgres, en diccionarios. Para los tests."""

    def __init__(self) -> None:
        self._candado = threading.RLock()
        self._clientes: dict[str, dict] = {}
        self._usuarios: dict[int, dict] = {}
        self._accesos: dict[tuple[int, str], str] = {}
        self._sesiones: dict[str, dict] = {}
        self._perfiles: dict[str, dict] = {}
        self._ajustes: dict[str, dict] = {}
        self._items: dict[int, dict] = {}
        self._fotos: dict[str, dict] = {}
        self._publicaciones: list[dict] = []
        self._claves: dict[str, dict] = {}
        self._auditoria: list[dict] = []
        self._siguiente = 1

    def _nuevo_id(self) -> int:
        self._siguiente += 1
        return self._siguiente

    # -- Negocios, usuarios y accesos ------------------------------------------

    def crear_cliente(self, cliente_id: str, nombre: str) -> None:
        with self._candado:
            if cliente_id in self._clientes:
                raise YaExiste(cliente_id)
            self._clientes[cliente_id] = {"id": cliente_id, "nombre": nombre}

    def cliente(self, cliente_id: str) -> dict | None:
        with self._candado:
            return copy.deepcopy(self._clientes.get(cliente_id))

    def borrar_cliente(self, cliente_id: str) -> None:
        with self._candado:
            self._clientes.pop(cliente_id, None)
            self._accesos = {k: v for k, v in self._accesos.items() if k[1] != cliente_id}
            self._sesiones = {k: v for k, v in self._sesiones.items() if v["cliente_id"] != cliente_id}
            self._perfiles.pop(cliente_id, None)
            self._ajustes.pop(cliente_id, None)
            self._items = {k: v for k, v in self._items.items() if v["cliente_id"] != cliente_id}
            self._fotos = {k: v for k, v in self._fotos.items() if v["cliente_id"] != cliente_id}
            self._publicaciones = [p for p in self._publicaciones if p["cliente_id"] != cliente_id]
            self._claves = {k: v for k, v in self._claves.items() if v["cliente_id"] != cliente_id}
            self._auditoria = [a for a in self._auditoria if a["cliente_id"] != cliente_id]

    def crear_usuario(self, correo: str, nombre: str, clave_hash: str) -> int:
        with self._candado:
            if any(u["correo"] == correo for u in self._usuarios.values()):
                raise YaExiste(correo)
            usuario_id = self._nuevo_id()
            self._usuarios[usuario_id] = {
                "id": usuario_id, "correo": correo, "nombre": nombre,
                "clave_hash": clave_hash, "activo": True,
            }
            return usuario_id

    def usuario_por_correo(self, correo: str) -> dict | None:
        with self._candado:
            for usuario in self._usuarios.values():
                if usuario["correo"] == correo:
                    return copy.deepcopy(usuario)
            return None

    def borrar_usuario(self, usuario_id: int) -> None:
        with self._candado:
            self._usuarios.pop(usuario_id, None)
            self._accesos = {k: v for k, v in self._accesos.items() if k[0] != usuario_id}
            self._sesiones = {k: v for k, v in self._sesiones.items() if v["usuario_id"] != usuario_id}

    def cambiar_clave(self, usuario_id: int, clave_hash: str) -> None:
        with self._candado:
            self._usuarios[usuario_id]["clave_hash"] = clave_hash

    def dar_acceso(self, usuario_id: int, cliente_id: str, rol: str) -> None:
        with self._candado:
            if usuario_id not in self._usuarios or cliente_id not in self._clientes:
                raise LookupError("No existe el usuario o el negocio.")
            self._accesos[(usuario_id, cliente_id)] = rol

    def accesos(self, usuario_id: int) -> list[dict]:
        with self._candado:
            filas = [
                {"cliente_id": cliente_id, "nombre": self._clientes[cliente_id]["nombre"], "rol": rol}
                for (uid, cliente_id), rol in self._accesos.items()
                if uid == usuario_id
            ]
            return sorted(filas, key=lambda f: (f["nombre"], f["cliente_id"]))

    # -- Sesiones ---------------------------------------------------------------

    def crear_sesion(self, huella: str, usuario_id: int, cliente_id: str, expira_en: datetime) -> None:
        with self._candado:
            self._sesiones[huella] = {"usuario_id": usuario_id, "cliente_id": cliente_id, "expira_en": expira_en}

    def sesion(self, huella: str, ahora: datetime) -> dict | None:
        with self._candado:
            fila = self._sesiones.get(huella)
            if fila is None or fila["expira_en"] <= ahora:
                return None
            usuario = self._usuarios.get(fila["usuario_id"])
            rol = self._accesos.get((fila["usuario_id"], fila["cliente_id"]))
            # Se revisa en cada pedido: si le sacaron el acceso o desactivaron
            # la cuenta, la sesión que ya tenía abierta deja de servir.
            if usuario is None or not usuario["activo"] or rol is None:
                return None
            return {
                "huella": huella,
                "usuario_id": usuario["id"],
                "correo": usuario["correo"],
                "nombre": usuario["nombre"],
                "cliente_id": fila["cliente_id"],
                "negocio": self._clientes[fila["cliente_id"]]["nombre"],
                "rol": rol,
            }

    def cambiar_negocio_de_sesion(self, huella: str, cliente_id: str) -> None:
        with self._candado:
            if huella in self._sesiones:
                self._sesiones[huella]["cliente_id"] = cliente_id

    def borrar_sesion(self, huella: str) -> None:
        with self._candado:
            self._sesiones.pop(huella, None)

    def borrar_sesiones_de(self, usuario_id: int) -> None:
        with self._candado:
            self._sesiones = {k: v for k, v in self._sesiones.items() if v["usuario_id"] != usuario_id}

    # -- Mi negocio y reglas de precio -------------------------------------------

    def perfil(self, cliente_id: str) -> dict:
        with self._candado:
            return copy.deepcopy(perfil_vacio() | self._perfiles.get(cliente_id, {}))

    def guardar_perfil(self, cliente_id: str, datos: dict, usuario_id: int | None) -> None:
        with self._candado:
            self._perfiles[cliente_id] = copy.deepcopy(datos)

    def ajustes(self, cliente_id: str) -> dict:
        with self._candado:
            return copy.deepcopy(self._ajustes.get(cliente_id, ajustes_por_defecto()))

    def guardar_ajustes(self, cliente_id: str, datos: dict, usuario_id: int | None) -> None:
        with self._candado:
            self._ajustes[cliente_id] = copy.deepcopy(datos)

    # -- Ítems y fotos -------------------------------------------------------------

    def items(self, cliente_id: str) -> list[dict]:
        with self._candado:
            filas = [self._publico(i) for i in self._items.values() if i["cliente_id"] == cliente_id]
            return sorted(filas, key=lambda i: i["sku"])

    def item(self, cliente_id: str, item_id: int) -> dict | None:
        with self._candado:
            fila = self._items.get(item_id)
            if fila is None or fila["cliente_id"] != cliente_id:
                return None
            return self._publico(fila)

    def crear_item(self, cliente_id: str, datos: dict) -> dict:
        with self._candado:
            if any(i["cliente_id"] == cliente_id and i["sku"] == datos["sku"] for i in self._items.values()):
                raise YaExiste(datos["sku"])
            item_id = self._nuevo_id()
            self._items[item_id] = copy.deepcopy(datos) | {
                "id": item_id, "cliente_id": cliente_id, "actualizado_en": ahora_iso(),
            }
            return self._publico(self._items[item_id])

    def actualizar_item(self, cliente_id: str, item_id: int, datos: dict) -> dict | None:
        with self._candado:
            fila = self._items.get(item_id)
            if fila is None or fila["cliente_id"] != cliente_id:
                return None
            cambios = {k: v for k, v in copy.deepcopy(datos).items() if k != "sku"}
            fila.update(cambios | {"actualizado_en": ahora_iso()})
            return self._publico(fila)

    def borrar_item(self, cliente_id: str, item_id: int) -> bool:
        with self._candado:
            fila = self._items.get(item_id)
            if fila is None or fila["cliente_id"] != cliente_id:
                return False
            del self._items[item_id]
            # La foto queda: la última publicación puede seguir usándola
            # hasta que se publique de nuevo.
            for foto in self._fotos.values():
                if foto["item_id"] == item_id:
                    foto["item_id"] = None
            return True

    def agregar_foto(self, cliente_id: str, item_id: int, foto: dict) -> dict:
        with self._candado:
            if self.item(cliente_id, item_id) is None:
                raise LookupError("El ítem no es de este negocio.")
            fila = copy.deepcopy(foto) | {
                "cliente_id": cliente_id, "item_id": item_id,
                "creada_en": ahora_iso(), "retirada_en": None,
            }
            self._fotos[fila["id"]] = fila
            return self._foto_publica(fila)

    def foto(self, cliente_id: str, foto_id: str) -> dict | None:
        with self._candado:
            fila = self._fotos.get(foto_id)
            if fila is None or fila["cliente_id"] != cliente_id:
                return None
            return self._foto_publica(fila)

    def fotos_vigentes(self, cliente_id: str) -> list[dict]:
        with self._candado:
            filas = [
                self._foto_publica(f) for f in self._fotos.values()
                if f["cliente_id"] == cliente_id and f["item_id"] is not None and f["retirada_en"] is None
            ]
            return sorted(filas, key=lambda f: (f["creada_en"], f["id"]))

    def retirar_foto(self, cliente_id: str, item_id: int, foto_id: str) -> bool:
        with self._candado:
            fila = self._fotos.get(foto_id)
            if (
                fila is None or fila["cliente_id"] != cliente_id
                or fila["item_id"] != item_id or fila["retirada_en"] is not None
            ):
                return False
            fila["retirada_en"] = ahora_iso()
            return True

    # -- Publicaciones ----------------------------------------------------------------

    def publicar(self, cliente_id: str, contenido: dict, huella: str, usuario_id: int | None) -> dict:
        with self._candado:
            version = 1 + max(
                (p["version"] for p in self._publicaciones if p["cliente_id"] == cliente_id), default=0
            )
            fila = {
                "cliente_id": cliente_id, "version": version, "huella": huella,
                "contenido": copy.deepcopy(contenido), "publicada_en": ahora_iso(),
                "publicada_por": self._usuarios[usuario_id]["nombre"] if usuario_id in self._usuarios else "",
            }
            self._publicaciones.append(fila)
            return {k: fila[k] for k in ("version", "huella", "publicada_en", "publicada_por")}

    def ultima_publicacion(self, cliente_id: str) -> dict | None:
        with self._candado:
            propias = [p for p in self._publicaciones if p["cliente_id"] == cliente_id]
            if not propias:
                return None
            fila = max(propias, key=lambda p: p["version"])
            return {k: copy.deepcopy(fila[k]) for k in ("version", "huella", "publicada_en", "publicada_por", "contenido")}

    def publicaciones(self, cliente_id: str, limite: int = 20) -> list[dict]:
        with self._candado:
            propias = sorted(
                (p for p in self._publicaciones if p["cliente_id"] == cliente_id),
                key=lambda p: p["version"], reverse=True,
            )
            return [
                {k: p[k] for k in ("version", "huella", "publicada_en", "publicada_por")}
                for p in propias[:limite]
            ]

    # -- Claves de los bots y auditoría -------------------------------------------------

    def crear_clave_bot(self, huella: str, cliente_id: str, nombre: str) -> None:
        with self._candado:
            self._claves[huella] = {"cliente_id": cliente_id, "nombre": nombre, "revocada": False}

    def cliente_de_clave_bot(self, huella: str) -> str | None:
        with self._candado:
            fila = self._claves.get(huella)
            if fila is None or fila["revocada"] or fila["cliente_id"] not in self._clientes:
                return None
            return fila["cliente_id"]

    def revocar_claves_bot(self, cliente_id: str) -> int:
        with self._candado:
            revocadas = 0
            for fila in self._claves.values():
                if fila["cliente_id"] == cliente_id and not fila["revocada"]:
                    fila["revocada"] = True
                    revocadas += 1
            return revocadas

    def auditar(self, cliente_id: str | None, usuario_id: int | None, accion: str, detalle: dict) -> None:
        with self._candado:
            self._auditoria.append({
                "cliente_id": cliente_id, "usuario_id": usuario_id, "accion": accion,
                "detalle": copy.deepcopy(detalle), "en": ahora_iso(),
            })

    def auditoria(self, cliente_id: str, limite: int = 50) -> list[dict]:
        with self._candado:
            propias = [a for a in self._auditoria if a["cliente_id"] == cliente_id]
            return [copy.deepcopy(a) for a in reversed(propias[-limite:])]

    # -- Formas de salida -------------------------------------------------------------

    @staticmethod
    def _publico(fila: dict) -> dict:
        return {k: copy.deepcopy(v) for k, v in fila.items() if k != "cliente_id"}

    @staticmethod
    def _foto_publica(fila: dict) -> dict:
        return {k: fila[k] for k in ("id", "item_id", "clave", "mime", "bytes", "sha256", "creada_en")}
