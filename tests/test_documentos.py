from decimal import Decimal
from pathlib import Path

from bringmef29.documentos import ConstructorDocumentos
from bringmef29.documentos.constructor import _a_data_uri
from bringmef29.documentos.formato import fecha_corta, fecha_larga, pesos

from .conftest import requiere_chromium


# --------------------------------------------------------------------------- #
# Formato
# --------------------------------------------------------------------------- #


def test_formato_de_pesos():
    assert pesos(1840000) == "$1.840.000"
    assert pesos(Decimal("0")) == "$0"
    assert pesos(-5000) == "-$5.000"
    assert pesos(None) == "—"
    assert pesos(1234.6) == "$1.235"          # los pesos van sin decimales
    assert pesos(980000, simbolo=False) == "980.000"


def test_formato_de_fechas():
    from datetime import date

    assert fecha_larga(date(2025, 9, 12)) == "12 de septiembre de 2025"
    assert fecha_corta(date(2025, 9, 12)) == "12-09-2025"
    assert fecha_larga(None) == "—"


# --------------------------------------------------------------------------- #
# Contexto de plantilla
# --------------------------------------------------------------------------- #


def test_resumen_solo_trae_codigos_con_valor(config, declaracion_con_pago):
    constructor = ConstructorDocumentos(config)
    resumen = constructor._resumen(declaracion_con_pago)
    codigos = [fila["codigo"] for fila in resumen]

    assert codigos == ["563", "538", "537", "062", "048", "547"]
    assert resumen[0]["glosa"] == "Base imponible (ventas netas del período)"
    assert resumen[0]["monto"] == "$18.500.000"


def test_resumen_respeta_la_glosa_que_venga_del_sii(config, declaracion_con_pago):
    declaracion_con_pago.lineas[1].glosa = "TOTAL DEBITOS DEL PERIODO"
    resumen = ConstructorDocumentos(config)._resumen(declaracion_con_pago)
    assert any(f["glosa"] == "TOTAL DEBITOS DEL PERIODO" for f in resumen)


def test_contexto_del_aviso(config, declaracion_con_pago):
    contexto = ConstructorDocumentos(config)._contexto(
        declaracion_con_pago, config.cliente("acme")
    )
    assert contexto["monto_a_pagar"] == "$1.840.000"
    assert contexto["razon_social"] == "Comercial Acme SpA"
    assert contexto["rut"] == "76.086.428-5"
    assert contexto["hay_que_pagar"]
    assert contexto["vencimiento"] == "12 de septiembre de 2025"
    assert "--acento" in contexto["css"]


def test_contexto_sin_pago_muestra_el_remanente(config, declaracion_sin_pago):
    contexto = ConstructorDocumentos(config)._contexto(
        declaracion_sin_pago, config.cliente("acme")
    )
    assert not contexto["hay_que_pagar"]
    assert contexto["remanente"] == "$400.000"


def test_data_uri_de_imagen(tmp_path):
    imagen = tmp_path / "logo.png"
    imagen.write_bytes(b"\x89PNG\r\n\x1a\n falso")
    uri = _a_data_uri(imagen)
    assert uri.startswith("data:image/png;base64,")
    assert _a_data_uri("") == ""
    assert _a_data_uri(tmp_path / "no-existe.png") == ""


# --------------------------------------------------------------------------- #
# Render (necesita Chromium)
# --------------------------------------------------------------------------- #


@requiere_chromium
def test_genera_pdf_e_imagen(config, declaracion_con_pago):
    documentos = ConstructorDocumentos(config).construir(
        declaracion_con_pago, config.cliente("acme"), guardar_html=True
    )

    pdf, imagen, html = Path(documentos.pdf), Path(documentos.imagen), Path(documentos.html)
    assert pdf.exists() and pdf.stat().st_size > 5000
    assert pdf.read_bytes().startswith(b"%PDF")
    assert imagen.exists() and imagen.read_bytes().startswith(b"\x89PNG")
    assert pdf.name == "F29-202508-760864285.pdf"

    contenido = html.read_text(encoding="utf-8")
    # El CSS no debe llegar escapado: rompería selectores y tipografías.
    assert ".ficha > div" in contenido
    assert "&gt;" not in contenido.split("</style>")[0]
    assert "$1.840.000" in contenido
    assert "00-123-45678-90" in contenido


@requiere_chromium
def test_el_aviso_sin_pago_no_muestra_datos_bancarios(config, declaracion_sin_pago):
    documentos = ConstructorDocumentos(config).construir(
        declaracion_sin_pago, config.cliente("acme"), guardar_html=True
    )
    contenido = Path(documentos.html).read_text(encoding="utf-8")
    assert "Sin pago asociado" in contenido
    assert "00-123-45678-90" not in contenido


@requiere_chromium
def test_incrusta_la_captura_del_sii(config, declaracion_con_pago, tmp_path):
    captura = tmp_path / "comprobante.png"
    captura.write_bytes(b"\x89PNG\r\n\x1a\n falso")
    documentos = ConstructorDocumentos(config).construir(
        declaracion_con_pago, config.cliente("acme"), captura_sii=str(captura), guardar_html=True
    )
    contenido = Path(documentos.html).read_text(encoding="utf-8")
    assert "Comprobante en el SII" in contenido
    assert "data:image/png;base64," in contenido
