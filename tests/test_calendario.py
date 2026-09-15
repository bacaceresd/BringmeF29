"""Feriados chilenos y el plazo real del F29."""

from datetime import date

import pytest

from bringmef29.calendario import (
    domingo_de_pascua,
    es_habil,
    fecha_con_dia_semana,
    feriados,
    siguiente_habil,
    vencimiento_f29,
)


@pytest.mark.parametrize(
    "anio,esperado",
    [(2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)), (2026, date(2026, 4, 5))],
)
def test_domingo_de_pascua(anio, esperado):
    assert domingo_de_pascua(anio) == esperado


def test_feriados_fijos():
    del_anio = feriados(2026)
    for fecha in [
        date(2026, 1, 1), date(2026, 5, 1), date(2026, 5, 21),
        date(2026, 9, 18), date(2026, 9, 19), date(2026, 12, 25),
    ]:
        assert fecha in del_anio


def test_semana_santa_esta_en_los_feriados():
    del_anio = feriados(2026)
    assert date(2026, 4, 3) in del_anio      # Viernes Santo
    assert date(2026, 4, 4) in del_anio      # Sábado Santo


def test_traslado_ley_19973():
    # 29-06-2027 cae martes → se traslada al lunes 28.
    assert date(2027, 6, 28) in feriados(2027)
    # 12-10-2027 cae martes → lunes 11.
    assert date(2027, 10, 11) in feriados(2027)


def test_dias_habiles():
    assert es_habil(date(2026, 9, 15))            # martes común
    assert not es_habil(date(2026, 9, 19))        # feriado
    assert not es_habil(date(2026, 9, 20))        # domingo
    assert not es_habil(date(2026, 9, 15), {date(2026, 9, 15)})   # feriado agregado a mano


def test_siguiente_habil_salta_el_fin_de_semana_largo():
    assert siguiente_habil(date(2026, 9, 18)) == date(2026, 9, 21)
    assert siguiente_habil(date(2026, 9, 15)) == date(2026, 9, 15)


def test_vencimiento_del_f29():
    # Agosto 2026: el día 20 cae domingo y el 18-19 son feriados → lunes 21.
    assert vencimiento_f29(2026, 8) == date(2026, 9, 21)
    # Agosto 2025: el día 20 cae sábado → lunes 22.
    assert vencimiento_f29(2025, 8) == date(2025, 9, 22)


def test_vencimiento_en_papel_usa_el_dia_12():
    assert vencimiento_f29(2025, 8, facturador_electronico=False) == date(2025, 9, 12)


def test_vencimiento_de_diciembre_pasa_al_ano_siguiente():
    assert vencimiento_f29(2025, 12).year == 2026


def test_feriados_extra_corren_el_plazo():
    extra = {date(2026, 9, 21), date(2026, 9, 22)}
    assert vencimiento_f29(2026, 8, feriados_extra=extra) == date(2026, 9, 23)


def test_fecha_con_dia_semana():
    assert fecha_con_dia_semana(date(2026, 9, 21)) == "Lunes 21 de septiembre, 2026"
