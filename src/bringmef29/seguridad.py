"""Manejo de credenciales tributarias: cifrado en reposo y redacción en logs.

La clave tributaria de un contribuyente da acceso total a su situación en el SII,
así que nunca se guarda en texto plano ni se escribe a los logs. El almacén cifra
con Fernet (AES-128-CBC + HMAC) usando una clave maestra que vive fuera del
repositorio, en la variable de entorno ``BRINGMEF29_MASTER_KEY`` o en un archivo
de clave con permisos 0600.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

VAR_CLAVE_MAESTRA = "BRINGMEF29_MASTER_KEY"
ARCHIVO_CLAVE_MAESTRA = "BRINGMEF29_MASTER_KEY_FILE"

_log = logging.getLogger(__name__)


class ErrorSeguridad(RuntimeError):
    """Problema al cifrar, descifrar o localizar la clave maestra."""


# --------------------------------------------------------------------------- #
# Redacción de logs
# --------------------------------------------------------------------------- #

# Patrones de valores que jamás deben aparecer en un log o en un traceback.
_PATRONES_SENSIBLES = [
    re.compile(
        r"(?i)\b(clave|password|passwd|pass|pwd|token|secret|authorization)\b"
        r"\s*[:=]\s*(?:bearer|basic)?\s*\S+"
    ),
    re.compile(r"(?i)\"(clave|password|token|secret)\"\s*:\s*\"[^\"]*\""),
]


class FiltroRedaccion(logging.Filter):
    """Reemplaza credenciales en los mensajes de log por ``***``.

    Es una red de seguridad, no una licencia para loguear secretos: el código
    nunca debe pasarlos a un logger en primer lugar.
    """

    def __init__(self, valores_literales: tuple[str, ...] = ()) -> None:
        super().__init__()
        self._literales = tuple(v for v in valores_literales if v)

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            mensaje = record.getMessage()
        except Exception:  # pragma: no cover - formateo roto aguas arriba
            return True
        limpio = redactar(mensaje, self._literales)
        if limpio != mensaje:
            record.msg = limpio
            record.args = ()
        return True


def redactar(texto: str, literales: tuple[str, ...] = ()) -> str:
    """Devuelve ``texto`` con credenciales enmascaradas."""
    resultado = texto
    for literal in literales:
        if literal and literal in resultado:
            resultado = resultado.replace(literal, "***")
    for patron in _PATRONES_SENSIBLES:
        resultado = patron.sub(lambda m: _enmascarar_par(m.group(0)), resultado)
    return resultado


def _enmascarar_par(fragmento: str) -> str:
    for separador in (":", "="):
        if separador in fragmento:
            clave, _, _ = fragmento.partition(separador)
            return f"{clave}{separador} ***"
    return "***"


# --------------------------------------------------------------------------- #
# Almacén cifrado
# --------------------------------------------------------------------------- #


def generar_clave_maestra() -> str:
    """Genera una clave maestra nueva en base64 urlsafe, lista para el entorno."""
    return Fernet.generate_key().decode("ascii")


def _cargar_clave_maestra() -> bytes:
    bruta = os.environ.get(VAR_CLAVE_MAESTRA)
    if not bruta:
        ruta = os.environ.get(ARCHIVO_CLAVE_MAESTRA)
        if ruta:
            archivo = Path(ruta).expanduser()
            if not archivo.exists():
                raise ErrorSeguridad(f"No existe el archivo de clave maestra: {archivo}")
            _exigir_permisos_restringidos(archivo)
            bruta = archivo.read_text(encoding="utf-8").strip()
    if not bruta:
        raise ErrorSeguridad(
            f"Falta la clave maestra. Define {VAR_CLAVE_MAESTRA} (o {ARCHIVO_CLAVE_MAESTRA}). "
            "Puedes generar una con: bringmef29 clave generar-maestra"
        )
    try:
        material = bruta.encode("ascii")
        if len(base64.urlsafe_b64decode(material)) != 32:
            raise ValueError
    except Exception as exc:  # noqa: BLE001
        raise ErrorSeguridad(
            "La clave maestra no es una clave Fernet válida (32 bytes en base64 urlsafe)."
        ) from exc
    return material


def _exigir_permisos_restringidos(archivo: Path) -> None:
    modo = stat.S_IMODE(archivo.stat().st_mode)
    if modo & 0o077:
        raise ErrorSeguridad(
            f"El archivo de clave maestra {archivo} es legible por otros usuarios "
            f"(permisos {modo:o}). Corrige con: chmod 600 {archivo}"
        )


def cifrar(texto_plano: str) -> str:
    """Cifra un secreto y lo devuelve como texto transportable en YAML."""
    return Fernet(_cargar_clave_maestra()).encrypt(texto_plano.encode("utf-8")).decode("ascii")


def descifrar(texto_cifrado: str) -> str:
    """Descifra un secreto producido por :func:`cifrar`."""
    try:
        return Fernet(_cargar_clave_maestra()).decrypt(texto_cifrado.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ErrorSeguridad(
            "No se pudo descifrar el secreto: la clave maestra no corresponde "
            "o el valor almacenado está corrupto."
        ) from exc


class AlmacenClaves:
    """Bóveda de claves tributarias en un archivo JSON cifrado por entrada.

    El archivo se crea con permisos 0600. La estructura es
    ``{"<rut-con-guion>": {"clave": "<token fernet>", "nota": "..."}}``.
    """

    def __init__(self, ruta: Path) -> None:
        self.ruta = Path(ruta).expanduser()

    def _leer(self) -> dict[str, dict[str, str]]:
        if not self.ruta.exists():
            return {}
        _exigir_permisos_restringidos(self.ruta)
        contenido = self.ruta.read_text(encoding="utf-8").strip()
        return json.loads(contenido) if contenido else {}

    def _escribir(self, datos: dict[str, dict[str, str]]) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        # Se crea con 0600 antes de escribir para no exponer el contenido ni un instante.
        descriptor = os.open(self.ruta, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as archivo:
            json.dump(datos, archivo, indent=2, ensure_ascii=False, sort_keys=True)
        os.chmod(self.ruta, 0o600)

    def guardar(self, rut: str, clave: str, nota: str = "") -> None:
        datos = self._leer()
        entrada = {"clave": cifrar(clave)}
        if nota:
            entrada["nota"] = nota
        datos[rut] = entrada
        self._escribir(datos)
        _log.info("Clave tributaria almacenada cifrada para %s", rut)

    def obtener(self, rut: str) -> str | None:
        entrada = self._leer().get(rut)
        if not entrada:
            return None
        return descifrar(entrada["clave"])

    def eliminar(self, rut: str) -> bool:
        datos = self._leer()
        if rut not in datos:
            return False
        del datos[rut]
        self._escribir(datos)
        return True

    def ruts(self) -> list[str]:
        return sorted(self._leer())
