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


def test_contexto_del_aviso(config, declaracion_con_pago):
    contexto = ConstructorDocumentos(config)._contexto(
        declaracion_con_pago, config.cliente("acme")
    )
    assert contexto["razon_social"] == "Comercial Acme SpA"
    assert contexto["rut"] == "76.086.428-5"
    assert contexto["resumen"].hay_que_pagar
    assert contexto["resumen"].total_monto == Decimal(1840000)
    assert "Lunes 22 de septiembre, 2025" in contexto["resumen"].vencimiento_texto
    assert "23:59" in contexto["resumen"].vencimiento_texto


def test_el_contexto_trae_el_resumen_agrupado(config, declaracion_con_pago):
    resumen = ConstructorDocumentos(config)._contexto(
        declaracion_con_pago, config.cliente("acme")
    )["resumen"]
    titulos = [g.titulo for g in resumen.grupos]
    assert "IVA" in titulos
    assert "Retenciones" in titulos


def test_contexto_sin_pago(config, declaracion_sin_pago):
    resumen = ConstructorDocumentos(config)._contexto(
        declaracion_sin_pago, config.cliente("acme")
    )["resumen"]
    assert not resumen.hay_que_pagar
    assert resumen.total_monto == Decimal(0)


def test_el_vencimiento_sigue_al_cliente(config, declaracion_con_pago):
    cliente = config.cliente("acme")
    cliente.facturador_electronico = False
    texto = ConstructorDocumentos(config)._contexto(declaracion_con_pago, cliente)[
        "resumen"
    ].vencimiento_texto
    assert "12 de septiembre" in texto


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
    assert pdf.exists() and pdf.stat().st_size > 3000
    assert pdf.read_bytes().startswith(b"%PDF")
    assert imagen.exists() and imagen.read_bytes().startswith(b"\x89PNG")
    assert pdf.name == "F29-202508-760864285.pdf"

    contenido = html.read_text(encoding="utf-8")
    # El CSS no debe llegar escapado: rompería selectores y tipografías.
    assert ".resumen tr.total td" in contenido
    assert "&gt;" not in contenido.split("</style>")[0]
    assert "1.840.000.-" in contenido          # formato contable, no $1.840.000
    assert "00-123-45678-90" in contenido
    assert "TOTAL A PAGAR F29 AGOSTO 2025" in contenido


@requiere_chromium
def test_el_aviso_sin_pago_no_muestra_datos_bancarios(config, declaracion_sin_pago):
    documentos = ConstructorDocumentos(config).construir(
        declaracion_sin_pago, config.cliente("acme"), guardar_html=True
    )
    contenido = Path(documentos.html).read_text(encoding="utf-8")
    assert "00-123-45678-90" not in contenido
    assert "Fecha de vencimiento" not in contenido


@requiere_chromium
def test_la_propuesta_sale_con_advertencia_en_el_documento(config, declaracion_con_pago):
    from bringmef29.modelos import PROPUESTA

    declaracion_con_pago.procedencia = PROPUESTA
    documentos = ConstructorDocumentos(config).construir(
        declaracion_con_pago, config.cliente("acme"), guardar_html=True
    )
    contenido = Path(documentos.html).read_text(encoding="utf-8")
    assert "propuesta del SII" in contenido
    assert "advertencia" in contenido
