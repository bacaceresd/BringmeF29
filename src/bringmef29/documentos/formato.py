"""Formateo de montos y fechas en convención chilena."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from ..modelos import MESES_ES


def pesos(valor: Decimal | int | float | None, *, simbolo: bool = True) -> str:
    """``1234567`` → ``$1.234.567``. Los pesos se muestran sin decimales."""
    if valor is None:
        return "—"
    entero = Decimal(str(valor)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    texto = f"{abs(int(entero)):,}".replace(",", ".")
    signo = "-" if entero < 0 else ""
    return f"{signo}${texto}" if simbolo else f"{signo}{texto}"


def numero(valor: Decimal | int | float | None) -> str:
    return pesos(valor, simbolo=False)


def fecha_larga(valor: date | datetime | None) -> str:
    """``date(2025, 9, 12)`` → ``12 de septiembre de 2025``."""
    if valor is None:
        return "—"
    if isinstance(valor, datetime):
        valor = valor.date()
    return f"{valor.day} de {MESES_ES[valor.month - 1]} de {valor.year}"


def fecha_corta(valor: date | datetime | None) -> str:
    if valor is None:
        return "—"
    if isinstance(valor, datetime):
        valor = valor.date()
    return valor.strftime("%d-%m-%Y")
