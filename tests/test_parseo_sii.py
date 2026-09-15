from decimal import Decimal

import pytest

from bringmef29.sii.f29_api import _extraer_lineas, _buscar_declaraciones, a_decimal
from bringmef29.sii.f29_navegador import _lineas_desde_texto


@pytest.mark.parametrize(
    "bruto,esperado",
    [
        ("1.234.567", Decimal(1234567)),
        ("1234", Decimal(1234)),
        (1234, Decimal(1234)),
        ("1.234.567,89", Decimal("1234567.89")),
        ("1234,50", Decimal("1234.50")),
        ("$ 980.000", Decimal(980000)),
        ("-5.000", Decimal(-5000)),
        ("(5.000)", Decimal(-5000)),
        ("0", Decimal(0)),
    ],
)
def test_conversion_de_montos(bruto, esperado):
    assert a_decimal(bruto) == esperado


@pytest.mark.parametrize("bruto", ["", "  ", None, "abc", True])
def test_montos_ilegibles(bruto):
    assert a_decimal(bruto) is None


def test_extrae_codigos_anidados_en_cualquier_nivel():
    crudo = {
        "respuesta": {"codigo": 0, "glosa": "OK"},
        "datos": {
            "declaracion": {
                "folio": "7654321098",
                "detalle": [
                    {"codigo": "538", "valor": "3.515.000", "glosa": "TOTAL DEBITOS"},
                    {"codigo": "537", "valor": "2.100.000"},
                    {"cod": "091", "val": 1415000},
                ],
            }
        },
    }
    lineas = {l.codigo_normalizado: l.valor for l in _extraer_lineas(crudo)}
    assert lineas["538"] == Decimal(3515000)
    assert lineas["537"] == Decimal(2100000)
    assert lineas["91"] == Decimal(1415000)


def test_no_confunde_la_respuesta_de_servicio_con_un_codigo():
    # {"codigo": 0, "glosa": "OK"} no trae valor, así que no debe entrar.
    lineas = list(_extraer_lineas({"respuesta": {"codigo": 0, "glosa": "OK"}}))
    assert lineas == []


def test_primer_codigo_gana_ante_duplicados():
    crudo = [{"codigo": "091", "valor": 100}, {"codigo": "91", "valor": 999}]
    lineas = list(_extraer_lineas(crudo))
    assert len(lineas) == 1
    assert lineas[0].valor == Decimal(100)


def test_busca_la_lista_de_declaraciones():
    crudo = {"data": {"listaEventos": [{"folio": "111", "estado": "Vigente"},
                                       {"folio": "222", "estado": "Rectificada"}]}}
    encontradas = list(_buscar_declaraciones(crudo))
    assert [d["folio"] for d in encontradas] == ["111", "222"]


def test_lee_codigos_desde_el_texto_de_la_pantalla():
    texto = "\n".join(
        [
            "TOTAL DEBITOS [538] 3.515.000",
            "TOTAL CREDITOS [537] 2.100.000",
            "linea sin codigo",
            "TOTAL A PAGAR [091] 1.415.000",
        ]
    )
    lineas = {l.codigo_normalizado: l.valor for l in _lineas_desde_texto(texto)}
    assert lineas == {
        "538": Decimal(3515000),
        "537": Decimal(2100000),
        "91": Decimal(1415000),
    }
