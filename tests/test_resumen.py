"""El resumen agrupado que ve el cliente: IVA, Retenciones, PPM y total."""

from decimal import Decimal

import pytest

from bringmef29 import resumen as R
from bringmef29.modelos import DeclaracionF29, LineaCodigo, Periodo
from bringmef29.rut import Rut

# Caso real de un contribuyente con remanente de crédito fiscal: no paga IVA ni
# PPM, y lo único que entera son las retenciones.
CASO = {
    # Débitos (línea 7 a 22): boletas + facturas, menos notas de crédito emitidas.
    "111": 10000000,   # L10  IVA débito de boletas
    "502": 1900000,    # L7   IVA débito de facturas emitidas
    "510": 10000000,   # L13  notas de crédito emitidas — resta
    "538": 1900000,    # L23  TOTAL DÉBITOS
    # Créditos (línea 28 a 48).
    "520": 1200000,    # L28  facturas recibidas del giro
    "528": 50000,       # L32  notas de crédito recibidas — resta
    "504": 900000,    # L36  remanente del mes anterior
    "537": 2050000,    # L49  TOTAL CRÉDITOS
    # Créditos superan débitos: queda remanente, no hay IVA que pagar.
    "77": 150000,     # L50  remanente para el mes siguiente
    # Retenciones y PPM.
    "48": 40000,       # L60  impuesto único 2ª categoría
    "151": 300000,     # L61  honorarios
    "62": 0,           # L69  PPM neto determinado
    "563": 5000000,   # L69  base imponible PPM
    "91": 340000,      # L141 TOTAL A PAGAR EN PLAZO LEGAL
}


def declaracion(codigos: dict, periodo: Periodo = Periodo(2026, 8)) -> DeclaracionF29:
    return DeclaracionF29(
        rut=Rut.parsear("11111111-1"),
        periodo=periodo,
        lineas=[LineaCodigo(c, Decimal(str(v))) for c, v in codigos.items()],
    )


def lineas_planas(resumen: R.Resumen) -> list[tuple[str, str]]:
    return [
        (l.glosa, R.monto_contable(l.monto, parentesis=l.parentesis))
        for g in resumen.grupos
        for l in g.lineas
        if not l.separador
    ]


# --------------------------------------------------------------------------- #
# Formato contable
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "valor,parentesis,esperado",
    [
        (10000000, False, "10.000.000.-"),
        (50000, False, "50.000.-"),
        (1200000, True, "(1.200.000.-)"),
        (0, False, "0.-"),
        (-5000, False, "(5.000.-)"),
        (None, False, "—"),
    ],
)
def test_monto_contable(valor, parentesis, esperado):
    assert R.monto_contable(valor, parentesis=parentesis) == esperado


# --------------------------------------------------------------------------- #
# Armado
# --------------------------------------------------------------------------- #


def test_grupos_esperados():
    resumen = R.construir(declaracion(CASO))
    assert [g.titulo for g in resumen.grupos] == ["IVA", "Retenciones", "PPM"]


def test_el_iva_sale_como_lo_escribe_un_contador():
    resumen = R.construir(declaracion(CASO))
    iva = dict(lineas_planas(resumen))
    assert iva["IVA DF Boletas electrónicas"] == "10.000.000.-"
    assert iva["Total IVA Débito"] == "1.900.000.-"
    assert iva["IVA CF Facturas afectas"] == "(1.200.000.-)"
    assert iva["IVA CF Notas de crédito recibidas"] == "50.000.-"
    assert iva["Remanente IVA CF mes anterior"] == "(900.000.-)"
    assert iva["Total IVA Crédito"] == "(2.050.000.-)"
    assert iva["Remanente IVA CF mes siguiente (IVA DF − IVA CF)"] == "150.000.-"


def test_las_retenciones_se_suman():
    resumen = R.construir(declaracion(CASO))
    filas = dict(lineas_planas(resumen))
    assert filas["Impuesto único 2ª categoría"] == "40.000.-"
    assert filas["Honorarios serv. profesionales"] == "300.000.-"
    assert filas["Total retenciones a pagar"] == "340.000.-"


def test_sin_ppm_aparece_la_nota_y_no_un_cero():
    resumen = R.construir(declaracion(CASO))
    ppm = next(g for g in resumen.grupos if g.titulo == "PPM")
    assert ppm.nota == "No paga PPM"
    assert all(l.glosa != "PPM neto determinado" for l in ppm.lineas)


def test_con_ppm_no_aparece_la_nota():
    resumen = R.construir(declaracion({**CASO, "062": 185000}))
    ppm = next(g for g in resumen.grupos if g.titulo == "PPM")
    assert ppm.nota == ""
    assert any(l.glosa == "PPM neto determinado" for l in ppm.lineas)


def test_total_y_vencimiento():
    resumen = R.construir(declaracion(CASO), vencimiento_texto="Lunes 21 de septiembre, 2026")
    assert resumen.total_glosa == "TOTAL A PAGAR F29 AGOSTO 2026"
    assert resumen.total_monto == Decimal(340000)
    assert resumen.hay_que_pagar
    assert resumen.vencimiento_texto == "Lunes 21 de septiembre, 2026"


def test_las_lineas_en_cero_no_se_imprimen():
    resumen = R.construir(declaracion({**CASO, "151": 0}))
    assert all(g != "Honorarios serv. profesionales" for g, _ in lineas_planas(resumen))


def test_un_codigo_ausente_no_inventa_una_linea():
    """Un código que el cliente no usa simplemente no aparece."""
    resumen = R.construir(declaracion({"538": 100, "537": 50, "091": 50}))
    glosas = [g for g, _ in lineas_planas(resumen)]
    assert "IVA DF Boletas electrónicas" not in glosas
    assert "Total IVA Débito" in glosas


def test_un_grupo_sin_datos_no_se_imprime():
    resumen = R.construir(declaracion({"538": 100, "537": 50, "091": 50}))
    assert "Retenciones" not in [g.titulo for g in resumen.grupos]


def test_avisa_cuando_las_partes_no_suman_el_total():
    """El total de retenciones sale del formulario; si no cuadra, hay que saberlo."""
    layout = {
        "grupos": [{
            "titulo": "Retenciones",
            "lineas": [
                {"glosa": "Impuesto único", "codigo": "048"},
                {"glosa": "Honorarios", "codigo": "151"},
                {"signo": "=", "glosa": "Total retenciones", "codigo": "049",
                 "suma_de": ["048", "151"], "siempre": True, "total": True},
            ],
        }],
        "total": {"glosa": "TOTAL", "codigos": ["091"]},
    }
    resumen = R.construir(
        declaracion({"048": 40000, "151": 300000, "049": 999999, "091": 999999}), layout=layout
    )
    assert len(resumen.descuadres) == 1
    assert "Total retenciones" in resumen.descuadres[0]


def test_no_avisa_cuando_cuadra():
    layout = {
        "grupos": [{
            "titulo": "Retenciones",
            "lineas": [
                {"glosa": "Impuesto único", "codigo": "048"},
                {"signo": "=", "glosa": "Total", "codigo": "049", "suma_de": ["048"]},
            ],
        }],
        "total": {"glosa": "TOTAL", "codigos": ["091"]},
    }
    resumen = R.construir(declaracion({"048": 100, "049": 100, "091": 100}), layout=layout)
    assert resumen.descuadres == []


def test_un_codigo_con_alternativas_usa_la_primera_presente():
    """El layout admite varias variantes del formulario para una misma línea."""
    layout = {
        "grupos": [{
            "titulo": "IVA",
            "lineas": [{"glosa": "Crédito", "codigo": ["520", "511"]}],
        }],
        "total": {"glosa": "TOTAL", "codigos": ["091"]},
    }
    solo_511 = R.construir(declaracion({"511": 777, "091": 0}), layout=layout)
    assert lineas_planas(solo_511) == [("Crédito", "777.-")]

    ambos = R.construir(declaracion({"520": 111, "511": 777, "091": 0}), layout=layout)
    assert lineas_planas(ambos) == [("Crédito", "111.-")]


def test_los_separadores_no_quedan_sueltos():
    """Un separador sin líneas alrededor sobra."""
    layout = {
        "grupos": [{
            "titulo": "IVA",
            "lineas": [
                {"separador": True},
                {"glosa": "Débito", "codigo": "538"},
                {"separador": True},
                {"separador": True},
            ],
        }],
        "total": {"glosa": "TOTAL", "codigos": ["091"]},
    }
    resumen = R.construir(declaracion({"538": 100, "091": 0}), layout=layout)
    lineas = resumen.grupos[0].lineas
    assert not lineas[0].separador
    assert not lineas[-1].separador
