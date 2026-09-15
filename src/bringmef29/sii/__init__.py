"""Acceso al SII: autenticación y consulta del Formulario 29."""

from .errores import (
    ErrorSii,
    ErrorAutenticacion,
    DeclaracionNoEncontrada,
    DeclaracionGuardadaNoEncontrada,
    DeclaracionEsPropuesta,
    RespuestaInesperada,
)

__all__ = [
    "ErrorSii",
    "ErrorAutenticacion",
    "DeclaracionNoEncontrada",
    "DeclaracionGuardadaNoEncontrada",
    "DeclaracionEsPropuesta",
    "RespuestaInesperada",
]
