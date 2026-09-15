"""Distingue de cuál formulario del SII proviene lo que se leyó.

En el portal del SII conviven tres F29 para un mismo período:

* la **propuesta**, que el SII pre-arma con los datos del Registro de Compras y
  Ventas;
* el **formulario guardado**, que el contribuyente llenó y dejó grabado sin
  enviar;
* la **declaración presentada**, ya enviada y con folio.

Sólo los dos últimos son del contribuyente. La propuesta no incluye lo que el
contador agrega a mano —PPM, retenciones, remanentes arrastrados, ajustes— así
que cobrarle a un cliente en base a ella es cobrarle un monto que nunca declaró.

Este módulo mira el texto, la URL y el JSON crudo y clasifica. Ante la duda
**no** afirma que sea del contribuyente: prefiere ``desconocida`` y que el flujo
se detenga a que un aviso salga con la cifra equivocada.
"""

from __future__ import annotations

import re
from typing import Any, Iterator

from ..modelos import (
    GUARDADA,
    PRESENTADA,
    PROCEDENCIA_DESCONOCIDA,
    PROPUESTA,
)

# Frases del SII que delatan que lo que está en pantalla es la propuesta.
SENALES_PROPUESTA = (
    "propuesta de f29",
    "propuesta de declaracion",
    "propuesta f29",
    "f29 propuesto",
    "declaracion propuesta",
    "propuesta del sii",
    "aceptar propuesta",
    "modificar propuesta",
    "propuesta generada",
    "registro de compras y ventas",
)

# Frases del formulario que el contribuyente guardó sin enviar.
SENALES_GUARDADA = (
    "declaracion guardada",
    "formulario guardado",
    "guardado sin enviar",
    "continuar declaracion",
    "recuperar declaracion",
    "borrador guardado",
    "declaracion en proceso",
)

# Frases de la declaración ya enviada.
SENALES_PRESENTADA = (
    "declaracion presentada",
    "comprobante de declaracion",
    "declaracion vigente",
    "fecha de presentacion",
    "folio de la declaracion",
)

# Llaves del JSON del SII que marcan la propuesta.
_LLAVES_PROPUESTA = ("espropuesta", "propuesta", "tipopropuesta", "origendatos")
_LLAVES_GUARDADA = ("esborrador", "guardada", "esguardada")
_VALORES_PROPUESTA = ("propuesta", "rcv", "registro de compras")
_VALORES_GUARDADA = ("guardada", "guardado", "borrador", "en proceso", "pendiente")
_VALORES_PRESENTADA = ("presentada", "vigente", "recibida", "aceptada")

_ACENTOS = str.maketrans("áéíóúÁÉÍÓÚüÜñÑ", "aeiouAEIOUuUnN")


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos y con espacios colapsados, para comparar frases."""
    return re.sub(r"\s+", " ", (texto or "").translate(_ACENTOS).lower()).strip()


def clasificar(
    *,
    texto: str = "",
    url: str = "",
    crudo: Any = None,
    folio: str = "",
    estado: str = "",
) -> str:
    """Devuelve ``propuesta``, ``guardada``, ``presentada`` o ``desconocida``.

    El orden de evaluación no es arbitrario: la propuesta se busca primero y gana
    sobre cualquier otra señal, porque confundirla con la declaración del
    contribuyente es el error caro.
    """
    plano = normalizar(f"{texto} {url} {estado}")

    if _hay_senal(plano, SENALES_PROPUESTA) or _json_dice_propuesta(crudo):
        return PROPUESTA

    estado_plano = normalizar(estado)
    if any(v in estado_plano for v in _VALORES_GUARDADA):
        return GUARDADA
    if _hay_senal(plano, SENALES_GUARDADA) or _json_dice_guardada(crudo):
        return GUARDADA

    if any(v in estado_plano for v in _VALORES_PRESENTADA):
        return PRESENTADA
    if folio and _hay_senal(plano, SENALES_PRESENTADA):
        return PRESENTADA
    # Un folio es lo que el SII entrega al recibir una declaración: sin ninguna
    # señal en contra, un folio real basta para darla por presentada.
    if folio and str(folio).strip().isdigit():
        return PRESENTADA

    return PROCEDENCIA_DESCONOCIDA


def _hay_senal(texto_plano: str, senales: tuple[str, ...]) -> bool:
    return any(senal in texto_plano for senal in senales)


def _recorrer(nodo: Any) -> Iterator[Any]:
    yield nodo
    if isinstance(nodo, dict):
        for valor in nodo.values():
            yield from _recorrer(valor)
    elif isinstance(nodo, list):
        for item in nodo:
            yield from _recorrer(item)


def _json_dice_propuesta(crudo: Any) -> bool:
    return _json_marca(crudo, _LLAVES_PROPUESTA, _VALORES_PROPUESTA)


def _json_dice_guardada(crudo: Any) -> bool:
    return _json_marca(crudo, _LLAVES_GUARDADA, _VALORES_GUARDADA)


def _json_marca(crudo: Any, llaves: tuple[str, ...], valores: tuple[str, ...]) -> bool:
    if crudo is None:
        return False
    for nodo in _recorrer(crudo):
        if not isinstance(nodo, dict):
            continue
        for llave, valor in nodo.items():
            clave = normalizar(str(llave)).replace(" ", "")
            if clave not in llaves:
                continue
            if valor is True:
                return True
            if isinstance(valor, str) and any(v in normalizar(valor) for v in valores):
                return True
    return False
