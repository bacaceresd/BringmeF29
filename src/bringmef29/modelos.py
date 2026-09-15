"""Modelos de dominio: período tributario, declaración F29 y aviso de pago."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from .rut import Rut

MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


class PeriodoInvalido(ValueError):
    """El período tributario no se pudo interpretar."""


@dataclass(frozen=True, order=True)
class Periodo:
    """Período tributario mensual del F29 (el mes que se declara, no el de pago)."""

    anio: int
    mes: int

    def __post_init__(self) -> None:
        if not 1 <= self.mes <= 12:
            raise PeriodoInvalido(f"Mes fuera de rango: {self.mes}")
        if not 2000 <= self.anio <= 2100:
            raise PeriodoInvalido(f"Año fuera de rango: {self.anio}")

    @classmethod
    def parsear(cls, valor: str) -> "Periodo":
        """Acepta ``2025-08``, ``2025/8``, ``082025`` o ``202508``."""
        texto = str(valor).strip()
        if m := re.fullmatch(r"(\d{4})[-/](\d{1,2})", texto):
            return cls(int(m.group(1)), int(m.group(2)))
        if m := re.fullmatch(r"(\d{1,2})[-/](\d{4})", texto):
            return cls(int(m.group(2)), int(m.group(1)))
        if m := re.fullmatch(r"(\d{4})(\d{2})", texto):
            return cls(int(m.group(1)), int(m.group(2)))
        raise PeriodoInvalido(f"No se pudo interpretar el período: {valor!r} (usa AAAA-MM)")

    @classmethod
    def anterior_a_hoy(cls, hoy: date | None = None) -> "Periodo":
        """El período que normalmente se está declarando: el mes calendario anterior."""
        hoy = hoy or date.today()
        return cls(hoy.year - 1, 12) if hoy.month == 1 else cls(hoy.year, hoy.month - 1)

    @property
    def etiqueta(self) -> str:
        return f"{MESES_ES[self.mes - 1].capitalize()} {self.anio}"

    @property
    def codigo(self) -> str:
        return f"{self.anio}{self.mes:02d}"

    @property
    def ultimo_dia(self) -> date:
        return date(self.anio, self.mes, calendar.monthrange(self.anio, self.mes)[1])

    def vencimiento_legal(
        self,
        *,
        facturador_electronico: bool = True,
        feriados_extra: set[date] | None = None,
    ) -> date:
        """Vencimiento del F29: día 20 del mes siguiente para facturadores
        electrónicos (día 12 en papel), corrido al día hábil siguiente cuando cae
        sábado, domingo o feriado.

        Es una referencia para el aviso, no una resolución del SII: las prórrogas
        puntuales y los feriados regionales se agregan con ``feriados_extra``.
        """
        from .calendario import vencimiento_f29

        return vencimiento_f29(
            self.anio,
            self.mes,
            facturador_electronico=facturador_electronico,
            feriados_extra=feriados_extra,
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.anio}-{self.mes:02d}"


@dataclass
class LineaCodigo:
    """Un código del formulario 29 con su valor declarado."""

    codigo: str
    valor: Decimal
    glosa: str = ""

    @property
    def codigo_normalizado(self) -> str:
        """Código sin ceros a la izquierda: el SII mezcla ``077`` y ``77``."""
        return self.codigo.lstrip("0") or "0"


# Procedencia del formulario dentro del SII. La distinción importa: en el portal
# conviven la propuesta que arma el SII desde el Registro de Compras y Ventas y el
# formulario que el contribuyente llenó él mismo. Sólo el segundo sirve para
# cobrarle al cliente.
PRESENTADA = "presentada"      # enviada al SII, con folio
GUARDADA = "guardada"          # el contribuyente la llenó y guardó, sin enviar
PROPUESTA = "propuesta"        # borrador que el SII pre-arma desde el RCV
PROCEDENCIA_DESCONOCIDA = "desconocida"

PROCEDENCIAS_DEL_CONTRIBUYENTE = (GUARDADA, PRESENTADA)


@dataclass
class DeclaracionF29:
    """Una declaración F29 leída del SII.

    ``procedencia`` dice de cuál de los tres formularios del portal proviene.
    Es lo primero que hay que mirar antes de cobrarle nada a un cliente: la
    propuesta del SII no es la declaración del contribuyente.
    """

    rut: Rut
    periodo: Periodo
    folio: str = ""
    estado: str = ""
    fecha_presentacion: datetime | None = None
    razon_social: str = ""
    lineas: list[LineaCodigo] = field(default_factory=list)
    via: str = ""                                  # "api", "navegador" o "archivo"
    procedencia: str = PROCEDENCIA_DESCONOCIDA
    url_comprobante: str = ""
    crudo: dict = field(default_factory=dict, repr=False)

    # -- procedencia --------------------------------------------------------
    @property
    def es_propuesta_del_sii(self) -> bool:
        return self.procedencia == PROPUESTA

    @property
    def es_del_contribuyente(self) -> bool:
        """True sólo si el formulario lo llenó el contribuyente, no el SII."""
        return self.procedencia in PROCEDENCIAS_DEL_CONTRIBUYENTE

    @property
    def procedencia_glosa(self) -> str:
        return {
            PRESENTADA: "Declaración presentada al SII",
            GUARDADA: "Declaración guardada por el contribuyente (sin enviar)",
            PROPUESTA: "Propuesta del SII (no es la declaración del contribuyente)",
        }.get(self.procedencia, "Procedencia no determinada")

    # -- acceso a códigos ---------------------------------------------------
    def valor(self, *codigos: str, defecto: Decimal | None = None) -> Decimal | None:
        """Devuelve el primer código presente de la lista, o ``defecto``."""
        indice = {linea.codigo_normalizado: linea.valor for linea in self.lineas}
        for codigo in codigos:
            clave = str(codigo).lstrip("0") or "0"
            if clave in indice:
                return indice[clave]
        return defecto

    @property
    def total_debitos(self) -> Decimal | None:
        return self.valor("538")

    @property
    def total_creditos(self) -> Decimal | None:
        return self.valor("537")

    @property
    def remanente_periodo_siguiente(self) -> Decimal | None:
        return self.valor("077")

    @property
    def ppm(self) -> Decimal | None:
        return self.valor("062")

    @property
    def impuesto_determinado(self) -> Decimal | None:
        return self.valor("547", "595")

    @property
    def reajuste(self) -> Decimal:
        return self.valor("092", defecto=Decimal(0)) or Decimal(0)

    @property
    def multas_intereses(self) -> Decimal:
        return self.valor("093", defecto=Decimal(0)) or Decimal(0)

    @property
    def monto_a_pagar(self) -> Decimal:
        """Monto que el contribuyente debe enterar en arcas fiscales.

        Prioriza el total con recargo (094) cuando la declaración se presentó
        fuera de plazo; si no, usa el total dentro de plazo (091) y, como último
        recurso, el impuesto determinado (547/595).
        """
        con_recargo = self.valor("094", defecto=Decimal(0)) or Decimal(0)
        if con_recargo > 0:
            return con_recargo
        dentro_de_plazo = self.valor("091", defecto=Decimal(0)) or Decimal(0)
        if dentro_de_plazo > 0:
            return dentro_de_plazo
        determinado = self.impuesto_determinado or Decimal(0)
        return determinado if determinado > 0 else Decimal(0)

    @property
    def sin_movimiento(self) -> bool:
        """Declaración sin impuestos ni créditos relevantes."""
        return all((linea.valor or 0) == 0 for linea in self.lineas)

    @property
    def hay_que_pagar(self) -> bool:
        return self.monto_a_pagar > 0


@dataclass
class DatosPago:
    """Instrucciones de pago que se le muestran al contribuyente."""

    modo: str = "transferencia"      # "transferencia" | "sii" | "ambos"
    titular: str = ""
    rut_titular: str = ""
    banco: str = ""
    tipo_cuenta: str = ""
    numero_cuenta: str = ""
    correo_confirmacion: str = ""
    url_pago_sii: str = "https://www.sii.cl/servicios_online/1044-.html"
    nota: str = ""


@dataclass
class Contribuyente:
    """Cliente del estudio contable."""

    alias: str
    rut: Rut
    razon_social: str = ""
    correo: list[str] = field(default_factory=list)
    correo_copia: list[str] = field(default_factory=list)
    whatsapp: str = ""
    nombre_contacto: str = ""
    # Define el plazo del F29: día 20 del mes siguiente en vez del día 12.
    facturador_electronico: bool = True
    clave_sii: str | None = field(default=None, repr=False)


@dataclass
class AvisoPago:
    """Resultado del flujo: los documentos generados y el detalle enviado."""

    declaracion: DeclaracionF29
    contribuyente: Contribuyente
    pdf: str = ""
    imagen: str = ""
    captura_sii: str = ""
    comprobante_sii: str = ""
    formulario_pdf: str = ""
    formulario_completo_pdf: str = ""
    formulario_excel: str = ""
    enviado_correo: bool = False
    enviado_whatsapp: bool = False
    enlace_whatsapp: str = ""
    incidencias: list[str] = field(default_factory=list)
