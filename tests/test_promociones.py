"""Pruebas del catálogo de promociones; no llaman al proveedor ni a Chatwoot."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest
from langchain_core.messages import ToolMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agente.promociones import (  # noqa: E402
    ErrorDeCatalogo,
    crear_herramienta_promociones,
    promociones_vigentes,
)


def _preparar_catalogo(
    raiz: Path,
    *,
    desde: str = "2026-09-01",
    hasta: str = "2026-10-11",
    imagen: str = "recursos/promociones/promo.png",
) -> Path:
    ruta_imagen = raiz / "recursos/promociones/promo.png"
    ruta_imagen.parent.mkdir(parents=True)
    ruta_imagen.write_bytes(b"\x89PNG\r\n\x1a\ncontenido-de-prueba")

    datos = {
        "version": "prueba",
        "promociones": [
            {
                "codigo": "PROMO-1",
                "titulo": "Plan de prueba",
                "precio_mensual": "45",
                "moneda": "USD",
                "limite_conversaciones": 1000,
                "incluye": ["panel CRM", "app móvil"],
                "vigente_desde": desde,
                "vigente_hasta": hasta,
                "condicion_tarifa": "Conserva la tarifa",
                "llamada_a_la_accion": "coordinar una demo",
                "imagen": imagen,
                "activa": True,
            }
        ],
    }
    catalogo = raiz / "catalogos/promociones.json"
    catalogo.parent.mkdir(parents=True)
    catalogo.write_text(json.dumps(datos), encoding="utf-8")
    return catalogo


@pytest.mark.parametrize("hoy", [date(2026, 9, 1), date(2026, 10, 11)])
def test_la_vigencia_incluye_el_primer_y_ultimo_dia(tmp_path, hoy):
    catalogo = _preparar_catalogo(tmp_path)

    promociones = promociones_vigentes(catalogo, hoy=hoy, raiz=tmp_path)

    assert [promocion.codigo for promocion in promociones] == ["PROMO-1"]
    assert promociones[0].imagen.mime == "image/png"


@pytest.mark.parametrize("hoy", [date(2026, 8, 31), date(2026, 10, 12)])
def test_no_reutiliza_una_promocion_fuera_de_vigencia(tmp_path, hoy):
    catalogo = _preparar_catalogo(tmp_path)
    assert promociones_vigentes(catalogo, hoy=hoy, raiz=tmp_path) == []


def test_la_herramienta_devuelve_texto_y_adjunto_estructurado(tmp_path):
    catalogo = _preparar_catalogo(tmp_path)
    herramienta = crear_herramienta_promociones(
        catalogo,
        raiz=tmp_path,
        hoy_para_pruebas=date(2026, 9, 14),
    )

    resultado = herramienta.invoke(
        {
            "name": "promociones_disponibles",
            "args": {},
            "id": "consulta-1",
            "type": "tool_call",
        }
    )

    assert isinstance(resultado, ToolMessage)
    assert "US$ 45 al mes" in resultado.content
    assert "app móvil" in resultado.content
    assert resultado.artifact["adjuntos"] == [
        {
            "tipo": "archivo_aprobado",
            "ruta": str((tmp_path / "recursos/promociones/promo.png").resolve()),
            "nombre": "promo.png",
            "mime": "image/png",
            "codigo": "PROMO-1",
        }
    ]


def test_una_promocion_vencida_no_produce_adjunto(tmp_path):
    catalogo = _preparar_catalogo(tmp_path, hasta="2026-09-13")
    herramienta = crear_herramienta_promociones(
        catalogo,
        raiz=tmp_path,
        hoy_para_pruebas=date(2026, 9, 14),
    )

    resultado = herramienta.invoke(
        {
            "name": "promociones_disponibles",
            "args": {},
            "id": "consulta-1",
            "type": "tool_call",
        }
    )

    assert "No hay promociones vigentes" in resultado.content
    assert resultado.artifact == {"adjuntos": []}


def test_rechaza_una_imagen_fuera_de_recursos(tmp_path):
    catalogo = _preparar_catalogo(tmp_path, imagen="../secreto.png")

    with pytest.raises(ErrorDeCatalogo, match="dentro de recursos"):
        promociones_vigentes(catalogo, hoy=date(2026, 9, 14), raiz=tmp_path)


def test_rechaza_un_archivo_que_no_es_una_imagen_real(tmp_path):
    catalogo = _preparar_catalogo(tmp_path)
    (tmp_path / "recursos/promociones/promo.png").write_text(
        "esto no es PNG", encoding="utf-8"
    )

    with pytest.raises(ErrorDeCatalogo, match="no coincide"):
        promociones_vigentes(catalogo, hoy=date(2026, 9, 14), raiz=tmp_path)


def test_el_catalogo_real_no_incluye_instalacion_ni_contrato():
    raiz = Path(__file__).resolve().parents[1]
    catalogo = raiz / "catalogos/promociones_smarth_house.json"

    promociones = promociones_vigentes(
        catalogo,
        hoy=date(2026, 9, 14),
        raiz=raiz,
    )
    texto = " ".join(
        [
            promociones[0].titulo,
            promociones[0].condicion_tarifa,
            promociones[0].llamada_a_la_accion,
            *promociones[0].incluye,
        ]
    ).lower()

    assert len(promociones) == 1
    assert "instalaci" not in texto
    assert "contrato" not in texto
    assert promociones[0].imagen.ruta.is_file()
