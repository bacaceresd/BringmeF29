"""Utilidades de RUT chileno: normalización, validación y formateo."""

from __future__ import annotations

import re
from dataclasses import dataclass

_NO_ALFANUMERICO = re.compile(r"[^0-9kK]")


class RutInvalido(ValueError):
    """El RUT no tiene un formato válido o su dígito verificador no calza."""


def digito_verificador(cuerpo: int) -> str:
    """Calcula el DV de un RUT con el algoritmo módulo 11."""
    suma = 0
    multiplicador = 2
    for digito in reversed(str(cuerpo)):
        suma += int(digito) * multiplicador
        multiplicador = 2 if multiplicador == 7 else multiplicador + 1
    resto = 11 - (suma % 11)
    if resto == 11:
        return "0"
    if resto == 10:
        return "K"
    return str(resto)


@dataclass(frozen=True)
class Rut:
    """RUT validado. `cuerpo` es la parte numérica y `dv` el dígito verificador en mayúscula."""

    cuerpo: int
    dv: str

    @classmethod
    def parsear(cls, valor: str | int) -> "Rut":
        limpio = _NO_ALFANUMERICO.sub("", str(valor)).upper()
        if len(limpio) < 2:
            raise RutInvalido(f"RUT demasiado corto: {valor!r}")
        cuerpo_txt, dv = limpio[:-1], limpio[-1]
        if not cuerpo_txt.isdigit():
            raise RutInvalido(f"El cuerpo del RUT debe ser numérico: {valor!r}")
        cuerpo = int(cuerpo_txt)
        esperado = digito_verificador(cuerpo)
        if dv != esperado:
            raise RutInvalido(
                f"Dígito verificador inválido para {cuerpo}: recibido {dv}, esperado {esperado}"
            )
        return cls(cuerpo=cuerpo, dv=dv)

    @property
    def sin_formato(self) -> str:
        """`123456789` — como lo esperan los formularios del SII."""
        return f"{self.cuerpo}{self.dv}"

    @property
    def con_guion(self) -> str:
        """`12345678-9`."""
        return f"{self.cuerpo}-{self.dv}"

    @property
    def formateado(self) -> str:
        """`12.345.678-9` — para mostrar al usuario."""
        return f"{self.cuerpo:,}".replace(",", ".") + f"-{self.dv}"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.con_guion


def es_valido(valor: str | int) -> bool:
    try:
        Rut.parsear(valor)
    except RutInvalido:
        return False
    return True
