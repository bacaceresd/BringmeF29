"""Canales de envío del aviso: correo electrónico y WhatsApp."""

from .correo import EnviadorCorreo, ErrorEnvioCorreo
from .whatsapp import EnviadorWhatsApp, ErrorEnvioWhatsApp, enlace_wa_me

__all__ = [
    "EnviadorCorreo",
    "ErrorEnvioCorreo",
    "EnviadorWhatsApp",
    "ErrorEnvioWhatsApp",
    "enlace_wa_me",
]
