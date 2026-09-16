"""Adaptador REST de Google Calendar; las credenciales vienen de config.py."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .agenda_modelo import ErrorDeAgenda


class ErrorGoogle(ErrorDeAgenda):
    def __init__(self, codigo: int, incierto=False):
        self.codigo, self.incierto = codigo, incierto
        super().__init__(f"Google Calendar no confirmó la operación (HTTP {codigo}).")


def fecha_google(instante):
    return datetime.fromtimestamp(instante, timezone.utc).isoformat()


class CalendarioGoogle:
    def __init__(self, cliente_id, secreto, refresh_token):
        self.cliente_id, self.secreto, self.refresh_token = cliente_id, secreto, refresh_token
        self._token, self._vence = "", 0
        self._candado = threading.Lock()

    def _acceso(self):
        with self._candado:
            if self._vence > time.time() + 60:
                return self._token
            datos = urllib.parse.urlencode({"client_id": self.cliente_id, "client_secret": self.secreto,
                                          "refresh_token": self.refresh_token, "grant_type": "refresh_token"}).encode()
            pedido = urllib.request.Request("https://oauth2.googleapis.com/token", data=datos)
            try:
                with urllib.request.urlopen(pedido, timeout=15) as respuesta:
                    valor = json.load(respuesta)
            except (urllib.error.URLError, TimeoutError):
                # Nunca imprimir cuerpos OAuth: pueden contener credenciales.
                raise ErrorDeAgenda("No se pudo renovar el acceso a Google Calendar; revisá la conexión.") from None
            self._token, self._vence = valor["access_token"], time.time() + valor["expires_in"]
            return self._token

    def _pedir(self, metodo, ruta, datos=None, parametros=None, etag=""):
        url = "https://www.googleapis.com/calendar/v3/" + ruta
        if parametros:
            url += "?" + urllib.parse.urlencode(parametros)
        cabeceras = {"Authorization": "Bearer " + self._acceso(), "Content-Type": "application/json"}
        if etag:
            cabeceras["If-Match"] = etag
        pedido = urllib.request.Request(url, method=metodo, headers=cabeceras,
                                       data=json.dumps(datos).encode() if datos is not None else None)
        try:
            with urllib.request.urlopen(pedido, timeout=20) as respuesta:
                crudo = respuesta.read()
                return json.loads(crudo) if crudo else {}
        except urllib.error.HTTPError as error:
            raise ErrorGoogle(error.code, incierto=error.code >= 500 or error.code == 429) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ErrorGoogle(0, incierto=True) from None

    @staticmethod
    def _ruta(calendario, evento=""):
        ruta = "calendars/" + urllib.parse.quote(calendario, safe="") + "/events"
        return ruta + ("/" + urllib.parse.quote(evento, safe="") if evento else "")

    def listar(self, calendario, desde, hasta):
        parametros = {"timeMin": fecha_google(desde), "timeMax": fecha_google(hasta),
                      "singleEvents": "true", "maxResults": 2500, "showDeleted": "false"}
        eventos = []
        while True:
            pagina = self._pedir("GET", self._ruta(calendario), parametros=parametros)
            eventos.extend(pagina.get("items", []))
            if not pagina.get("nextPageToken"):
                return eventos
            parametros["pageToken"] = pagina["nextPageToken"]

    def obtener(self, calendario, evento):
        try:
            return self._pedir("GET", self._ruta(calendario, evento))
        except ErrorGoogle as error:
            if error.codigo in (404, 410):
                return None
            raise

    def crear(self, calendario, datos):
        return self._pedir("POST", self._ruta(calendario), datos,
                           {"conferenceDataVersion": 1, "sendUpdates": "none"})

    def modificar(self, calendario, evento, datos, etag):
        return self._pedir("PATCH", self._ruta(calendario, evento), datos,
                           {"conferenceDataVersion": 1, "sendUpdates": "none"}, etag=etag)

    def cancelar(self, calendario, evento, etag):
        return self._pedir("DELETE", self._ruta(calendario, evento), etag=etag)
