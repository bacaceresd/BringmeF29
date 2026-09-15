import os
from decimal import Decimal

import pytest

from bringmef29 import config as modulo_config
from bringmef29.modelos import DeclaracionF29, LineaCodigo, Periodo
from bringmef29.rut import Rut
from bringmef29.seguridad import generar_clave_maestra

CONFIG_BASE = {
    "estudio": {
        "nombre": "Estudio de Prueba",
        "correo": "estudio@ejemplo.cl",
        "telefono": "+56 9 0000 0000",
    },
    "pago": {
        "modo": "ambos",
        "titular": "Estudio de Prueba SpA",
        "rut_titular": "77.111.222-6",
        "banco": "Banco de Chile",
        "tipo_cuenta": "Cuenta Corriente",
        "numero_cuenta": "00-123-45678-90",
        "correo_confirmacion": "pagos@ejemplo.cl",
    },
    "correo": {
        "servidor": "smtp.ejemplo.cl",
        "puerto": 587,
        "remitente": "estudio@ejemplo.cl",
        "nombre_remitente": "Estudio de Prueba",
    },
    "whatsapp": {"proveedor": "enlace"},
    "clientes": [
        {
            "alias": "acme",
            "rut": "76.086.428-5",
            "razon_social": "Comercial Acme SpA",
            "nombre_contacto": "Ana",
            "correo": ["ana@acme.cl"],
            "whatsapp": "+56 9 1111 2222",
        }
    ],
}


@pytest.fixture
def clave_maestra(monkeypatch):
    clave = generar_clave_maestra()
    monkeypatch.setenv("BRINGMEF29_MASTER_KEY", clave)
    return clave


@pytest.fixture
def config(tmp_path):
    cfg = modulo_config.desde_dict(CONFIG_BASE)
    cfg.directorio_salida = tmp_path / "salida"
    cfg.ruta_almacen_claves = tmp_path / "secretos" / "claves.json"
    return cfg


@pytest.fixture
def declaracion_con_pago():
    return DeclaracionF29(
        rut=Rut.parsear("76.086.428-5"),
        periodo=Periodo(2025, 8),
        folio="7654321098",
        estado="Vigente",
        razon_social="Comercial Acme SpA",
        origen="api",
        lineas=[
            LineaCodigo("563", Decimal("18500000")),
            LineaCodigo("538", Decimal("3515000")),
            LineaCodigo("537", Decimal("2100000")),
            LineaCodigo("062", Decimal("185000")),
            LineaCodigo("048", Decimal("240000")),
            LineaCodigo("547", Decimal("1840000")),
            LineaCodigo("091", Decimal("1840000")),
        ],
    )


@pytest.fixture
def declaracion_sin_pago():
    return DeclaracionF29(
        rut=Rut.parsear("76.086.428-5"),
        periodo=Periodo(2025, 8),
        folio="7654321099",
        razon_social="Comercial Acme SpA",
        lineas=[
            LineaCodigo("538", Decimal("1000000")),
            LineaCodigo("537", Decimal("1400000")),
            LineaCodigo("077", Decimal("400000")),
            LineaCodigo("091", Decimal("0")),
        ],
    )


def hay_chromium() -> bool:
    from bringmef29.sii.f29_navegador import ruta_chromium

    if ruta_chromium():
        return True
    return bool(os.environ.get("PLAYWRIGHT_BROWSERS_PATH"))


requiere_chromium = pytest.mark.skipif(
    not hay_chromium(), reason="requiere Chromium para renderizar PDF/PNG"
)
