"""Contraseñas, tokens y límite de intentos, solo con la biblioteca estándar.

`hashlib.scrypt` resuelve lo mismo que bcrypt o argon2 sin sumar una
dependencia: es lento y usa memoria a propósito, que es lo que encarece
probar contraseñas robadas de la base.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import threading
import time
from collections import deque
from functools import cache

# 16 MB y unos 50 ms por intento en una computadora común. hashlib no deja
# pasar de 32 MB sin tocar maxmem, así que no conviene subir N sin medir.
N, R, P = 2**14, 8, 1
LARGO_DERIVADO = 32
MINIMO_CLAVE = 10
MAXIMO_CLAVE = 128


class ClaveDebil(ValueError):
    """La contraseña nueva no cumple el mínimo."""


def validar_clave_nueva(clave: str) -> str:
    if not isinstance(clave, str) or len(clave) < MINIMO_CLAVE:
        raise ClaveDebil(f"La contraseña necesita al menos {MINIMO_CLAVE} caracteres.")
    if len(clave) > MAXIMO_CLAVE:
        raise ClaveDebil(f"La contraseña puede tener hasta {MAXIMO_CLAVE} caracteres.")
    return clave


def hashear_clave(clave: str) -> str:
    sal = secrets.token_bytes(16)
    derivada = hashlib.scrypt(
        clave.encode("utf-8"), salt=sal, n=N, r=R, p=P, dklen=LARGO_DERIVADO
    )
    return f"scrypt${N}${R}${P}${_b64(sal)}${_b64(derivada)}"


def verificar_clave(clave: str, guardada: str) -> bool:
    # Una contraseña gigante no es de nadie y le haría pagar a scrypt un
    # trabajo que el atacante manda gratis.
    if not isinstance(clave, str) or len(clave) > MAXIMO_CLAVE:
        return False
    try:
        esquema, n, r, p, sal, esperada = guardada.split("$")
        if esquema != "scrypt":
            return False
        sal_bytes, esperada_bytes = _de_b64(sal), _de_b64(esperada)
        calculada = hashlib.scrypt(
            clave.encode("utf-8"),
            salt=sal_bytes,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(esperada_bytes),
        )
    except (ValueError, binascii.Error):
        return False
    return hmac.compare_digest(calculada, esperada_bytes)


@cache
def clave_de_relleno() -> str:
    """Un hash que no es de nadie, para gastar el mismo tiempo sin usuario.

    Si con un correo inexistente respondiéramos al instante y con uno real
    tardáramos lo que tarda scrypt, el reloj diría qué correos tienen cuenta.
    """
    return hashear_clave(secrets.token_urlsafe(24))


def nuevo_token() -> str:
    return secrets.token_urlsafe(32)


def huella(token: str) -> str:
    """Lo que se guarda de una sesión o una clave de bot: nunca el token.

    Con la base filtrada no alcanza para entrar. No hace falta scrypt: el
    token tiene 256 bits al azar y no se puede adivinar probando.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class LimiteDeIntentos:
    """Frena a quien prueba contraseñas: pocos fallos por ventana y por clave.

    Vive en memoria porque el portal corre en un solo proceso. Un reinicio
    lo vacía; alcanza para cortar un ataque de fuerza bruta, que necesita
    miles de intentos.
    """

    MAXIMO_CLAVES = 10_000

    def __init__(self, maximo: int = 5, ventana_segundos: float = 900, reloj=time.monotonic):
        self.maximo = maximo
        self.ventana = ventana_segundos
        self.reloj = reloj
        self._fallos: dict[str, deque[float]] = {}
        self._candado = threading.Lock()

    def bloqueado(self, *claves: str) -> bool:
        with self._candado:
            ahora = self.reloj()
            return any(len(self._vigentes(clave, ahora)) >= self.maximo for clave in claves)

    def registrar_fallo(self, *claves: str) -> None:
        with self._candado:
            ahora = self.reloj()
            if len(self._fallos) > self.MAXIMO_CLAVES:
                # Alguien probando correos al azar no puede hacer crecer esto
                # sin límite: se descartan las claves que ya vencieron.
                for clave in list(self._fallos):
                    self._vigentes(clave, ahora)
            for clave in claves:
                self._fallos.setdefault(clave, deque()).append(ahora)

    def olvidar(self, *claves: str) -> None:
        with self._candado:
            for clave in claves:
                self._fallos.pop(clave, None)

    def _vigentes(self, clave: str, ahora: float) -> deque[float]:
        fallos = self._fallos.get(clave)
        if fallos is None:
            return deque()
        while fallos and ahora - fallos[0] > self.ventana:
            fallos.popleft()
        if not fallos:
            del self._fallos[clave]
        return fallos


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).decode("ascii").rstrip("=")


def _de_b64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))
