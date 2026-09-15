"""El resumen agrupado que ve el cliente: IVA, Retenciones, PPM y total."""

from decimal import Decimal

import pytest

from bringmef29 import resumen as R
from bringmef29.modelos import DeclaracionF29, LineaCodigo, Periodo
from bringmef29.rut import Rut

# Caso real de un contribuyente con remanente de crédito fiscal: no paga IVA ni
# PPM, y lo único que entera son las retenciones.
CASO = {
    "111": 23030105, "502": 2317063, "538": 2317063,
    "520": 1993566, "527": 6674, "504": 2533186, "537": 4520078,
    "077": 2203015,
    "048": 53572, "151": 386874,
    "062": 0, "563": 13823935,
    "091": 440446,
}


def declaracion(codigos: dict, periodo: Periodo = Periodo(2026, 8)) -> DeclaracionF29:
    return DeclaracionF29(
        rut=Rut.parsear("76086428-5"),
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
        (23030105, False, "23.030.105.-"),
        (6674, False, "6.674.-"),
        (1993566, True, "(1.993.566.-)"),
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
    assert iva["IVA DF Boletas electrónicas"] == "23.030.105.-"
    assert iva["Total IVA Débito"] == "2.317.063.-"
    assert iva["IVA CF Facturas afectas"] == "(1.993.566.-)"
    assert iva["IVA CF Notas de crédito recibidas"] == "6.674.-"
    assert iva["Remanente IVA CF mes anterior"] == "(2.533.186.-)"
    assert iva["Total IVA Crédito"] == "(4.520.078.-)"
    assert iva["Remanente IVA CF mes siguiente (IVA DF − IVA CF)"] == "2.203.015.-"


def test_las_retenciones_se_suman():
    resumen = R.construir(declaracion(CASO))
    filas = dict(lineas_planas(resumen))
    assert filas["Impuesto único 2ª categoría"] == "53.572.-"
    assert filas["Honorarios serv. profesionales"] == "386.874.-"
    assert filas["Total retenciones a pagar"] == "440.446.-"


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
    assert resumen.total_monto == Decimal(440446)
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
        declaracion({"048": 53572, "151": 386874, "049": 999999, "091": 999999}), layout=layout
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
