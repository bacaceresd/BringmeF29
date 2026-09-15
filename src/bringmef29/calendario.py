"""Feriados chilenos y vencimiento del F29.

El plazo del F29 no es una fecha fija: vence el día 12 del mes siguiente en papel
y el **día 20 para quienes facturan electrónicamente** —que hoy son casi todos—,
y si ese día cae sábado, domingo o feriado, corre al día hábil siguiente.

Los feriados fijos y los de Semana Santa se calculan aquí. Los movibles por ley
(29 de junio, 12 de octubre, 31 de octubre) siguen las reglas de traslado de las
leyes 19.973 y 20.299. Cualquier otro —elecciones, feriados regionales, los que
se decretan para un año puntual— se agrega en la configuración con
``feriados_extra``; el calendario oficial lo publica la Dirección del Trabajo.
"""

from __future__ import annotations

from datetime import date, timedelta

# Vencimiento habitual según cómo factura el contribuyente.
DIA_FACTURADOR_ELECTRONICO = 20
DIA_PAPEL = 12

DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def domingo_de_pascua(anio: int) -> date:
    """Domingo de Resurrección por el algoritmo de Meeus/Jones/Butcher (gregoriano)."""
    a = anio % 19
    b, c = divmod(anio, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return date(anio, mes, dia + 1)


def _trasladar_ley_19973(feriado: date) -> date:
    """29 de junio y 12 de octubre: martes → lunes anterior; miércoles/jueves → viernes siguiente."""
    dia_semana = feriado.weekday()          # lunes = 0
    if dia_semana == 1:                      # martes
        return feriado - timedelta(days=1)
    if dia_semana in (2, 3):                 # miércoles o jueves
        return feriado + timedelta(days=4 - dia_semana)
    return feriado


def _trasladar_ley_20299(feriado: date) -> date:
    """31 de octubre: martes → viernes anterior; miércoles → viernes siguiente."""
    dia_semana = feriado.weekday()
    if dia_semana == 1:                      # martes
        return feriado - timedelta(days=4)
    if dia_semana == 2:                      # miércoles
        return feriado + timedelta(days=2)
    return feriado


def feriados(anio: int) -> set[date]:
    """Feriados legales de alcance nacional para ``anio``."""
    pascua = domingo_de_pascua(anio)
    fechas = {
        date(anio, 1, 1),                    # Año Nuevo
        pascua - timedelta(days=2),          # Viernes Santo
        pascua - timedelta(days=1),          # Sábado Santo
        date(anio, 5, 1),                    # Día del Trabajo
        date(anio, 5, 21),                   # Glorias Navales
        date(anio, 6, 20),                   # Día de los Pueblos Indígenas
        date(anio, 7, 16),                   # Virgen del Carmen
        date(anio, 8, 15),                   # Asunción de la Virgen
        date(anio, 9, 18),                   # Independencia Nacional
        date(anio, 9, 19),                   # Glorias del Ejército
        date(anio, 11, 1),                   # Día de Todos los Santos
        date(anio, 12, 8),                   # Inmaculada Concepción
        date(anio, 12, 25),                  # Navidad
        _trasladar_ley_19973(date(anio, 6, 29)),    # San Pedro y San Pablo
        _trasladar_ley_19973(date(anio, 10, 12)),   # Encuentro de Dos Mundos
        _trasladar_ley_20299(date(anio, 10, 31)),   # Iglesias Evangélicas
    }
    return fechas


def es_habil(dia: date, extra: set[date] | None = None) -> bool:
    if dia.weekday() >= 5:                   # sábado o domingo
        return False
    if dia in feriados(dia.year):
        return False
    return not (extra and dia in extra)


def siguiente_habil(dia: date, extra: set[date] | None = None) -> date:
    """El propio día si es hábil; si no, el primer día hábil que le sigue."""
    tope = dia + timedelta(days=30)
    while not es_habil(dia, extra) and dia < tope:
        dia += timedelta(days=1)
    return dia


def vencimiento_f29(
    anio: int,
    mes: int,
    *,
    facturador_electronico: bool = True,
    feriados_extra: set[date] | None = None,
) -> date:
    """Fecha en que vence el F29 del período ``anio``-``mes``.

    El plazo corre sobre el mes siguiente al declarado. Es una referencia para el
    aviso al cliente, no una resolución del SII: prórrogas puntuales y feriados
    regionales hay que agregarlos con ``feriados_extra``.
    """
    dia = DIA_FACTURADOR_ELECTRONICO if facturador_electronico else DIA_PAPEL
    anio_venc, mes_venc = (anio + 1, 1) if mes == 12 else (anio, mes + 1)
    return siguiente_habil(date(anio_venc, mes_venc, dia), feriados_extra)


def fecha_con_dia_semana(dia: date) -> str:
    """``Lunes 21 de septiembre, 2026`` — como lo escribe un contador en el aviso."""
    from .modelos import MESES_ES

    nombre = DIAS_ES[dia.weekday()].capitalize()
    return f"{nombre} {dia.day} de {MESES_ES[dia.month - 1]}, {dia.year}"
