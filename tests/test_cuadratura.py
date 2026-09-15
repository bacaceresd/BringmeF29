"""Las identidades del F29: que lo traído del SII cuadre consigo mismo."""

from decimal import Decimal

import pytest

from bringmef29.cuadratura import (
    cargar_catalogo,
    describir,
    glosa,
    seccion_de_linea,
    verificar,
)
from bringmef29.modelos import DeclaracionF29, LineaCodigo, Periodo
from bringmef29.rut import Rut

# Declaración que cuadra entera: débitos y créditos suman sus totales, y como el
# crédito supera al débito queda remanente para el mes siguiente.
CUADRA = {
    "111": 23030105, "502": 2317063, "510": 23030105, "538": 2317063,
    "520": 1993566, "528": 6674, "504": 2533186, "537": 4520078,
    "77": 2203015,
    "48": 53572, "151": 386874, "62": 0, "563": 13823935, "91": 440446,
}


def declaracion(codigos: dict) -> DeclaracionF29:
    return DeclaracionF29(
        rut=Rut.parsear("76086428-5"),
        periodo=Periodo(2026, 8),
        lineas=[LineaCodigo(c, Decimal(str(v))) for c, v in codigos.items()],
    )


# --------------------------------------------------------------------------- #
# Catálogo
# --------------------------------------------------------------------------- #


def test_el_catalogo_trae_los_codigos_del_formulario():
    codigos = cargar_catalogo()["codigos"]
    assert len(codigos) > 180
    for codigo in ("538", "537", "77", "89", "595", "547", "91", "94"):
        assert codigo in codigos


@pytest.mark.parametrize(
    "codigo,linea,signo",
    [
        ("502", 7, "+"),      # IVA débito de facturas emitidas
        ("111", 10, "+"),     # IVA débito de boletas
        ("510", 13, "-"),     # notas de crédito emitidas: restan del débito
        ("501", 17, "+"),     # liquidaciones factura
        ("538", 23, "="),     # total débitos
        ("520", 28, "+"),     # crédito de facturas del giro
        ("528", 32, "-"),     # notas de crédito recibidas: restan del crédito
        ("504", 36, "+"),     # remanente del mes anterior
        ("537", 49, "="),     # total créditos
    ],
)
def test_linea_y_signo_de_los_codigos_clave(codigo, linea, signo):
    datos = describir(codigo)
    assert datos["linea"] == linea
    assert datos["signo"] == signo


def test_el_codigo_de_monto_esta_marcado():
    """En cada línea, sólo uno de los códigos lleva el monto que suma."""
    assert describir("502")["monto"]        # monto
    assert not describir("503")["monto"]    # cantidad de facturas
    assert describir("111")["monto"]
    assert not describir("110")["monto"]    # cantidad de boletas


def test_los_documentos_electronicos_recibidos_son_informativos():
    """El 511 no es crédito fiscal: es el total de documentos recibidos."""
    datos = describir("511")
    assert datos["signo"] == ""
    assert "informativo" in datos["glosa"].lower()


def test_glosa_y_seccion():
    assert glosa("538") == "TOTAL DÉBITOS"
    assert describir("48")["glosa"].startswith("Retención de Impuesto Único")
    assert seccion_de_linea(10) == "Débitos"
    assert seccion_de_linea(30) == "Créditos"
    assert seccion_de_linea(69) == "Retenciones y PPM"


def test_codigo_desconocido():
    assert describir("999999") is None
    assert glosa("999999") == ""


def test_los_ceros_a_la_izquierda_dan_igual():
    assert describir("048")["linea"] == describir("48")["linea"]


# --------------------------------------------------------------------------- #
# Verificación
# --------------------------------------------------------------------------- #


def test_una_declaracion_consistente_no_tiene_descuadres():
    assert verificar(declaracion(CUADRA)) == []


def test_detecta_un_total_de_debitos_que_no_suma():
    descuadres = verificar(declaracion({**CUADRA, "538": 9999999}))
    nombres = [d.nombre for d in descuadres]
    assert "Total débitos" in nombres
    problema = next(d for d in descuadres if d.nombre == "Total débitos")
    assert problema.declarado == Decimal(9999999)
    assert problema.calculado == Decimal(2317063)
    assert problema.diferencia == Decimal(7682936)
    assert "538" in str(problema)


def test_detecta_un_total_de_creditos_que_no_suma():
    descuadres = verificar(declaracion({**CUADRA, "537": 1}))
    assert any(d.nombre == "Total créditos" for d in descuadres)


def test_las_notas_de_credito_recibidas_restan_del_credito():
    """Si 528 sumara en vez de restar, 537 no cuadraría."""
    sin_notas = {k: v for k, v in CUADRA.items() if k != "528"}
    # 520 + 504 = 4.526.752, que ya no calza con el 537 declarado.
    assert any(d.nombre == "Total créditos" for d in verificar(declaracion(sin_notas)))


def test_detecta_un_remanente_mal_arrastrado():
    descuadres = verificar(declaracion({**CUADRA, "77": 1}))
    assert any(d.codigo == "77" for d in descuadres)


def test_el_iva_determinado_no_se_exige_cuando_hay_remanente():
    """Con créditos mayores que débitos el resultado va al 77, no al 89."""
    assert all(d.codigo != "89" for d in verificar(declaracion(CUADRA)))


def test_detecta_un_iva_determinado_equivocado():
    con_iva = {**CUADRA, "538": 6000000, "510": 19347168, "77": 0, "89": 1}
    assert any(d.codigo == "89" for d in verificar(declaracion(con_iva)))


def test_total_con_recargo():
    fuera_de_plazo = {**CUADRA, "92": 5000, "93": 20000, "94": 465446}
    assert verificar(declaracion(fuera_de_plazo)) == []
    mal = {**fuera_de_plazo, "94": 999999}
    assert any(d.codigo == "94" for d in verificar(declaracion(mal)))


def test_el_recargo_no_se_exige_en_una_declaracion_dentro_de_plazo():
    assert all(d.codigo != "94" for d in verificar(declaracion(CUADRA)))


def test_una_declaracion_vacia_no_produce_descuadres():
    assert verificar(declaracion({})) == []


def test_el_texto_del_descuadre_es_legible():
    problema = verificar(declaracion({**CUADRA, "538": 9999999}))[0]
    texto = str(problema)
    assert "9.999.999" in texto and "2.317.063" in texto
