"""Reglas de agenda compartidas por agencias, consultorios y otros negocios."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


class ErrorDeAgenda(Exception):
    """Una condición de agenda que se puede explicar sin exponer secretos."""


@dataclass(frozen=True)
class ReglasAgenda:
    negocio: str
    nombre: str
    zona: str
    dias: tuple[int, ...]
    apertura: str
    cierre: str
    paso_minutos: int
    anticipacion_minutos: int
    horizonte_dias: int
    recordatorios_minutos: tuple[int, ...]
    recursos: dict
    servicios: dict
    cierres: tuple[str, ...] = ()

    @classmethod
    def leer(cls, ruta: Path):
        return cls.desde_dict(json.loads(ruta.read_text(encoding="utf-8")))

    @classmethod
    def desde_dict(cls, datos: dict):
        try:
            reglas = cls(**{**datos, "dias": tuple(datos["dias"]),
                            "recordatorios_minutos": tuple(datos["recordatorios_minutos"]),
                            "cierres": tuple(datos.get("cierres", []))})
            ZoneInfo(reglas.zona)
            if not re.fullmatch(r"[a-z0-9-]{2,50}", reglas.negocio):
                raise ValueError()
            if not reglas.dias or any(type(d) is not int or d not in range(7) for d in reglas.dias):
                raise ValueError()
            if time.fromisoformat(reglas.apertura) >= time.fromisoformat(reglas.cierre):
                raise ValueError()
            for valor, minimo, maximo in ((reglas.paso_minutos, 5, 120),
                                         (reglas.anticipacion_minutos, 0, 10080),
                                         (reglas.horizonte_dias, 1, 180)):
                if type(valor) is not int or not minimo <= valor <= maximo:
                    raise ValueError()
            if any(type(m) is not int or not 1 <= m <= 10080 for m in reglas.recordatorios_minutos):
                raise ValueError()
            calendarios = []
            for codigo, recurso in reglas.recursos.items():
                if not re.fullmatch(r"[a-z0-9_-]{1,40}", codigo):
                    raise ValueError()
                if type(recurso["capacidad"]) is not int or not 1 <= recurso["capacidad"] <= 100:
                    raise ValueError()
                if not recurso["nombre"] or not recurso["calendario"]:
                    raise ValueError()
                calendarios.append(recurso["calendario"])
            if not calendarios or len(set(calendarios)) != len(calendarios):
                raise ValueError()
            for servicio in reglas.servicios.values():
                if type(servicio["minutos"]) is not int or not 5 <= servicio["minutos"] <= 480:
                    raise ValueError()
                if not servicio["recursos"] or not set(servicio["recursos"]) <= set(reglas.recursos):
                    raise ValueError()
            if not reglas.servicios:
                raise ValueError()
            for dia in reglas.cierres:
                datetime.strptime(dia, "%Y-%m-%d")
            return reglas
        except (ValueError, TypeError, KeyError) as error:
            raise ErrorDeAgenda("Revisá el archivo de reglas de la agenda.") from error

    @property
    def tz(self):
        return ZoneInfo(self.zona)

    def intervalo(self, servicio: str, recurso: str, fecha: str, ahora: float):
        if servicio not in self.servicios or recurso not in self.servicios[servicio]["recursos"]:
            raise ErrorDeAgenda("Ese servicio o profesional no está habilitado.")
        try:
            inicio = datetime.fromisoformat(fecha)
        except ValueError:
            raise ErrorDeAgenda("Indicá fecha y hora completas, por ejemplo 2026-09-21T09:00.") from None
        if inicio.tzinfo is None:
            inicio = inicio.replace(tzinfo=self.tz)
        inicio = inicio.astimezone(self.tz)
        # Detecta horas inexistentes durante cambios estacionales de otros países.
        if datetime.fromtimestamp(inicio.timestamp(), self.tz).replace(tzinfo=None) != inicio.replace(tzinfo=None):
            raise ErrorDeAgenda("Esa hora no existe en la zona del negocio.")
        fin = inicio + timedelta(minutes=self.servicios[servicio]["minutos"])
        apertura = datetime.combine(inicio.date(), time.fromisoformat(self.apertura), self.tz)
        cierre = datetime.combine(inicio.date(), time.fromisoformat(self.cierre), self.tz)
        if (inicio.weekday() not in self.dias or inicio.date().isoformat() in self.cierres
                or inicio < apertura or fin > cierre or inicio.second or inicio.microsecond
                or int((inicio - apertura).total_seconds()) % (self.paso_minutos * 60)):
            raise ErrorDeAgenda("Ese horario queda fuera de los turnos de atención.")
        if inicio.timestamp() < ahora + self.anticipacion_minutos * 60:
            raise ErrorDeAgenda("Ese horario ya pasó o no cumple la anticipación mínima.")
        if inicio.timestamp() > ahora + self.horizonte_dias * 86400:
            raise ErrorDeAgenda("Todavía no se abrió la agenda para esa fecha.")
        return inicio.timestamp(), fin.timestamp()

    def describir(self, inicio: float, fin: float):
        return (datetime.fromtimestamp(inicio, self.tz).strftime("%d/%m/%Y %H:%M")
                + " a " + datetime.fromtimestamp(fin, self.tz).strftime("%H:%M")
                + f" ({self.zona})")


def ocupacion_maxima(intervalos, inicio: float, fin: float) -> int:
    """Cuenta simultaneidad real; dos intervalos contiguos no se superponen."""
    puntos = []
    for desde, hasta, cupos in intervalos:
        if desde < fin and hasta > inicio:
            puntos.extend(((max(desde, inicio), cupos), (min(hasta, fin), -cupos)))
    actual = maxima = 0
    for _, cambio in sorted(puntos):
        actual += cambio
        maxima = max(maxima, actual)
    return maxima
