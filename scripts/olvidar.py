"""Borrar lo que el bot recuerda de una conversación.

    python scripts/olvidar.py --conversacion 3
    python scripts/olvidar.py --todas

**Para qué sirve.** El bot lee su prompt más los últimos mensajes de la
charla. Si le cambiás el catálogo —o peor, la identidad entera— las
conversaciones que ya venían arrastran lo anterior: el modelo ve veinte
mensajes hablando de otra cosa y sigue ese hilo, aunque las instrucciones
nuevas digan otra cosa. Se nota sobre todo en el primer mensaje después
del cambio.

Borrando la memoria de esa conversación, el bot arranca de cero y toma la
identidad nueva desde el próximo mensaje.

**Qué NO borra.** El historial de Chatwoot queda intacto: en la bandeja se
siguen viendo todos los mensajes. Lo único que se borra es el recuerdo del
bot, que vive en Postgres.

**Sobre qué base trabaja.** Sobre la del `.env` de la raíz, que es la del
bot de la agencia. Para el bot de un cliente, apuntá `POSTGRES_DSN` a su
base antes de correrlo, o usá `--dsn`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from agente.config import Config  # noqa: E402
from agente.memoria import postgres  # noqa: E402


def main() -> int:
    parsear = argparse.ArgumentParser(
        description="Borra lo que el bot recuerda de una o todas las conversaciones."
    )
    grupo = parsear.add_mutually_exclusive_group(required=True)
    grupo.add_argument(
        "--conversacion",
        metavar="ID",
        help="El id de conversación de Chatwoot (el número que aparece en la URL).",
    )
    grupo.add_argument(
        "--todas",
        action="store_true",
        help="Todas las conversaciones de esta base. Pide confirmación.",
    )
    parsear.add_argument(
        "--dsn",
        default="",
        help="Conexión a usar. Por defecto, la del .env.",
    )
    parsear.add_argument(
        "--si",
        action="store_true",
        help="No preguntar. Para usarlo dentro de otro script.",
    )
    args = parsear.parse_args()

    dsn = args.dsn or Config.desde_entorno().postgres_dsn
    if not dsn:
        print("No hay POSTGRES_DSN. Revisá el .env o pasá --dsn.")
        return 1

    guardador = postgres(dsn)

    if args.conversacion:
        hilos = [str(args.conversacion)]
    else:
        hilos = _todos_los_hilos(guardador)
        if not hilos:
            print("No hay ninguna conversación guardada.")
            return 0
        print(f"Se van a olvidar {len(hilos)} conversaciones: {', '.join(hilos)}")
        # El historial de Chatwoot no se toca, pero esto igual es
        # irreversible: si el bot estaba a mitad de una venta, pierde el hilo.
        if not args.si and input("¿Seguimos? (escribí 'si') ").strip().lower() != "si":
            print("No se borró nada.")
            return 0

    for hilo in hilos:
        guardador.delete_thread(hilo)
        print(f"  olvidada la conversación {hilo}")

    print("\nListo. El bot arranca de cero en esas conversaciones.")
    print("El historial de Chatwoot no se tocó.")
    return 0


def _todos_los_hilos(guardador) -> list[str]:
    """Los ids de conversación que tienen algo guardado.

    Se pregunta directo a la tabla del checkpointer porque `list()` recorre
    todos los checkpoints de todas las conversaciones, y con un bot que
    lleva meses atendiendo eso es traer muchísimo para quedarse con una
    lista de ids.
    """
    with guardador.conn.cursor() as cursor:
        cursor.execute("SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id")
        # Las filas vienen como diccionarios y no como tuplas: el
        # checkpointer configura la conexión con `dict_row`. Accediendo por
        # posición se obtiene el nombre de la columna en vez del valor, y el
        # resultado parece andar hasta que mirás lo que imprimió.
        return [fila["thread_id"] for fila in cursor.fetchall()]


if __name__ == "__main__":
    raise SystemExit(main())
