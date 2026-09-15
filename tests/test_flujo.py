import json
from decimal import Decimal
from pathlib import Path

import pytest

from bringmef29 import flujo
from bringmef29.modelos import Periodo
from bringmef29.sii.errores import ErrorAutenticacion, RespuestaInesperada

from .conftest import requiere_chromium


def test_guardar_y_releer_declaracion(config, declaracion_con_pago):
    ruta = flujo.guardar_declaracion(config, declaracion_con_pago)
    guardado = json.loads(Path(ruta).read_text(encoding="utf-8"))

    assert guardado["folio"] == "7654321098"
    assert guardado["monto_a_pagar"] == "1840000"
    assert Path(ruta).parent.name == "202508"

    releida = flujo.cargar_declaracion(ruta)
    assert releida.rut == declaracion_con_pago.rut
    assert releida.periodo == Periodo(2025, 8)
    assert releida.monto_a_pagar == Decimal(1840000)
    assert len(releida.lineas) == len(declaracion_con_pago.lineas)


def test_modo_desconocido(config, monkeypatch):
    monkeypatch.setenv("BRINGMEF29_CLAVE_ACME", "x")
    with pytest.raises(ValueError, match="Modo de obtención desconocido"):
        flujo.obtener(config, config.cliente("acme"), Periodo(2025, 8), modo="telepatia")


def test_auto_cae_al_navegador_si_la_api_falla(config, monkeypatch, declaracion_con_pago):
    """Con fuente 'presentada' la vía API es válida; si falla, debe usarse el navegador."""
    monkeypatch.setenv("BRINGMEF29_CLAVE_ACME", "x")
    llamadas = []

    def api_falla(*_a, **_k):
        llamadas.append("api")
        raise RespuestaInesperada("el SII cambió")

    def navegador_responde(*_a, **_k):
        llamadas.append("navegador")
        return declaracion_con_pago, "captura.png", "sii.pdf"

    monkeypatch.setattr(flujo, "_obtener_api", api_falla)
    monkeypatch.setattr(flujo, "obtener_con_navegador", navegador_responde)

    resultado = flujo.obtener(
        config, config.cliente("acme"), Periodo(2025, 8), fuente="presentada", modo="auto"
    )

    assert llamadas == ["api", "navegador"]
    assert resultado.declaracion is declaracion_con_pago
    assert resultado.captura == "captura.png"
    assert resultado.pdf_oficial == "sii.pdf"


def test_auto_no_reintenta_si_la_clave_es_incorrecta(config, monkeypatch):
    monkeypatch.setenv("BRINGMEF29_CLAVE_ACME", "x")
    llamadas = []

    def api_rechaza(*_a, **_k):
        llamadas.append("api")
        raise ErrorAutenticacion("clave incorrecta")

    def navegador(*_a, **_k):  # pragma: no cover - no debería llamarse
        llamadas.append("navegador")
        raise AssertionError("no se debe reintentar con una clave inválida")

    monkeypatch.setattr(flujo, "_obtener_api", api_rechaza)
    monkeypatch.setattr(flujo, "obtener_con_navegador", navegador)

    with pytest.raises(ErrorAutenticacion):
        flujo.obtener(
            config, config.cliente("acme"), Periodo(2025, 8), fuente="presentada", modo="auto"
        )
    assert llamadas == ["api"]


@requiere_chromium
def test_procesar_desde_archivo_sin_tocar_el_sii(config, declaracion_con_pago, monkeypatch):
    ruta = flujo.guardar_declaracion(config, declaracion_con_pago)

    def no_llamar(*_a, **_k):  # pragma: no cover - el test falla si se llama
        raise AssertionError("no debe consultarse el SII cuando se usa --desde-archivo")

    monkeypatch.setattr(flujo, "obtener", no_llamar)

    aviso = flujo.procesar(
        config, "acme", Periodo(2025, 8), desde_archivo=ruta, simular_envio=True
    )

    assert Path(aviso.pdf).exists()
    assert Path(aviso.imagen).exists()
    assert not aviso.enviado_correo and not aviso.enviado_whatsapp
    assert aviso.enlace_whatsapp.startswith("https://wa.me/")
    assert aviso.incidencias == []


@requiere_chromium
def test_las_fallas_de_envio_quedan_como_incidencias(config, declaracion_con_pago, monkeypatch):
    ruta = flujo.guardar_declaracion(config, declaracion_con_pago)
    cliente = config.cliente("acme")
    cliente.correo = []          # sin correo → incidencia, no excepción
    cliente.whatsapp = ""        # sin whatsapp → incidencia

    aviso = flujo.procesar(config, "acme", Periodo(2025, 8), desde_archivo=ruta)

    assert len(aviso.incidencias) == 2
    assert any("Correo" in i for i in aviso.incidencias)
    assert any("WhatsApp" in i for i in aviso.incidencias)
    assert Path(aviso.pdf).exists()   # los documentos se generan igual


@requiere_chromium
def test_solo_documentos_no_envia(config, declaracion_con_pago, monkeypatch):
    ruta = flujo.guardar_declaracion(config, declaracion_con_pago)
    monkeypatch.setattr(
        flujo, "EnviadorCorreo", lambda *_a: pytest.fail("no debe enviar correo")
    )
    aviso = flujo.procesar(
        config, "acme", Periodo(2025, 8), desde_archivo=ruta, solo_documentos=True
    )
    assert Path(aviso.pdf).exists()
    assert not aviso.enviado_correo
