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


class DeclaracionEsPropuesta(ErrorSii):
    """Lo que se leyó es la propuesta del SII, no la declaración del contribuyente.

    El SII pre-arma un F29 con los datos del Registro de Compras y Ventas. Esa
    propuesta no refleja lo que el contador efectivamente declaró (PPM, retenciones,
    remanentes, ajustes), así que cobrarle al cliente en base a ella sería un error.
    """


class DeclaracionGuardadaNoEncontrada(DeclaracionNoEncontrada):
    """No hay un F29 guardado por el contribuyente para ese período.

    Puede que todavía no se haya llenado, o que se haya enviado y ahora esté como
    declaración presentada.
    """
