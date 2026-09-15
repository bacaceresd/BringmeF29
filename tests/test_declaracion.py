from decimal import Decimal

from bringmef29.modelos import DeclaracionF29, LineaCodigo, Periodo
from bringmef29.rut import Rut


def _declaracion(**codigos) -> DeclaracionF29:
    return DeclaracionF29(
        rut=Rut.parsear("11.111.111-1"),
        periodo=Periodo(2025, 8),
        lineas=[LineaCodigo(c, Decimal(str(v))) for c, v in codigos.items()],
    )


def test_valor_ignora_ceros_a_la_izquierda():
    declaracion = _declaracion(**{"077": 400000})
    assert declaracion.valor("77") == Decimal(400000)
    assert declaracion.valor("077") == Decimal(400000)


def test_valor_devuelve_el_defecto_si_falta_el_codigo():
    assert _declaracion().valor("091", defecto=Decimal(0)) == Decimal(0)
    assert _declaracion().valor("091") is None


def test_monto_a_pagar_usa_el_total_dentro_de_plazo(declaracion_con_pago):
    assert declaracion_con_pago.monto_a_pagar == Decimal(1840000)
    assert declaracion_con_pago.hay_que_pagar


def test_monto_a_pagar_prefiere_el_total_con_recargo():
    declaracion = _declaracion(**{"091": 1000000, "094": 1085000, "092": 15000, "093": 70000})
    assert declaracion.monto_a_pagar == Decimal(1085000)
    assert declaracion.reajuste == Decimal(15000)
    assert declaracion.multas_intereses == Decimal(70000)


def test_monto_a_pagar_cae_al_impuesto_determinado():
    assert _declaracion(**{"547": 500000}).monto_a_pagar == Decimal(500000)


def test_declaracion_sin_pago(declaracion_sin_pago):
    assert not declaracion_sin_pago.hay_que_pagar
    assert declaracion_sin_pago.monto_a_pagar == Decimal(0)
    assert declaracion_sin_pago.remanente_periodo_siguiente == Decimal(400000)


def test_sin_movimiento():
    assert _declaracion(**{"538": 0, "537": 0}).sin_movimiento
    assert not _declaracion(**{"538": 1}).sin_movimiento


def test_accesos_por_nombre(declaracion_con_pago):
    assert declaracion_con_pago.total_debitos == Decimal(3515000)
    assert declaracion_con_pago.total_creditos == Decimal(2100000)
    assert declaracion_con_pago.ppm == Decimal(185000)
    assert declaracion_con_pago.impuesto_determinado == Decimal(1840000)
