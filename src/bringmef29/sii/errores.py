"""Errores del acceso al SII."""

from __future__ import annotations


class ErrorSii(RuntimeError):
    """Error genérico al interactuar con el SII."""


class ErrorAutenticacion(ErrorSii):
    """El SII rechazó el RUT o la clave tributaria, o exige un segundo factor."""


class DeclaracionNoEncontrada(ErrorSii):
    """No hay F29 presentado para ese RUT y período."""


class RespuestaInesperada(ErrorSii):
    """El SII respondió algo que el programa no supo interpretar.

    Suele significar que el sitio cambió: revisa la captura guardada en el
    directorio de estado y ajusta los selectores o endpoints.
    """
