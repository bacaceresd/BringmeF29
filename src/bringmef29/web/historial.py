"""Registro de las consultas hechas desde la aplicación local.

Una consulta se identifica por el contribuyente, el período y la *huella* de
los códigos que trajo el SII. Volver a traer exactamente lo mismo reemplaza la
entrada y la deja arriba; si cambió aunque sea un código, es otra consulta y se
suma a la lista sin pisar la anterior. Por eso cada una guarda sus documentos
en su propia carpeta: dos versiones del mismo período no se sobreescriben.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from ..config import Config
from ..modelos import DeclaracionF29

ARCHIVO = "consultas.json"
MAXIMO = 100

# Sólo referencias con esta forma se aceptan desde la URL: <rut>-<período>-<huella>.
_REFERENCIA = re.compile(r"^[0-9]{1,9}[0-9kK]-[0-9]{6}-[0-9a-f]{8}$")


def huella(declaracion: DeclaracionF29) -> str:
    """Resumen corto del contenido: cambia si cambia cualquier código o valor."""
    partes = sorted(
        f"{linea.codigo_normalizado}={linea.valor}" for linea in declaracion.lineas
    )
    return hashlib.sha256("|".join(partes).encode("utf-8")).hexdigest()[:8]


def referencia(declaracion: DeclaracionF29) -> str:
    return (f"{declaracion.rut.sin_formato}-{declaracion.periodo.codigo}-"
            f"{huella(declaracion)}")


def referencia_valida(ref: str) -> bool:
    return bool(_REFERENCIA.match(ref or ""))


def carpeta(config: Config, declaracion: DeclaracionF29) -> Path:
    """Dónde viven los documentos de esta consulta en particular."""
    destino = (config.directorio_salida / declaracion.rut.sin_formato
               / declaracion.periodo.codigo / huella(declaracion))
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def _ruta_archivo(config: Config) -> Path:
    return config.directorio_salida / ARCHIVO


def listar(config: Config) -> list[dict]:
    """Las consultas guardadas, de la más reciente a la más antigua."""
    archivo = _ruta_archivo(config)
    if not archivo.exists():
        return []
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return datos if isinstance(datos, list) else []


def buscar(config: Config, ref: str) -> dict | None:
    if not referencia_valida(ref):
        return None
    for entrada in listar(config):
        if entrada.get("ref") == ref:
            return entrada
    return None


def registrar(config: Config, declaracion: DeclaracionF29, rutas: dict) -> dict:
    """Anota la consulta arriba de todo y devuelve la entrada."""
    ref = referencia(declaracion)
    entrada = {
        "ref": ref,
        "rut": declaracion.rut.formateado,
        "rut_plano": declaracion.rut.sin_formato,
        "razon": declaracion.razon_social,
        "periodo": declaracion.periodo.codigo,
        "etiqueta": declaracion.periodo.etiqueta,
        "monto": str(declaracion.monto_a_pagar),
        "cuando": datetime.now().isoformat(timespec="seconds"),
        "carpeta": str(carpeta(config, declaracion)),
        "rutas": {k: v for k, v in rutas.items() if v},
    }
    # Misma consulta exacta: se reemplaza y sube. Distinta: convive con la otra.
    consultas = [c for c in listar(config) if c.get("ref") != ref]
    consultas.insert(0, entrada)
    guardar(config, consultas[:MAXIMO])
    return entrada


def guardar(config: Config, consultas: list[dict]) -> None:
    config.directorio_salida.mkdir(parents=True, exist_ok=True)
    _ruta_archivo(config).write_text(
        json.dumps(consultas, indent=2, ensure_ascii=False), encoding="utf-8"
    )
