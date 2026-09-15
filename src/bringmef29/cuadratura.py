"""Comprueba que el F29 traído del SII cuadre consigo mismo.

El formulario tiene identidades aritméticas propias: el total de débitos es la
suma de sus líneas, el IVA determinado es la diferencia entre débitos y créditos,
el total con recargo es el total del plazo legal más reajuste, intereses y multas.
Si lo que se leyó del SII respeta esas identidades, se leyó bien.

Esto no recalcula impuestos ni corrige la declaración: sólo compara lo que el SII
entregó contra lo que el propio formulario dice que debe dar. Cuando algo no
calza, casi siempre es que el programa leyó mal una línea —no que el contribuyente
declaró mal—, y por eso el aviso lo muestra en vez de callarlo.

Las identidades y el mapa de líneas viven en ``recursos/codigos_f29.yml``,
generado desde las instrucciones oficiales del SII.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml

from .modelos import DeclaracionF29

RUTA_CATALOGO = Path(__file__).parent / "recursos" / "codigos_f29.yml"


@dataclass
class Descuadre:
    """Una identidad del formulario que no se cumple."""

    nombre: str
    codigo: str
    declarado: Decimal
    calculado: Decimal

    @property
    def diferencia(self) -> Decimal:
        return self.declarado - self.calculado

    def __str__(self) -> str:
        return (
            f"{self.nombre} (código {self.codigo}): el SII trae "
            f"{_miles(self.declarado)} y las líneas dan {_miles(self.calculado)} "
            f"— diferencia {_miles(self.diferencia)}"
        )


def _miles(valor: Decimal) -> str:
    return f"{int(valor):,}".replace(",", ".")


# --------------------------------------------------------------------------- #
# Catálogo
# --------------------------------------------------------------------------- #


def cargar_catalogo(ruta: str | Path | None = None) -> dict:
    archivo = Path(ruta) if ruta else RUTA_CATALOGO
    return yaml.safe_load(archivo.read_text(encoding="utf-8")) or {}


def glosa(codigo: str, catalogo: dict | None = None) -> str:
    """Para qué sirve un código, según las instrucciones del SII."""
    catalogo = catalogo if catalogo is not None else cargar_catalogo()
    entrada = catalogo.get("codigos", {}).get(_normalizar(codigo))
    return entrada["glosa"] if entrada else ""


def describir(codigo: str, catalogo: dict | None = None) -> dict | None:
    """Línea, signo y glosa de un código; ``None`` si no está en el catálogo."""
    catalogo = catalogo if catalogo is not None else cargar_catalogo()
    entrada = catalogo.get("codigos", {}).get(_normalizar(codigo))
    if not entrada:
        return None
    return {"codigo": _normalizar(codigo), **entrada,
            "seccion": seccion_de_linea(entrada["linea"], catalogo)}


def seccion_de_linea(linea: int, catalogo: dict | None = None) -> str:
    catalogo = catalogo if catalogo is not None else cargar_catalogo()
    for tramo in catalogo.get("secciones", []):
        if tramo["desde"] <= linea <= tramo["hasta"]:
            return tramo["nombre"]
    return "Otros"


def _normalizar(codigo: str | int) -> str:
    return str(codigo).lstrip("0") or "0"


# --------------------------------------------------------------------------- #
# Verificación
# --------------------------------------------------------------------------- #


def verificar(declaracion: DeclaracionF29, *, catalogo: dict | None = None) -> list[Descuadre]:
    """Devuelve los descuadres encontrados; lista vacía si todo calza."""
    catalogo = catalogo if catalogo is not None else cargar_catalogo()
    codigos = catalogo.get("codigos", {})
    descuadres: list[Descuadre] = []

    for identidad in catalogo.get("identidades", []):
        total_codigo = _normalizar(identidad["total"])
        declarado = declaracion.valor(total_codigo)

        if "suma_lineas" in identidad:
            calculado = _sumar_lineas(declaracion, codigos, *identidad["suma_lineas"])
        else:
            calculado = _aplicar_formula(declaracion, identidad["formula"])

        if calculado is None:
            continue

        # Un total que el SII no entrega y que además da cero no es un descuadre:
        # es una línea que el contribuyente simplemente no usa.
        if declarado is None:
            if calculado == 0 or identidad.get("solo_si_presente"):
                continue
            declarado = Decimal(0)

        if identidad.get("solo_si_positivo") and calculado <= 0:
            continue
        if declarado == calculado:
            continue

        descuadres.append(
            Descuadre(
                nombre=identidad["nombre"],
                codigo=total_codigo,
                declarado=declarado,
                calculado=calculado,
            )
        )
    return descuadres


def _sumar_lineas(
    declaracion: DeclaracionF29, codigos: dict, desde: int, hasta: int
) -> Decimal | None:
    """Suma los montos de un rango de líneas, respetando el signo del formulario.

    Sólo entra el código de cada línea marcado como ``monto``: los demás son
    cantidades de documentos, tasas o bases imponibles, que no suman.
    """
    total = Decimal(0)
    hubo_alguno = False
    for codigo, datos in codigos.items():
        if not datos.get("monto") or not desde <= datos["linea"] <= hasta:
            continue
        valor = declaracion.valor(codigo)
        if valor is None:
            continue
        hubo_alguno = True
        total += -valor if datos.get("signo") == "-" else valor
    return total if hubo_alguno else None


def _aplicar_formula(declaracion: DeclaracionF29, formula: list[str]) -> Decimal | None:
    """Evalúa una fórmula ``["538", "-", "537"]`` con los valores de la declaración."""
    total: Decimal | None = None
    operador = "+"
    hubo_alguno = False
    for ficha in formula:
        if ficha in ("+", "-"):
            operador = ficha
            continue
        valor = declaracion.valor(_normalizar(ficha))
        if valor is None:
            valor = Decimal(0)
        else:
            hubo_alguno = True
        if total is None:
            total = valor
        else:
            total = total + valor if operador == "+" else total - valor
    return total if hubo_alguno else None
