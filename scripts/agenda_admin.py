"""Comprobación y administración de agenda; no envía mensajes desde esta CLI."""

import argparse
from datetime import datetime, time, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agente.agenda import crear_agenda
from agente.agenda_modelo import ErrorDeAgenda
from agente.canales.chatwoot import Chatwoot
from agente.config import config_agenda_local, ErrorDeConfiguracion


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--negocio", default="", help="Lee .env.agenda.<negocio>.local en vez de "
                        ".env.agenda.local. Va antes del comando.")
    comandos = parser.add_subparsers(dest="accion", required=True)
    comandos.add_parser("comprobar", help="Verifica lectura de calendarios, sin crear citas ni enviar mensajes.")
    comandos.add_parser("estado", help="Muestra conteos operativos, sin nombres de contactos.")
    citas = comandos.add_parser("citas", help="Lista las citas de recepción con su estado de asistencia.")
    citas.add_argument("--fecha", required=True, help="Día local AAAA-MM-DD.")
    comandos.add_parser("sincronizar", help="Actualiza cambios manuales y programa avisos; no los envía.")
    vincular = comandos.add_parser("vincular", help="Asocia una cita manual a un contacto de Chatwoot.")
    for campo in ("conversacion", "servicio", "recurso", "evento", "nombre"):
        vincular.add_argument("--" + campo, required=True)
    args = parser.parse_args()
    try:
        config = config_agenda_local(args.negocio)
        agenda = crear_agenda(config)
        if args.accion == "comprobar":
            for ajustes in agenda.reglas.recursos.values():
                agenda.google.listar(ajustes["calendario"], agenda.reloj(), agenda.reloj() + 86400)
            print("Lectura de calendarios verificada. Esto no prueba todavía escrituras ni entrega de WhatsApp.")
        elif args.accion == "citas":
            try:
                dia = datetime.strptime(args.fecha, "%Y-%m-%d").date()
            except ValueError:
                raise ErrorDeAgenda("Indicá el día como AAAA-MM-DD.") from None
            desde = datetime.combine(dia, time(), agenda.reglas.tz)
            hasta = (desde + timedelta(days=1)).timestamp()
            with agenda.repo.transaccion() as db:
                for cita in db.listar("cita", desde=desde.timestamp()):
                    if cita["inicio"] >= hasta:
                        continue
                    estado = "agendada" if cita["estado"] == "confirmada" else cita["estado"]
                    print(cita["id"], cita["nombre"], cita["servicio"], cita["recurso"],
                          agenda.reglas.describir(cita["inicio"], cita["fin"]),
                          "reserva=" + estado, "asistencia=" + cita.get("asistencia", "pendiente"), sep=" | ")
        elif args.accion == "sincronizar":
            agenda.sincronizar()
            print("Sincronización terminada; avisos registrados para el trabajador del webhook.")
        elif args.accion == "vincular":
            if not args.conversacion.isdigit():
                raise ErrorDeAgenda("La conversación debe tener un ID numérico.")
            canal = Chatwoot(config.chatwoot_url, config.chatwoot_token, config.chatwoot_cuenta_id,
                             bandeja_id=config.chatwoot_bandeja_id)
            conversacion = canal._api("GET", f"conversations/{args.conversacion}")
            if str(conversacion.get("inbox_id")) != config.chatwoot_bandeja_id:
                raise ErrorDeAgenda("La conversación no pertenece a la bandeja configurada.")
            contacto = (conversacion.get("meta") or {}).get("sender") or {}
            agenda.registrar_contacto(args.conversacion, contacto.get("id"), config.chatwoot_cuenta_id, config.chatwoot_bandeja_id)
            referencia = agenda.vincular_manual(args.conversacion, args.servicio, args.recurso, args.evento, args.nombre)
            print("Cita vinculada:", referencia)
        else:
            with agenda.repo.transaccion() as db:
                print("Citas pendientes:", len(db.listar("cita", estados=("pendiente",))))
                agendadas = db.listar("cita", estados=("confirmada",), desde=agenda.reloj())
                confirmadas = sum(c.get("asistencia") == "confirmada" for c in agendadas)
                print("Citas agendadas vigentes:", len(agendadas))
                print("Asistencias confirmadas:", confirmadas)
                print("Asistencias sin confirmar:", len(agendadas) - confirmadas)
                print("Avisos pendientes:", len(db.listar("envio", estados=("pendiente", "enviando"))))
                print("Avisos bloqueados o inciertos:", len(db.listar("envio", estados=("bloqueado", "incierto"))))
                control = db.obtener("control", "sincronizacion") or {}
                print("Conflictos manuales:", len(control.get("conflictos", [])))
    except (ErrorDeAgenda, ErrorDeConfiguracion) as error:
        print(str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
