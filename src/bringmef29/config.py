"""Carga de configuración: estudio contable, clientes, correo, WhatsApp y pago."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .modelos import Contribuyente, DatosPago
from .rut import Rut
from .seguridad import AlmacenClaves

RUTA_CONFIG_POR_DEFECTO = Path("config/clientes.yml")
RUTA_ALMACEN_POR_DEFECTO = Path(".secretos/claves.json")
RUTA_CATALOGO = Path(__file__).parent / "recursos" / "codigos_f29.yml"

_NO_ALFANUM = re.compile(r"[^A-Z0-9]")


class ErrorConfig(RuntimeError):
    """La configuración está incompleta o mal formada."""


# --------------------------------------------------------------------------- #
# Secciones
# --------------------------------------------------------------------------- #


@dataclass
class Estudio:
    """Quién emite el aviso: el contador o estudio contable."""

    nombre: str = ""
    rut: str = ""
    correo: str = ""
    telefono: str = ""
    sitio_web: str = ""
    logo: str = ""


@dataclass
class ConfigCorreo:
    servidor: str = ""
    puerto: int = 587
    usuario: str = ""
    clave: str = field(default="", repr=False)
    remitente: str = ""
    nombre_remitente: str = ""
    seguridad: str = "starttls"      # "starttls" | "ssl" | "ninguna"
    responder_a: str = ""
    asunto: str = "F29 {periodo} — {razon_social}"

    @property
    def configurado(self) -> bool:
        return bool(self.servidor and self.remitente)


@dataclass
class ConfigWhatsApp:
    proveedor: str = "enlace"        # "enlace" | "twilio" | "meta"
    # Twilio
    twilio_sid: str = ""
    twilio_token: str = field(default="", repr=False)
    twilio_desde: str = ""           # p.ej. "whatsapp:+14155238886"
    # Meta WhatsApp Cloud API
    meta_phone_number_id: str = ""
    meta_token: str = field(default="", repr=False)
    meta_plantilla: str = ""
    meta_idioma: str = "es"
    # Común
    url_publica_base: str = ""       # base https:// donde se publican los adjuntos
    plantilla_mensaje: str = ""


@dataclass
class ConfigSii:
    # Cuál de los formularios del SII se lee. "guardada" es el F29 que el
    # contribuyente llenó y grabó, no la propuesta que arma el SII.
    fuente: str = "guardada"         # "guardada" | "presentada" | "auto"
    modo: str = "auto"               # "auto" | "api" | "navegador"
    headless: bool = True
    timeout_ms: int = 45000
    ruta_chromium: str = ""
    directorio_estado: str = ".estado_sii"
    guardar_capturas: bool = True


@dataclass
class Config:
    estudio: Estudio = field(default_factory=Estudio)
    pago: DatosPago = field(default_factory=DatosPago)
    correo: ConfigCorreo = field(default_factory=ConfigCorreo)
    whatsapp: ConfigWhatsApp = field(default_factory=ConfigWhatsApp)
    sii: ConfigSii = field(default_factory=ConfigSii)
    clientes: dict[str, Contribuyente] = field(default_factory=dict)
    directorio_salida: Path = Path("salida")
    ruta_almacen_claves: Path = RUTA_ALMACEN_POR_DEFECTO
    ruta_archivo: Path | None = None

    # -- clientes -----------------------------------------------------------
    def cliente(self, referencia: str) -> Contribuyente:
        """Busca un cliente por alias o por RUT (con o sin formato)."""
        clave = referencia.strip().lower()
        if clave in self.clientes:
            return self.clientes[clave]
        try:
            rut = Rut.parsear(referencia)
        except Exception:  # noqa: BLE001 - no era un RUT, seguimos al error final
            pass
        else:
            for contribuyente in self.clientes.values():
                if contribuyente.rut == rut:
                    return contribuyente
        disponibles = ", ".join(sorted(self.clientes)) or "(ninguno)"
        raise ErrorConfig(f"No hay un cliente '{referencia}' configurado. Disponibles: {disponibles}")

    def clave_sii(self, contribuyente: Contribuyente) -> str:
        """Resuelve la clave tributaria: explícita > variable de entorno > almacén cifrado."""
        if contribuyente.clave_sii:
            return contribuyente.clave_sii
        sufijo = _NO_ALFANUM.sub("_", contribuyente.alias.upper())
        for variable in (
            f"BRINGMEF29_CLAVE_{sufijo}",
            f"SII_CLAVE_{sufijo}",
            "BRINGMEF29_CLAVE_SII",
        ):
            if valor := os.environ.get(variable):
                return valor
        almacenada = AlmacenClaves(self.ruta_almacen_claves).obtener(contribuyente.rut.con_guion)
        if almacenada:
            return almacenada
        raise ErrorConfig(
            f"No hay clave tributaria para '{contribuyente.alias}'. Guárdala cifrada con:\n"
            f"  bringmef29 clave guardar {contribuyente.alias}\n"
            f"o expórtala en la variable BRINGMEF29_CLAVE_{sufijo}."
        )


# --------------------------------------------------------------------------- #
# Carga
# --------------------------------------------------------------------------- #


def cargar(ruta: str | Path | None = None) -> Config:
    """Lee el YAML de configuración, resolviendo secretos desde el entorno."""
    _cargar_dotenv()
    archivo = Path(ruta) if ruta else Path(os.environ.get("BRINGMEF29_CONFIG", RUTA_CONFIG_POR_DEFECTO))
    if not archivo.exists():
        raise ErrorConfig(
            f"No existe el archivo de configuración {archivo}. "
            "Cópialo desde config/clientes.example.yml y complétalo."
        )
    datos = yaml.safe_load(archivo.read_text(encoding="utf-8")) or {}
    return desde_dict(datos, ruta_archivo=archivo)


def desde_dict(datos: dict, ruta_archivo: Path | None = None) -> Config:
    """Construye la configuración desde un diccionario ya parseado."""
    config = Config(ruta_archivo=ruta_archivo)

    config.estudio = Estudio(**_campos(Estudio, datos.get("estudio", {})))
    config.pago = DatosPago(**_campos(DatosPago, datos.get("pago", {})))

    correo = _campos(ConfigCorreo, datos.get("correo", {}))
    correo.setdefault("clave", "")
    correo["clave"] = _resolver_secreto(correo["clave"], "BRINGMEF29_SMTP_CLAVE", "SMTP_PASSWORD")
    config.correo = ConfigCorreo(**correo)

    whatsapp = _campos(ConfigWhatsApp, datos.get("whatsapp", {}))
    whatsapp["twilio_token"] = _resolver_secreto(
        whatsapp.get("twilio_token", ""), "BRINGMEF29_TWILIO_TOKEN", "TWILIO_AUTH_TOKEN"
    )
    whatsapp["meta_token"] = _resolver_secreto(
        whatsapp.get("meta_token", ""), "BRINGMEF29_META_TOKEN", "META_WHATSAPP_TOKEN"
    )
    config.whatsapp = ConfigWhatsApp(**whatsapp)

    sii = _campos(ConfigSii, datos.get("sii", {}))
    sii.setdefault("ruta_chromium", os.environ.get("BRINGMEF29_CHROMIUM", ""))
    config.sii = ConfigSii(**sii)

    if salida := datos.get("directorio_salida"):
        config.directorio_salida = Path(str(salida))
    if almacen := datos.get("ruta_almacen_claves"):
        config.ruta_almacen_claves = Path(str(almacen))

    for bruto in datos.get("clientes", []) or []:
        contribuyente = _cliente_desde_dict(bruto)
        config.clientes[contribuyente.alias.lower()] = contribuyente

    return config


def _cliente_desde_dict(bruto: dict) -> Contribuyente:
    if "rut" not in bruto:
        raise ErrorConfig(f"Cliente sin RUT en la configuración: {bruto!r}")
    rut = Rut.parsear(bruto["rut"])
    alias = str(bruto.get("alias") or rut.sin_formato).strip()
    clave = bruto.get("clave_sii") or ""
    if clave:
        clave = _resolver_secreto(clave, "")
    return Contribuyente(
        alias=alias,
        rut=rut,
        razon_social=str(bruto.get("razon_social", "")),
        correo=_como_lista(bruto.get("correo")),
        correo_copia=_como_lista(bruto.get("correo_copia")),
        whatsapp=str(bruto.get("whatsapp", "")),
        nombre_contacto=str(bruto.get("nombre_contacto", "")),
        clave_sii=clave or None,
    )


def cargar_catalogo(ruta: str | Path | None = None) -> dict:
    """Catálogo de glosas y códigos del F29."""
    archivo = Path(ruta) if ruta else RUTA_CATALOGO
    return yaml.safe_load(archivo.read_text(encoding="utf-8")) or {}


# --------------------------------------------------------------------------- #
# Ayudantes
# --------------------------------------------------------------------------- #


def _campos(clase, bruto: dict | None) -> dict:
    """Filtra las llaves del YAML que no son campos de la dataclass."""
    if not bruto:
        return {}
    validos = {f.name for f in clase.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    desconocidos = set(bruto) - validos
    if desconocidos:
        raise ErrorConfig(
            f"Claves desconocidas en la sección '{clase.__name__}': {', '.join(sorted(desconocidos))}"
        )
    return dict(bruto)


def _como_lista(valor) -> list[str]:
    if not valor:
        return []
    if isinstance(valor, str):
        return [parte.strip() for parte in valor.split(",") if parte.strip()]
    return [str(item).strip() for item in valor if str(item).strip()]


def _resolver_secreto(valor: str, *variables_alternativas: str) -> str:
    """Resuelve ``env:NOMBRE`` o ``${NOMBRE}`` contra el entorno; si no, usa alternativas."""
    texto = str(valor or "")
    if texto.startswith("env:"):
        nombre = texto[4:].strip()
        resuelto = os.environ.get(nombre, "")
        if not resuelto:
            raise ErrorConfig(f"La configuración referencia env:{nombre} pero la variable no está definida.")
        return resuelto
    if m := re.fullmatch(r"\$\{(\w+)\}", texto):
        return os.environ.get(m.group(1), "")
    if texto:
        return texto
    for variable in variables_alternativas:
        if variable and (resuelto := os.environ.get(variable)):
            return resuelto
    return ""


def _cargar_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dependencia opcional en tiempo de ejecución
        return
    load_dotenv(override=False)
