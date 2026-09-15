from datetime import date

import pytest

from bringmef29.modelos import Periodo, PeriodoInvalido


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("2025-08", (2025, 8)),
        ("2025/8", (2025, 8)),
        ("08-2025", (2025, 8)),
        ("202508", (2025, 8)),
    ],
)
def test_parseo(entrada, esperado):
    periodo = Periodo.parsear(entrada)
    assert (periodo.anio, periodo.mes) == esperado


@pytest.mark.parametrize("entrada", ["2025-13", "agosto", "", "25-8"])
def test_parseo_invalido(entrada):
    with pytest.raises(PeriodoInvalido):
        Periodo.parsear(entrada)


def test_etiqueta_y_codigo():
    periodo = Periodo(2025, 8)
    assert periodo.etiqueta == "Agosto 2025"
    assert periodo.codigo == "202508"
    assert str(periodo) == "2025-08"


def test_periodo_anterior_cruza_el_ano():
    assert Periodo.anterior_a_hoy(date(2025, 1, 15)) == Periodo(2024, 12)
    assert Periodo.anterior_a_hoy(date(2025, 9, 3)) == Periodo(2025, 8)


def test_vencimiento_legal_facturador_electronico():
    """Día 20 del mes siguiente, corrido al hábil siguiente si cae feriado o fin de semana."""
    # 20-09-2025 cae sábado → lunes 22.
    assert Periodo(2025, 8).vencimiento_legal() == date(2025, 9, 22)
    # 20-09-2026 cae domingo, y el 18 y 19 son feriados → lunes 21.
    assert Periodo(2026, 8).vencimiento_legal() == date(2026, 9, 21)
    # 20-01-2026 es martes hábil.
    assert Periodo(2025, 12).vencimiento_legal() == date(2026, 1, 20)


def test_vencimiento_legal_en_papel():
    assert Periodo(2025, 8).vencimiento_legal(facturador_electronico=False) == date(2025, 9, 12)


def test_vencimiento_considera_feriados_adicionales():
    from datetime import date as _d

    extra = {_d(2026, 1, 20), _d(2026, 1, 21)}
    assert Periodo(2025, 12).vencimiento_legal(feriados_extra=extra) == date(2026, 1, 22)


def test_ultimo_dia_considera_bisiestos():
    assert Periodo(2024, 2).ultimo_dia == date(2024, 2, 29)
    assert Periodo(2025, 2).ultimo_dia == date(2025, 2, 28)
