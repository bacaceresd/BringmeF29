"""Acceso al SII: autenticación y consulta del Formulario 29."""

from .errores import (
    ErrorSii,
    ErrorAutenticacion,
    DeclaracionNoEncontrada,
    RespuestaInesperada,
)

__all__ = [
    "ErrorSii",
    "ErrorAutenticacion",
    "DeclaracionNoEncontrada",
    "RespuestaInesperada",
]
