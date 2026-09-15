"""Revisa que todo lo que el programa necesita esté en su lugar.

Comprueba lo que se puede comprobar sin la clave de nadie: que Chromium esté,
que la configuración cargue, que la clave maestra exista, que el SII responda
desde este equipo, que el directorio de salida se pueda escribir. Lo único que
no se puede verificar aquí es el acceso a la cuenta de un contribuyente — para
eso hay que entrar de verdad, y eso lo hace ``bringmef29 traer``.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

URL_LOGIN_SII = "https://zeusr.sii.cl/AUT2000/InicioAutenticacion/IngresoRutClave.html"

BIEN, AVISO, MAL = "ok", "aviso", "mal"


@dataclass
class Chequeo:
    nombre: str
    estado: str
    detalle: str = ""
    arreglo: str = ""

    @property
    def glifo(self) -> str:
        return {BIEN: "✓", AVISO: "!", MAL: "✗"}[self.estado]


def _python() -> Chequeo:
    v = sys.version_info
    version = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) < (3, 10):
        return Chequeo("Python", MAL, version, "El programa necesita Python 3.10 o superior.")
    return Chequeo("Python", BIEN, version)


def _chromium() -> Chequeo:
    from .sii.f29_navegador import ruta_chromium

    try:
        __import__("playwright")
    except ImportError:
        return Chequeo(
            "Chromium", MAL, "Playwright no está instalado",
            "pip install playwright && playwright install chromium",
        )
    ruta = ruta_chromium()
    if ruta:
        return Chequeo("Chromium", BIEN, ruta)
    return Chequeo(
        "Chromium", AVISO, "se usará el que traiga Playwright",
        "Si falla al abrir el navegador:  playwright install chromium",
    )


def _configuracion(ruta_config: str | None) -> tuple[Chequeo, object | None]:
    from .config import ErrorConfig, cargar

    try:
        config = cargar(ruta_config)
    except ErrorConfig as exc:
        return Chequeo("Configuración", MAL, str(exc).split("\n")[0],
                       "cp config/clientes.example.yml config/clientes.yml"), None
    cuantos = len(config.clientes)
    if not cuantos:
        return Chequeo("Configuración", AVISO, f"{config.ruta_archivo} sin clientes",
                       "Agrega al menos un cliente en la sección 'clientes'."), config
    return Chequeo("Configuración", BIEN, f"{cuantos} cliente(s) en {config.ruta_archivo}"), config


def _clave_maestra() -> Chequeo:
    from .seguridad import ARCHIVO_CLAVE_MAESTRA, VAR_CLAVE_MAESTRA

    if os.environ.get(VAR_CLAVE_MAESTRA) or os.environ.get(ARCHIVO_CLAVE_MAESTRA):
        return Chequeo("Clave maestra", BIEN, "definida en el entorno")
    return Chequeo(
        "Clave maestra", AVISO, "no está definida",
        "Sólo hace falta para guardar claves cifradas:  bringmef29 clave generar-maestra",
    )


def _claves_de_clientes(config) -> Chequeo:
    from .config import ErrorConfig

    if config is None or not config.clientes:
        return Chequeo("Claves tributarias", AVISO, "sin clientes que revisar")
    con, sin = [], []
    for contribuyente in config.clientes.values():
        try:
            config.clave_sii(contribuyente)
        except (ErrorConfig, Exception):  # noqa: BLE001 - cualquier fallo cuenta como "sin clave"
            sin.append(contribuyente.alias)
        else:
            con.append(contribuyente.alias)
    if not con:
        return Chequeo(
            "Claves tributarias", MAL, f"ninguno de {len(sin)} cliente(s) tiene clave",
            "bringmef29 clave guardar <cliente>",
        )
    if sin:
        return Chequeo(
            "Claves tributarias", AVISO, f"{len(con)} con clave, sin clave: {', '.join(sin)}",
            "bringmef29 clave guardar " + sin[0],
        )
    return Chequeo("Claves tributarias", BIEN, f"{len(con)} cliente(s) con clave guardada")


def _sii_alcanzable() -> Chequeo:
    """¿Responde el SII desde este equipo? Es una página pública, no se envía nada."""
    import requests

    try:
        respuesta = requests.get(URL_LOGIN_SII, timeout=20,
                                 headers={"User-Agent": "Mozilla/5.0"})
    except requests.RequestException as exc:
        return Chequeo("SII alcanzable", MAL, str(exc)[:90],
                       "Revisa la conexión, el proxy o el firewall del equipo.")
    if respuesta.status_code != 200:
        return Chequeo("SII alcanzable", AVISO, f"HTTP {respuesta.status_code}",
                       "El SII puede estar en mantención.")
    if "rutcntr" not in respuesta.text:
        return Chequeo(
            "SII alcanzable", AVISO, "responde, pero el formulario de login cambió",
            "Revísalo con:  bringmef29 traer <cliente> --modo navegador --sin-headless",
        )
    return Chequeo("SII alcanzable", BIEN, "el formulario de login responde y calza")


def _correo(config) -> Chequeo:
    if config is None:
        return Chequeo("Correo", AVISO, "sin configuración")
    if not config.correo.configurado:
        return Chequeo("Correo", AVISO, "sin servidor ni remitente",
                       "Completa la sección 'correo' de clientes.yml.")
    if not config.correo.clave:
        return Chequeo(
            "Correo", AVISO, f"{config.correo.servidor} sin contraseña",
            "Gmail y Microsoft 365 piden una contraseña de aplicación.",
        )
    return Chequeo("Correo", BIEN, f"{config.correo.remitente} vía {config.correo.servidor}")


def _whatsapp(config) -> Chequeo:
    if config is None:
        return Chequeo("WhatsApp", AVISO, "sin configuración")
    proveedor = (config.whatsapp.proveedor or "enlace").lower()
    if proveedor == "enlace":
        return Chequeo("WhatsApp", BIEN, "enlace wa.me (no requiere cuenta de API)")
    if proveedor == "twilio" and not (config.whatsapp.twilio_sid and config.whatsapp.twilio_token):
        return Chequeo("WhatsApp", MAL, "twilio sin credenciales",
                       "Define twilio_sid y BRINGMEF29_TWILIO_TOKEN.")
    if proveedor == "meta" and not (config.whatsapp.meta_phone_number_id and config.whatsapp.meta_token):
        return Chequeo("WhatsApp", MAL, "meta sin credenciales",
                       "Define meta_phone_number_id y BRINGMEF29_META_TOKEN.")
    return Chequeo("WhatsApp", BIEN, proveedor)


def _salida(config) -> Chequeo:
    if config is None:
        return Chequeo("Directorio de salida", AVISO, "sin configuración")
    carpeta = Path(config.directorio_salida)
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
        prueba = carpeta / ".escritura"
        prueba.write_text("ok", encoding="utf-8")
        prueba.unlink()
    except OSError as exc:
        return Chequeo("Directorio de salida", MAL, f"{carpeta}: {exc}",
                       "Elige otra carpeta en 'directorio_salida'.")
    libre = shutil.disk_usage(carpeta).free // (1024 * 1024)
    return Chequeo("Directorio de salida", BIEN, f"{carpeta} ({libre} MB libres)")


def _excel() -> Chequeo:
    try:
        __import__("openpyxl")
    except ImportError:
        return Chequeo("Exportar a Excel", AVISO, "openpyxl no está instalado",
                       "pip install openpyxl")
    return Chequeo("Exportar a Excel", BIEN, "disponible")


def revisar(ruta_config: str | None = None, *, con_red: bool = True) -> list[Chequeo]:
    """Corre todos los chequeos y devuelve sus resultados, en orden."""
    chequeo_config, config = _configuracion(ruta_config)
    chequeos = [
        _python(),
        _chromium(),
        _excel(),
        chequeo_config,
        _clave_maestra(),
        _claves_de_clientes(config),
        _salida(config),
        _correo(config),
        _whatsapp(config),
    ]
    if con_red:
        chequeos.append(_sii_alcanzable())
    return chequeos
