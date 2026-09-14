"""El repositorio de verdad: PostgreSQL.

Mismo contrato que `RepositorioEnMemoria` (ver `repositorio.py`). Cada
consulta de datos de un negocio lleva `cliente_id` en el WHERE, y las
fotos tienen una clave foránea compuesta (negocio, ítem): ni con un error
en la aplicación una foto puede quedar colgada del ítem de otro negocio.

La base se prepara sola al arrancar (`migrar`): solo crea lo que falta.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .modelo import ajustes_por_defecto, perfil_vacio
from .repositorio import YaExiste

ESQUEMA = """
CREATE TABLE IF NOT EXISTS clientes (
    id text PRIMARY KEY CHECK (id ~ '^[a-z0-9][a-z0-9-]{1,40}$'),
    nombre text NOT NULL,
    creado_en timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS usuarios (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    correo text NOT NULL UNIQUE CHECK (correo = lower(correo)),
    nombre text NOT NULL,
    clave_hash text NOT NULL,
    activo boolean NOT NULL DEFAULT true,
    creado_en timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS accesos (
    usuario_id bigint NOT NULL REFERENCES usuarios (id) ON DELETE CASCADE,
    cliente_id text NOT NULL REFERENCES clientes (id) ON DELETE CASCADE,
    rol text NOT NULL CHECK (rol IN ('administrador', 'empleado')),
    PRIMARY KEY (usuario_id, cliente_id)
);

CREATE TABLE IF NOT EXISTS sesiones (
    huella text PRIMARY KEY,
    usuario_id bigint NOT NULL REFERENCES usuarios (id) ON DELETE CASCADE,
    cliente_id text NOT NULL REFERENCES clientes (id) ON DELETE CASCADE,
    creada_en timestamptz NOT NULL DEFAULT now(),
    expira_en timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS sesiones_por_usuario ON sesiones (usuario_id);

CREATE TABLE IF NOT EXISTS perfiles (
    cliente_id text PRIMARY KEY REFERENCES clientes (id) ON DELETE CASCADE,
    datos jsonb NOT NULL,
    actualizado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_por bigint REFERENCES usuarios (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS ajustes_catalogo (
    cliente_id text PRIMARY KEY REFERENCES clientes (id) ON DELETE CASCADE,
    moneda text NOT NULL,
    cantidad_maxima integer,
    descuentos jsonb NOT NULL,
    actualizado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_por bigint REFERENCES usuarios (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS items (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cliente_id text NOT NULL REFERENCES clientes (id) ON DELETE CASCADE,
    sku text NOT NULL,
    tipo text NOT NULL CHECK (tipo IN ('producto', 'servicio', 'promocion')),
    nombre text NOT NULL,
    categoria text NOT NULL DEFAULT '',
    descripcion text NOT NULL DEFAULT '',
    precio numeric(12, 2),
    unidad text NOT NULL DEFAULT '',
    vigente_desde date,
    vigente_hasta date,
    opciones jsonb NOT NULL DEFAULT '[]',
    extras jsonb NOT NULL DEFAULT '[]',
    cotizacion_automatica boolean NOT NULL DEFAULT false,
    activo boolean NOT NULL DEFAULT true,
    actualizado_en timestamptz NOT NULL DEFAULT now(),
    UNIQUE (cliente_id, sku),
    UNIQUE (cliente_id, id)
);

-- La moneda por ítem llegó después de la primera versión. Se agrega así para
-- que también la reciban las bases ya creadas: los ítems que existían toman
-- la moneda que su negocio tenía en las reglas de precio.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'items' AND column_name = 'moneda'
    ) THEN
        ALTER TABLE items ADD COLUMN moneda text NOT NULL DEFAULT 'USD' CHECK (moneda IN ('USD', 'NIO'));
        UPDATE items i SET moneda = a.moneda
        FROM ajustes_catalogo a WHERE a.cliente_id = i.cliente_id;
    END IF;
END $$;

-- También llegaron después: dónde se ofrece el ítem, precio «desde» y
-- agotado. Los valores por defecto dejan todo como estaba.
ALTER TABLE items ADD COLUMN IF NOT EXISTS precio_desde boolean NOT NULL DEFAULT false;
ALTER TABLE items ADD COLUMN IF NOT EXISTS lineas jsonb NOT NULL DEFAULT '[]';
ALTER TABLE items ADD COLUMN IF NOT EXISTS agotado boolean NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS fotos (
    id text PRIMARY KEY CHECK (id ~ '^[0-9a-f]{32}$'),
    cliente_id text NOT NULL REFERENCES clientes (id) ON DELETE CASCADE,
    item_id bigint,
    clave text NOT NULL UNIQUE,
    mime text NOT NULL,
    bytes integer NOT NULL,
    sha256 text NOT NULL,
    creada_en timestamptz NOT NULL DEFAULT now(),
    retirada_en timestamptz,
    -- Al borrar el ítem la foto queda sin ítem, no se borra: la última
    -- publicación puede seguir usándola hasta que se publique de nuevo.
    FOREIGN KEY (cliente_id, item_id) REFERENCES items (cliente_id, id)
        ON DELETE SET NULL (item_id)
);
CREATE INDEX IF NOT EXISTS fotos_por_item ON fotos (cliente_id, item_id);

CREATE TABLE IF NOT EXISTS publicaciones (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cliente_id text NOT NULL REFERENCES clientes (id) ON DELETE CASCADE,
    version integer NOT NULL,
    contenido jsonb NOT NULL,
    huella text NOT NULL,
    publicada_en timestamptz NOT NULL DEFAULT now(),
    publicada_por bigint REFERENCES usuarios (id) ON DELETE SET NULL,
    UNIQUE (cliente_id, version)
);

CREATE TABLE IF NOT EXISTS claves_bot (
    huella text PRIMARY KEY,
    cliente_id text NOT NULL REFERENCES clientes (id) ON DELETE CASCADE,
    nombre text NOT NULL,
    creada_en timestamptz NOT NULL DEFAULT now(),
    revocada_en timestamptz
);

CREATE TABLE IF NOT EXISTS auditoria (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cliente_id text REFERENCES clientes (id) ON DELETE CASCADE,
    usuario_id bigint REFERENCES usuarios (id) ON DELETE SET NULL,
    accion text NOT NULL,
    detalle jsonb NOT NULL DEFAULT '{}',
    en timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS auditoria_por_cliente ON auditoria (cliente_id, en DESC);
"""

# Un número fijo cualquiera: dos procesos que arrancan a la vez no preparan
# la base en paralelo.
_CANDADO_DE_MIGRACION = 5_140_926

_COLUMNAS_ITEM = (
    "id, sku, tipo, nombre, categoria, descripcion, precio, moneda, precio_desde, unidad, vigente_desde, "
    "vigente_hasta, opciones, extras, lineas, cotizacion_automatica, agotado, activo, actualizado_en"
)
_COLUMNAS_FOTO = "id, item_id, clave, mime, bytes, sha256, creada_en"


class RepositorioPostgres:
    def __init__(self, dsn: str, maximo_conexiones: int = 3) -> None:
        # Un pool chico: el portal lo usan pocas personas a la vez, y el
        # PostgreSQL es el mismo que el de las memorias de los bots. Tiene que
        # entrar en el límite del rol (5 en catalogos_pruebas) dejando lugar
        # para el comando de administración y las pruebas: con 4 se llenó.
        self._pool = ConnectionPool(
            dsn,
            min_size=1,
            max_size=maximo_conexiones,
            kwargs={"row_factory": dict_row},
            # Antes de prestar una conexión, confirma que sigue viva. Un corte
            # de red o el cierre por inactividad del servidor la dejan muerta,
            # y sin esto el primer pedido después falla.
            check=ConnectionPool.check_connection,
            # Suelta las conexiones que sobran después de un rato quieto.
            max_idle=300,
            open=True,
        )

    def cerrar(self) -> None:
        self._pool.close()

    def migrar(self) -> None:
        with self._pool.connection() as conexion:
            conexion.execute("SELECT pg_advisory_xact_lock(%s)", (_CANDADO_DE_MIGRACION,))
            conexion.execute(ESQUEMA)

    # -- Negocios, usuarios y accesos ------------------------------------------

    def crear_cliente(self, cliente_id: str, nombre: str) -> None:
        try:
            with self._pool.connection() as conexion:
                conexion.execute(
                    "INSERT INTO clientes (id, nombre) VALUES (%s, %s)", (cliente_id, nombre)
                )
        except psycopg.errors.UniqueViolation:
            raise YaExiste(cliente_id) from None

    def cliente(self, cliente_id: str) -> dict | None:
        return self._una("SELECT id, nombre FROM clientes WHERE id = %s", (cliente_id,))

    def borrar_cliente(self, cliente_id: str) -> None:
        self._ejecutar("DELETE FROM clientes WHERE id = %s", (cliente_id,))

    def crear_usuario(self, correo: str, nombre: str, clave_hash: str) -> int:
        try:
            fila = self._una(
                "INSERT INTO usuarios (correo, nombre, clave_hash) VALUES (%s, %s, %s) RETURNING id",
                (correo, nombre, clave_hash),
            )
        except psycopg.errors.UniqueViolation:
            raise YaExiste(correo) from None
        return fila["id"]

    def usuario_por_correo(self, correo: str) -> dict | None:
        return self._una(
            "SELECT id, correo, nombre, clave_hash, activo FROM usuarios WHERE correo = %s",
            (correo,),
        )

    def borrar_usuario(self, usuario_id: int) -> None:
        self._ejecutar("DELETE FROM usuarios WHERE id = %s", (usuario_id,))

    def cambiar_correo(self, usuario_id: int, correo: str) -> None:
        try:
            self._ejecutar("UPDATE usuarios SET correo = %s WHERE id = %s", (correo, usuario_id))
        except psycopg.errors.UniqueViolation:
            raise YaExiste(correo) from None

    def cambiar_clave(self, usuario_id: int, clave_hash: str) -> None:
        self._ejecutar("UPDATE usuarios SET clave_hash = %s WHERE id = %s", (clave_hash, usuario_id))

    def dar_acceso(self, usuario_id: int, cliente_id: str, rol: str) -> None:
        try:
            self._ejecutar(
                """
                INSERT INTO accesos (usuario_id, cliente_id, rol) VALUES (%s, %s, %s)
                ON CONFLICT (usuario_id, cliente_id) DO UPDATE SET rol = EXCLUDED.rol
                """,
                (usuario_id, cliente_id, rol),
            )
        except psycopg.errors.ForeignKeyViolation:
            raise LookupError("No existe el usuario o el negocio.") from None

    def accesos(self, usuario_id: int) -> list[dict]:
        return self._varias(
            """
            SELECT a.cliente_id, c.nombre, a.rol
            FROM accesos a JOIN clientes c ON c.id = a.cliente_id
            WHERE a.usuario_id = %s
            ORDER BY c.nombre, a.cliente_id
            """,
            (usuario_id,),
        )

    # -- Sesiones ---------------------------------------------------------------

    def crear_sesion(self, huella: str, usuario_id: int, cliente_id: str, expira_en: datetime) -> None:
        self._ejecutar(
            "INSERT INTO sesiones (huella, usuario_id, cliente_id, expira_en) VALUES (%s, %s, %s, %s)",
            (huella, usuario_id, cliente_id, expira_en),
        )

    def sesion(self, huella: str, ahora: datetime) -> dict | None:
        # El JOIN con accesos es la parte importante: si le sacaron el acceso
        # o desactivaron la cuenta, la sesión abierta deja de servir.
        return self._una(
            """
            SELECT s.huella, u.id AS usuario_id, u.correo, u.nombre,
                   s.cliente_id, c.nombre AS negocio, a.rol
            FROM sesiones s
            JOIN usuarios u ON u.id = s.usuario_id AND u.activo
            JOIN accesos a ON a.usuario_id = s.usuario_id AND a.cliente_id = s.cliente_id
            JOIN clientes c ON c.id = s.cliente_id
            WHERE s.huella = %s AND s.expira_en > %s
            """,
            (huella, ahora),
        )

    def cambiar_negocio_de_sesion(self, huella: str, cliente_id: str) -> None:
        self._ejecutar("UPDATE sesiones SET cliente_id = %s WHERE huella = %s", (cliente_id, huella))

    def borrar_sesion(self, huella: str) -> None:
        self._ejecutar("DELETE FROM sesiones WHERE huella = %s", (huella,))

    def borrar_sesiones_de(self, usuario_id: int) -> None:
        self._ejecutar("DELETE FROM sesiones WHERE usuario_id = %s", (usuario_id,))

    # -- Mi negocio y reglas de precio -------------------------------------------

    def perfil(self, cliente_id: str) -> dict:
        fila = self._una("SELECT datos FROM perfiles WHERE cliente_id = %s", (cliente_id,))
        # Completa con los campos que se sumaron después de guardarlo.
        return (perfil_vacio() | fila["datos"]) if fila else perfil_vacio()

    def guardar_perfil(self, cliente_id: str, datos: dict, usuario_id: int | None) -> None:
        self._ejecutar(
            """
            INSERT INTO perfiles (cliente_id, datos, actualizado_por) VALUES (%s, %s, %s)
            ON CONFLICT (cliente_id) DO UPDATE
            SET datos = EXCLUDED.datos, actualizado_por = EXCLUDED.actualizado_por, actualizado_en = now()
            """,
            (cliente_id, Jsonb(datos), usuario_id),
        )

    def ajustes(self, cliente_id: str) -> dict:
        fila = self._una(
            "SELECT moneda, cantidad_maxima, descuentos FROM ajustes_catalogo WHERE cliente_id = %s",
            (cliente_id,),
        )
        return fila if fila else ajustes_por_defecto()

    def guardar_ajustes(self, cliente_id: str, datos: dict, usuario_id: int | None) -> None:
        self._ejecutar(
            """
            INSERT INTO ajustes_catalogo (cliente_id, moneda, cantidad_maxima, descuentos, actualizado_por)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (cliente_id) DO UPDATE
            SET moneda = EXCLUDED.moneda, cantidad_maxima = EXCLUDED.cantidad_maxima,
                descuentos = EXCLUDED.descuentos, actualizado_por = EXCLUDED.actualizado_por,
                actualizado_en = now()
            """,
            (cliente_id, datos["moneda"], datos["cantidad_maxima"], Jsonb(datos["descuentos"]), usuario_id),
        )

    # -- Ítems y fotos -------------------------------------------------------------

    def items(self, cliente_id: str) -> list[dict]:
        filas = self._varias(
            f"SELECT {_COLUMNAS_ITEM} FROM items WHERE cliente_id = %s ORDER BY sku", (cliente_id,)
        )
        return [_item(f) for f in filas]

    def item(self, cliente_id: str, item_id: int) -> dict | None:
        fila = self._una(
            f"SELECT {_COLUMNAS_ITEM} FROM items WHERE cliente_id = %s AND id = %s",
            (cliente_id, item_id),
        )
        return _item(fila) if fila else None

    def crear_item(self, cliente_id: str, datos: dict) -> dict:
        try:
            fila = self._una(
                f"""
                INSERT INTO items (cliente_id, sku, tipo, nombre, categoria, descripcion, precio, moneda,
                    precio_desde, unidad, vigente_desde, vigente_hasta, opciones, extras, lineas,
                    cotizacion_automatica, agotado, activo)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING {_COLUMNAS_ITEM}
                """,
                (cliente_id, datos["sku"], *_valores_de_item(datos)),
            )
        except psycopg.errors.UniqueViolation:
            raise YaExiste(datos["sku"]) from None
        return _item(fila)

    def actualizar_item(self, cliente_id: str, item_id: int, datos: dict) -> dict | None:
        fila = self._una(
            f"""
            UPDATE items SET tipo = %s, nombre = %s, categoria = %s, descripcion = %s, precio = %s,
                moneda = %s, precio_desde = %s, unidad = %s, vigente_desde = %s, vigente_hasta = %s,
                opciones = %s, extras = %s, lineas = %s, cotizacion_automatica = %s, agotado = %s,
                activo = %s, actualizado_en = now()
            WHERE cliente_id = %s AND id = %s
            RETURNING {_COLUMNAS_ITEM}
            """,
            (*_valores_de_item(datos), cliente_id, item_id),
        )
        return _item(fila) if fila else None

    def borrar_item(self, cliente_id: str, item_id: int) -> bool:
        fila = self._una(
            "DELETE FROM items WHERE cliente_id = %s AND id = %s RETURNING id", (cliente_id, item_id)
        )
        return fila is not None

    def agregar_foto(self, cliente_id: str, item_id: int, foto: dict) -> dict:
        try:
            fila = self._una(
                f"""
                INSERT INTO fotos (id, cliente_id, item_id, clave, mime, bytes, sha256)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING {_COLUMNAS_FOTO}
                """,
                (foto["id"], cliente_id, item_id, foto["clave"], foto["mime"], foto["bytes"], foto["sha256"]),
            )
        except psycopg.errors.ForeignKeyViolation:
            raise LookupError("El ítem no es de este negocio.") from None
        return _foto(fila)

    def foto(self, cliente_id: str, foto_id: str) -> dict | None:
        fila = self._una(
            f"SELECT {_COLUMNAS_FOTO} FROM fotos WHERE cliente_id = %s AND id = %s", (cliente_id, foto_id)
        )
        return _foto(fila) if fila else None

    def fotos_vigentes(self, cliente_id: str) -> list[dict]:
        filas = self._varias(
            f"""
            SELECT {_COLUMNAS_FOTO} FROM fotos
            WHERE cliente_id = %s AND item_id IS NOT NULL AND retirada_en IS NULL
            ORDER BY creada_en, id
            """,
            (cliente_id,),
        )
        return [_foto(f) for f in filas]

    def retirar_foto(self, cliente_id: str, item_id: int, foto_id: str) -> bool:
        fila = self._una(
            """
            UPDATE fotos SET retirada_en = now()
            WHERE cliente_id = %s AND item_id = %s AND id = %s AND retirada_en IS NULL
            RETURNING id
            """,
            (cliente_id, item_id, foto_id),
        )
        return fila is not None

    # -- Publicaciones ----------------------------------------------------------------

    def publicar(self, cliente_id: str, contenido: dict, huella: str, usuario_id: int | None) -> dict:
        with self._pool.connection() as conexion:
            # Bloquea el negocio hasta el final de la transacción: dos
            # «Publicar» al mismo tiempo no pueden sacar el mismo número.
            conexion.execute("SELECT id FROM clientes WHERE id = %s FOR UPDATE", (cliente_id,))
            fila = conexion.execute(
                """
                INSERT INTO publicaciones (cliente_id, version, contenido, huella, publicada_por)
                SELECT %s, coalesce(max(version), 0) + 1, %s, %s, %s
                FROM publicaciones WHERE cliente_id = %s
                RETURNING version, huella, publicada_en,
                    (SELECT nombre FROM usuarios WHERE id = publicada_por) AS publicada_por
                """,
                (cliente_id, Jsonb(contenido), huella, usuario_id, cliente_id),
            ).fetchone()
        return _publicacion(fila)

    def ultima_publicacion(self, cliente_id: str) -> dict | None:
        fila = self._una(
            """
            SELECT p.version, p.huella, p.publicada_en, p.contenido, u.nombre AS publicada_por
            FROM publicaciones p LEFT JOIN usuarios u ON u.id = p.publicada_por
            WHERE p.cliente_id = %s
            ORDER BY p.version DESC LIMIT 1
            """,
            (cliente_id,),
        )
        return _publicacion(fila) if fila else None

    def publicaciones(self, cliente_id: str, limite: int = 20) -> list[dict]:
        filas = self._varias(
            """
            SELECT p.version, p.huella, p.publicada_en, u.nombre AS publicada_por
            FROM publicaciones p LEFT JOIN usuarios u ON u.id = p.publicada_por
            WHERE p.cliente_id = %s
            ORDER BY p.version DESC LIMIT %s
            """,
            (cliente_id, limite),
        )
        return [_publicacion(f) for f in filas]

    # -- Claves de los bots y auditoría -------------------------------------------------

    def crear_clave_bot(self, huella: str, cliente_id: str, nombre: str) -> None:
        self._ejecutar(
            "INSERT INTO claves_bot (huella, cliente_id, nombre) VALUES (%s, %s, %s)",
            (huella, cliente_id, nombre),
        )

    def cliente_de_clave_bot(self, huella: str) -> str | None:
        fila = self._una(
            "SELECT cliente_id FROM claves_bot WHERE huella = %s AND revocada_en IS NULL", (huella,)
        )
        return fila["cliente_id"] if fila else None

    def revocar_claves_bot(self, cliente_id: str) -> int:
        filas = self._varias(
            """
            UPDATE claves_bot SET revocada_en = now()
            WHERE cliente_id = %s AND revocada_en IS NULL RETURNING huella
            """,
            (cliente_id,),
        )
        return len(filas)

    def auditar(self, cliente_id: str | None, usuario_id: int | None, accion: str, detalle: dict) -> None:
        self._ejecutar(
            "INSERT INTO auditoria (cliente_id, usuario_id, accion, detalle) VALUES (%s, %s, %s, %s)",
            (cliente_id, usuario_id, accion, Jsonb(detalle)),
        )

    def auditoria(self, cliente_id: str, limite: int = 50) -> list[dict]:
        filas = self._varias(
            """
            SELECT cliente_id, usuario_id, accion, detalle, en FROM auditoria
            WHERE cliente_id = %s ORDER BY en DESC, id DESC LIMIT %s
            """,
            (cliente_id, limite),
        )
        return [f | {"en": f["en"].isoformat(timespec="seconds")} for f in filas]

    # -- Ayudas ---------------------------------------------------------------------------

    def _ejecutar(self, consulta: str, parametros: tuple) -> None:
        with self._pool.connection() as conexion:
            conexion.execute(consulta, parametros)

    def _una(self, consulta: str, parametros: tuple) -> dict | None:
        with self._pool.connection() as conexion:
            return conexion.execute(consulta, parametros).fetchone()

    def _varias(self, consulta: str, parametros: tuple) -> list[dict]:
        with self._pool.connection() as conexion:
            return conexion.execute(consulta, parametros).fetchall()


def _valores_de_item(datos: dict) -> tuple:
    return (
        datos["tipo"], datos["nombre"], datos["categoria"], datos["descripcion"],
        Decimal(datos["precio"]) if datos["precio"] is not None else None,
        datos["moneda"], datos["precio_desde"], datos["unidad"], datos["vigente_desde"], datos["vigente_hasta"],
        Jsonb(datos["opciones"]), Jsonb(datos["extras"]), Jsonb(datos["lineas"]),
        datos["cotizacion_automatica"], datos["agotado"], datos["activo"],
    )


def _item(fila: dict) -> dict:
    return fila | {
        "precio": f"{fila['precio']:.2f}" if fila["precio"] is not None else None,
        "vigente_desde": fila["vigente_desde"].isoformat() if fila["vigente_desde"] else None,
        "vigente_hasta": fila["vigente_hasta"].isoformat() if fila["vigente_hasta"] else None,
        "actualizado_en": fila["actualizado_en"].isoformat(timespec="seconds"),
    }


def _foto(fila: dict) -> dict:
    return fila | {"creada_en": fila["creada_en"].isoformat(timespec="seconds")}


def _publicacion(fila: dict) -> dict:
    return fila | {
        "publicada_en": fila["publicada_en"].isoformat(timespec="seconds"),
        "publicada_por": fila["publicada_por"] or "",
    }
