"""Arma el resumen del F29 que ve el cliente: IVA, Retenciones, PPM y total.

No es la lista cruda de códigos del formulario —eso no se lo entiende nadie fuera
de una oficina contable— sino el mismo resumen que un contador escribe a mano:
agrupado, con signos ``(+) (-) (=)`` y los montos que restan entre paréntesis.

El armado no calcula impuestos: toma los códigos tal como el SII los tiene. Lo
que sí hace es **cuadrar**: cuando el layout declara de qué componentes sale un
total, compara la suma con el total del formulario y avisa si no calzan, en vez
de imprimir un resumen que no suma.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import yaml

from .modelos import DeclaracionF29, Periodo

RUTA_LAYOUT = Path(__file__).parent / "recursos" / "resumen_f29.yml"


@dataclass
class LineaResumen:
    glosa: str = ""
    monto: Decimal | None = None
    signo: str = ""
    parentesis: bool = False
    total: bool = False
    destacar: bool = False
    separador: bool = False


@dataclass
class GrupoResumen:
    titulo: str
    lineas: list[LineaResumen] = field(default_factory=list)
    nota: str = ""


@dataclass
class Resumen:
    grupos: list[GrupoResumen] = field(default_factory=list)
    total_glosa: str = ""
    total_monto: Decimal = Decimal(0)
    vencimiento_texto: str = ""
    descuadres: list[str] = field(default_factory=list)

    @property
    def hay_que_pagar(self) -> bool:
        return self.total_monto > 0


def cargar_layout(ruta: str | Path | None = None) -> dict:
    archivo = Path(ruta) if ruta else RUTA_LAYOUT
    return yaml.safe_load(archivo.read_text(encoding="utf-8")) or {}


def construir(
    declaracion: DeclaracionF29,
    *,
    layout: dict | None = None,
    vencimiento_texto: str = "",
) -> Resumen:
    """Construye el resumen a partir de los códigos de la declaración."""
    layout = layout if layout is not None else cargar_layout()
    resumen = Resumen(vencimiento_texto=vencimiento_texto)

    for bruto in layout.get("grupos", []) or []:
        grupo = _construir_grupo(bruto, declaracion, resumen)
        if grupo is not None:
            resumen.grupos.append(grupo)

    bruto_total = layout.get("total", {}) or {}
    resumen.total_monto = declaracion.monto_a_pagar
    resumen.total_glosa = str(bruto_total.get("glosa", "TOTAL A PAGAR F29 {periodo}")).format(
        periodo=_periodo_en_mayusculas(declaracion.periodo),
        periodo_codigo=declaracion.periodo.codigo,
    )
    return resumen


def _construir_grupo(bruto: dict, declaracion: DeclaracionF29, resumen: Resumen) -> GrupoResumen | None:
    grupo = GrupoResumen(titulo=str(bruto.get("titulo", "")))

    for bruto_linea in bruto.get("lineas", []) or []:
        if bruto_linea.get("separador"):
            # Un separador sólo tiene sentido entre dos líneas con contenido.
            if grupo.lineas and not grupo.lineas[-1].separador:
                grupo.lineas.append(LineaResumen(separador=True))
            continue
        linea = _construir_linea(bruto_linea, declaracion, resumen)
        if linea is not None:
            grupo.lineas.append(linea)

    while grupo.lineas and grupo.lineas[-1].separador:
        grupo.lineas.pop()

    # Un grupo que quedó sin líneas con monto no se imprime.
    if not any(not l.separador for l in grupo.lineas):
        return None

    codigo_cero = bruto.get("codigo_cero")
    nota = bruto.get("nota_si_cero")
    if nota and codigo_cero and not (declaracion.valor(str(codigo_cero), defecto=Decimal(0)) or 0):
        grupo.nota = str(nota)

    return grupo


def _construir_linea(bruto: dict, declaracion: DeclaracionF29, resumen: Resumen) -> LineaResumen | None:
    codigos = _como_lista(bruto.get("codigo"))
    suma_de = _como_lista(bruto.get("suma_de"))

    monto: Decimal | None = None
    if codigos:
        monto = declaracion.valor(*codigos)
    if monto is None and suma_de:
        monto = _sumar(declaracion, suma_de)

    if monto is None:
        return None
    if monto == 0 and not bruto.get("siempre"):
        return None

    if codigos and suma_de:
        _revisar_cuadratura(declaracion, codigos, suma_de, str(bruto.get("glosa", "")), resumen)

    signo = str(bruto.get("signo", ""))
    return LineaResumen(
        glosa=str(bruto.get("glosa", "")),
        monto=monto,
        signo=signo,
        parentesis=bool(bruto.get("parentesis", signo == "-")),
        total=bool(bruto.get("total")),
        destacar=bool(bruto.get("destacar")),
    )


def _revisar_cuadratura(
    declaracion: DeclaracionF29,
    codigos: list[str],
    suma_de: list[str],
    glosa: str,
    resumen: Resumen,
) -> None:
    """Compara el total del formulario con la suma de sus componentes."""
    oficial = declaracion.valor(*codigos)
    calculado = _sumar(declaracion, suma_de)
    if oficial is None or calculado is None or oficial == calculado:
        return
    resumen.descuadres.append(
        f"{glosa or codigos[0]}: el formulario dice {oficial:,.0f} y las líneas suman "
        f"{calculado:,.0f} (diferencia {oficial - calculado:,.0f})".replace(",", ".")
    )


def _sumar(declaracion: DeclaracionF29, codigos: list[str]) -> Decimal | None:
    valores = [declaracion.valor(c) for c in codigos]
    presentes = [v for v in valores if v is not None]
    return sum(presentes, Decimal(0)) if presentes else None


def _como_lista(valor) -> list[str]:
    if valor is None:
        return []
    if isinstance(valor, (list, tuple)):
        return [str(v) for v in valor]
    return [str(valor)]


def _periodo_en_mayusculas(periodo: Periodo) -> str:
    return periodo.etiqueta.upper()


# --------------------------------------------------------------------------- #
# Formato contable
# --------------------------------------------------------------------------- #


def monto_contable(valor: Decimal | int | float | None, *, parentesis: bool = False) -> str:
    """``23030105`` → ``23.030.105.-``; entre paréntesis cuando la línea resta."""
    if valor is None:
        return "—"
    entero = int(round(float(valor)))
    texto = f"{abs(entero):,}".replace(",", ".") + ".-"
    if entero < 0 or parentesis:
        return f"({texto})"
    return texto
