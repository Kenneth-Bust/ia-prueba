"""Partir la respuesta en varios mensajes.

En un chat de web una respuesta larga se lee bien de un tirón. En WhatsApp
o Telegram no: un bloque de 800 caracteres se ve como un ladrillo y no
parece escrito por una persona.

Esta función parte el texto en mensajes cortos, respetando lo que el modelo
quiso separar. No se usa en la plataforma de pruebas — está acá lista para
cuando el agente atienda mensajería.

    partir_respuesta("Hola.\\n\\n¿Qué necesitás?")  →  ["Hola.", "¿Qué necesitás?"]

El criterio, en orden:

    1. Si el texto trae renglones en blanco, se respeta esa separación.
    2. Si no y entra en un solo mensaje, va entero.
    3. Si no, se parte por oraciones sin cortar ninguna al medio.
"""

from __future__ import annotations

import re

# Un mensaje suelto de este largo o menos se manda entero.
LARGO_DE_UN_MENSAJE = 320

# Nunca mandamos más de esto: cinco globos seguidos ya es spam.
MAXIMO_DE_MENSAJES = 5

_FIN_DE_ORACION = re.compile(r"(?<=[.!?…])\s+")


# -- El ritmo de escritura ----------------------------------------------------
#
# Partir la respuesta en varios globos no alcanza para que parezca escrita por
# una persona: si los dos salen en la misma décima de segundo, el efecto es al
# revés y se nota más que si fuera un solo mensaje largo. Nadie escribe dos
# párrafos a la vez.
#
# Así que entre mensaje y mensaje se espera lo que tardaría alguien en
# tipearlo, con el "escribiendo..." encendido mientras tanto.

# Cuántos caracteres por segundo "escribe" el agente. 28 es rápido pero
# creíble: alguien que tipea bien en el teléfono.
CARACTERES_POR_SEGUNDO = 28

# La pausa nunca baja de esto (un mensaje de dos palabras igual toma un
# instante) ni sube de esto otro (nadie espera 8 segundos por la segunda
# mitad de una respuesta).
PAUSA_MINIMA = 1.2
PAUSA_MAXIMA = 4.0


def pausa_de_tipeo(texto: str) -> float:
    """Cuánto esperar antes de mandar este mensaje, en segundos.

    Proporcional al largo: un "dale, te espero" sale casi enseguida y un
    párrafo de tres renglones se hace esperar. Es la diferencia entre que
    parezca una persona y que parezca un formulario.
    """
    segundos = len(texto or "") / CARACTERES_POR_SEGUNDO
    return max(PAUSA_MINIMA, min(segundos, PAUSA_MAXIMA))


def partir_respuesta(
    texto: str,
    largo_de_un_mensaje: int = LARGO_DE_UN_MENSAJE,
    maximo: int = MAXIMO_DE_MENSAJES,
) -> list[str]:
    """Devuelve la lista de mensajes a enviar, en orden."""
    texto = _limpiar(texto)
    if not texto:
        return []

    # 1. El modelo ya separó con renglones en blanco: le hacemos caso.
    bloques = [b.strip() for b in re.split(r"\n\s*\n", texto) if b.strip()]
    if len(bloques) > 1:
        return _juntar_hasta(bloques, maximo)

    # 2. Entra en un solo mensaje.
    if len(texto) <= largo_de_un_mensaje:
        return [texto]

    # 3. Partir por oraciones, sin cortar ninguna al medio.
    return _juntar_hasta(_por_oraciones(texto, largo_de_un_mensaje), maximo)


def _limpiar(texto: str) -> str:
    """Normaliza los saltos de línea que mandan los modelos."""
    return (
        (texto or "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .strip()
    )


def _por_oraciones(texto: str, largo: int) -> list[str]:
    """Agrupa oraciones hasta llenar cada mensaje."""
    mensajes: list[str] = []
    actual = ""

    for oracion in _FIN_DE_ORACION.split(texto):
        oracion = oracion.strip()
        if not oracion:
            continue

        if not actual:
            actual = oracion
        elif len(actual) + 1 + len(oracion) <= largo:
            actual += " " + oracion
        else:
            mensajes.append(actual)
            actual = oracion

    if actual:
        mensajes.append(actual)

    return mensajes


def _juntar_hasta(mensajes: list[str], maximo: int) -> list[str]:
    """Si quedaron más mensajes que el máximo, pega el sobrante al último."""
    if len(mensajes) <= maximo:
        return mensajes

    return mensajes[: maximo - 1] + ["\n\n".join(mensajes[maximo - 1 :])]
