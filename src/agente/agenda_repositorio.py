"""Persistencia de agenda; transacciones cortas, separadas de la memoria del LLM."""

from __future__ import annotations

from contextlib import contextmanager
import atexit
import hashlib
import json
from pathlib import Path
import sqlite3
import threading


ESQUEMA = (
    """CREATE TABLE IF NOT EXISTS agenda_registros (
       negocio TEXT NOT NULL, clase TEXT NOT NULL, id TEXT NOT NULL,
       contacto TEXT NOT NULL DEFAULT '', estado TEXT NOT NULL DEFAULT '',
       instante DOUBLE PRECISION NOT NULL DEFAULT 0, final DOUBLE PRECISION NOT NULL DEFAULT 0, datos TEXT NOT NULL,
       PRIMARY KEY (negocio, clase, id))""",
    "CREATE INDEX IF NOT EXISTS agenda_pendientes ON agenda_registros (negocio, clase, estado, instante)",
    "CREATE INDEX IF NOT EXISTS agenda_por_contacto ON agenda_registros (negocio, clase, contacto)",
    "CREATE INDEX IF NOT EXISTS agenda_vigentes ON agenda_registros (negocio, clase, estado, final)",
)
CLASES = {"cita", "propuesta", "contacto", "externo", "envio", "control"}
_POOLS = {}
_CANDADO_POOLS = threading.Lock()


def _pool_postgres(destino):
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
    huella = hashlib.sha256(destino.encode()).hexdigest()
    with _CANDADO_POOLS:
        if huella not in _POOLS:
            # Varios repositorios de la misma aplicación comparten tres conexiones,
            # sin abrir otra por cada consulta ni retener conexiones de pruebas.
            pool = ConnectionPool(destino, min_size=1, max_size=3, timeout=20,
                                  kwargs={"row_factory": dict_row, "connect_timeout": 10},
                                  check=ConnectionPool.check_connection, open=False)
            pool.open(wait=True, timeout=15)
            _POOLS[huella] = pool
            atexit.register(pool.close)
        return _POOLS[huella]


class RepositorioAgenda:
    def __init__(self, destino: str, negocio: str):
        self.destino, self.negocio = destino, negocio
        self.postgres = destino.startswith(("postgresql://", "postgres://", "host=", "dbname=", "user=", "service="))
        self.candado = int.from_bytes(hashlib.sha256(("agenda:" + negocio).encode()).digest()[:8], "big", signed=True)
        if not self.postgres:
            Path(destino).parent.mkdir(parents=True, exist_ok=True)

    def _conectar(self):
        if self.postgres:
            return _pool_postgres(self.destino).getconn()
        conexion = sqlite3.connect(self.destino, timeout=15)
        conexion.row_factory = sqlite3.Row
        return conexion

    def preparar(self):
        with self.transaccion() as sesion:
            for sentencia in ESQUEMA:
                sesion.ejecutar(sentencia)

    @contextmanager
    def transaccion(self):
        conexion = self._conectar()
        try:
            if self.postgres:
                conexion.execute("SET LOCAL lock_timeout = '10s'")
                # El candado incluye negocio y funciona entre procesos/bandejas.
                conexion.execute("SELECT pg_advisory_xact_lock(%s)", (self.candado,))
            else:
                conexion.execute("BEGIN IMMEDIATE")
            yield SesionAgenda(conexion, self.negocio, self.postgres)
            conexion.commit()
        except BaseException:
            conexion.rollback()
            raise
        finally:
            if self.postgres:
                _pool_postgres(self.destino).putconn(conexion)
            else:
                conexion.close()


class SesionAgenda:
    def __init__(self, conexion, negocio, postgres):
        self.conexion, self.negocio, self.postgres = conexion, negocio, postgres

    def ejecutar(self, sql, parametros=()):
        return self.conexion.execute(sql.replace("?", "%s") if self.postgres else sql, parametros)

    def obtener(self, clase, identificador):
        fila = self.ejecutar("SELECT datos FROM agenda_registros WHERE negocio=? AND clase=? AND id=?",
                            (self.negocio, clase, identificador)).fetchone()
        return json.loads(fila["datos"]) if fila else None

    def listar(self, clase, *, contacto=None, estados=None, hasta=None, desde=None):
        sql, parametros = "SELECT datos FROM agenda_registros WHERE negocio=? AND clase=?", [self.negocio, clase]
        if contacto is not None:
            sql += " AND contacto=?"
            parametros.append(contacto)
        if estados:
            sql += " AND estado IN (" + ",".join("?" for _ in estados) + ")"
            parametros.extend(estados)
        if hasta is not None:
            sql += " AND instante<=?"
            parametros.append(hasta)
        if desde is not None:
            sql += " AND final>=?"
            parametros.append(desde)
        return [json.loads(f["datos"]) for f in self.ejecutar(sql + " ORDER BY instante", parametros).fetchall()]

    def guardar(self, clase, datos):
        if clase not in CLASES:
            raise ValueError("Clase de registro de agenda inválida.")
        self.ejecutar("""INSERT INTO agenda_registros (negocio,clase,id,contacto,estado,instante,final,datos)
          VALUES (?,?,?,?,?,?,?,?) ON CONFLICT (negocio,clase,id) DO UPDATE SET
          contacto=excluded.contacto,estado=excluded.estado,instante=excluded.instante,final=excluded.final,datos=excluded.datos""",
          (self.negocio, clase, datos["id"], datos.get("contacto", ""), datos.get("estado", ""),
           datos.get("vence", datos.get("inicio", 0)), datos.get("fin", 0), json.dumps(datos, ensure_ascii=False)))

    def borrar_externos(self):
        self.ejecutar("DELETE FROM agenda_registros WHERE negocio=? AND clase='externo'", (self.negocio,))
