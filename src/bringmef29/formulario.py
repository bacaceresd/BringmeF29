"""Arma el Formulario 29 por secciones, como lo muestra el borrador del SII.

Es la versión formal del período —la que va por correo— frente al resumen corto
de :mod:`bringmef29.resumen`, que es el que se manda por WhatsApp. Aquí cada
sección del formulario (débitos, créditos, retenciones, PPM, resultado) es un
bloque aparte con su número de línea, su código y su glosa oficial.

Dos formas de la misma estructura:

``compacto``
    Sólo las líneas que traen valor. Es lo que se lee de verdad: un F29 típico
    usa quince o veinte líneas de las ochenta y siete.
``completo``
    Todas las líneas del formulario, con las casillas vacías incluidas, para
    cotejar contra el SII línea por línea.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import yaml

from .modelos import DeclaracionF29

RUTA_ESTRUCTURA = Path(__file__).parent / "recursos" / "formulario_f29.yml"


@dataclass
class Casilla:
    """Un código con su valor, tal como aparece en una casilla del formulario."""

    codigo: str
    valor: Decimal | None = None
    etiqueta: str = ""

    @property
    def tiene_valor(self) -> bool:
        return self.valor is not None


@dataclass
class LineaFormulario:
    numero: int
    glosa: str
    cantidad: Casilla | None = None
    monto: Casilla | None = None
    extra: list[Casilla] = field(default_factory=list)
    signo: str = ""
    total: bool = False
    destacar: bool = False

    @property
    def tiene_valor(self) -> bool:
        """Una línea cuenta como usada si alguna de sus casillas trae valor."""
        casillas = [self.cantidad, self.monto, *self.extra]
        return any(c is not None and c.tiene_valor for c in casillas)


@dataclass
class SeccionFormulario:
    titulo: str
    subtitulo: str = ""
    columnas: list[str] = field(default_factory=list)
    lineas: list[LineaFormulario] = field(default_factory=list)

    @property
    def tiene_valor(self) -> bool:
        return any(l.tiene_valor for l in self.lineas)


@dataclass
class Formulario:
    declaracion: DeclaracionF29
    secciones: list[SeccionFormulario] = field(default_factory=list)
    completo: bool = False

    @property
    def lineas_con_valor(self) -> int:
        return sum(1 for s in self.secciones for l in s.lineas if l.tiene_valor)


def cargar_estructura(ruta: str | Path | None = None) -> dict:
    archivo = Path(ruta) if ruta else RUTA_ESTRUCTURA
    return yaml.safe_load(archivo.read_text(encoding="utf-8")) or {}


def construir(
    declaracion: DeclaracionF29,
    *,
    completo: bool = False,
    estructura: dict | None = None,
) -> Formulario:
    """Arma el formulario con los valores de la declaración.

    Con ``completo=False`` quedan sólo las líneas que traen valor, y las
    secciones que se vacían del todo desaparecen: el documento muestra lo que el
    contribuyente efectivamente usó.
    """
    estructura = estructura if estructura is not None else cargar_estructura()
    formulario = Formulario(declaracion=declaracion, completo=completo)

    for bruta in estructura.get("secciones", []) or []:
        seccion = SeccionFormulario(
            titulo=str(bruta.get("titulo", "")),
            subtitulo=str(bruta.get("subtitulo", "")),
            columnas=list(bruta.get("columnas", []) or []),
        )
        for cruda in bruta.get("lineas", []) or []:
            linea = _construir_linea(cruda, declaracion)
            if completo or linea.tiene_valor:
                seccion.lineas.append(linea)
        if seccion.lineas:
            formulario.secciones.append(seccion)

    return formulario


def _construir_linea(cruda: dict, declaracion: DeclaracionF29) -> LineaFormulario:
    def casilla(codigo, etiqueta: str = "") -> Casilla | None:
        if not codigo:
            return None
        return Casilla(codigo=str(codigo), valor=declaracion.valor(str(codigo)), etiqueta=etiqueta)

    return LineaFormulario(
        numero=int(cruda.get("n", 0)),
        glosa=str(cruda.get("glosa", "")),
        cantidad=casilla(cruda.get("cantidad")),
        monto=casilla(cruda.get("codigo")),
        extra=[
            c for c in (
                casilla(e.get("codigo"), str(e.get("etiqueta", "")))
                for e in (cruda.get("extra") or [])
            ) if c is not None
        ],
        signo=str(cruda.get("signo", "")),
        total=bool(cruda.get("total")),
        destacar=bool(cruda.get("destacar")),
    )


# --------------------------------------------------------------------------- #
# Formato
# --------------------------------------------------------------------------- #


def monto(valor: Decimal | int | float | None) -> str:
    """``2317063`` → ``2.317.063``. Una casilla vacía se muestra vacía."""
    if valor is None:
        return ""
    return f"{int(round(float(valor))):,}".replace(",", ".")
