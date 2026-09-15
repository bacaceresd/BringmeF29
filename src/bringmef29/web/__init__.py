"""La aplicación local: una pantalla por URL."""

from .servidor import ErrorWeb, _Manejador, consultar, servir

__all__ = ["ErrorWeb", "_Manejador", "consultar", "servir"]
