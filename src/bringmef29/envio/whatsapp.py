"""Envío del aviso por WhatsApp.

Tres proveedores, según cuánta infraestructura tengas montada:

``enlace``
    No envía nada por sí solo: arma un enlace ``wa.me`` con el mensaje ya
    escrito, listo para abrir y apretar enviar desde tu teléfono o WhatsApp Web.
    Es el modo por defecto porque no requiere cuenta de API ni aprobación de
    plantillas, y sirve desde el primer día.

``twilio``
    WhatsApp Business a través de Twilio. Envía solo, y adjunta la imagen o el
    PDF si le das una URL pública (``url_publica_base``).

``meta``
    WhatsApp Cloud API de Meta, directo. Igual que Twilio en capacidades.

Los dos últimos exigen que el número esté habilitado como WhatsApp Business y
respetan la ventana de 24 horas de Meta: fuera de ella solo se puede iniciar
conversación con una plantilla aprobada (``meta_plantilla``).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urljoin

import requests

from ..config import Config, ConfigWhatsApp
from ..calendario import fecha_con_dia_semana
from ..documentos.formato import pesos
from ..modelos import Contribuyente, DeclaracionF29

_log = logging.getLogger(__name__)

URL_META = "https://graph.facebook.com/v21.0"
URL_TWILIO = "https://api.twilio.com/2010-04-01"

_NO_DIGITOS = re.compile(r"\D")


class ErrorEnvioWhatsApp(RuntimeError):
    """No se pudo enviar el mensaje de WhatsApp."""


@dataclass
class ResultadoWhatsApp:
    enviado: bool
    enlace: str = ""
    identificador: str = ""
    detalle: str = ""


def normalizar_numero(numero: str, *, pais_por_defecto: str = "56") -> str:
    """Devuelve el número en formato E.164 sin ``+`` (lo que piden las APIs).

    Acepta ``+56 9 1234 5678``, ``912345678`` o ``56912345678``. Para Chile,
    un número de 9 dígitos que empieza en 9 se asume móvil nacional.
    """
    digitos = _NO_DIGITOS.sub("", numero or "")
    if not digitos:
        raise ErrorEnvioWhatsApp("El contacto no tiene número de WhatsApp configurado.")
    if digitos.startswith(pais_por_defecto) and len(digitos) >= 11:
        return digitos
    if len(digitos) == 9 and digitos.startswith("9"):
        return pais_por_defecto + digitos
    if len(digitos) == 8:
        return f"{pais_por_defecto}9{digitos}"
    return digitos


def enlace_wa_me(numero: str, mensaje: str) -> str:
    """Enlace ``wa.me`` con el texto precargado."""
    return f"https://wa.me/{normalizar_numero(numero)}?text={quote(mensaje)}"


class EnviadorWhatsApp:
    """Despacha el aviso por el proveedor configurado."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.whatsapp: ConfigWhatsApp = config.whatsapp

    # -- API ----------------------------------------------------------------
    def enviar(
        self,
        declaracion: DeclaracionF29,
        contribuyente: Contribuyente,
        *,
        imagen: str = "",
        pdf: str = "",
        numero: str = "",
        simular: bool = False,
    ) -> ResultadoWhatsApp:
        destino = numero or contribuyente.whatsapp
        if not destino:
            raise ErrorEnvioWhatsApp(
                f"El cliente '{contribuyente.alias}' no tiene WhatsApp configurado."
            )
        texto = self.redactar(declaracion, contribuyente)
        enlace = enlace_wa_me(destino, texto)

        proveedor = (self.whatsapp.proveedor or "enlace").lower()
        if simular:
            _log.info("[simulación] WhatsApp (%s) listo para %s — no se envía.", proveedor, destino)
            return ResultadoWhatsApp(enviado=False, enlace=enlace, detalle="simulación")

        if proveedor == "enlace":
            _log.info("Enlace de WhatsApp generado para %s", destino)
            return ResultadoWhatsApp(
                enviado=False,
                enlace=enlace,
                detalle="Abre el enlace para enviar el mensaje desde tu WhatsApp.",
            )
        if proveedor == "twilio":
            return self._enviar_twilio(destino, texto, imagen or pdf, enlace)
        if proveedor == "meta":
            return self._enviar_meta(destino, texto, imagen, pdf, enlace)
        raise ErrorEnvioWhatsApp(
            f"Proveedor de WhatsApp desconocido: '{proveedor}'. Usa 'enlace', 'twilio' o 'meta'."
        )

    # -- mensaje ------------------------------------------------------------
    def redactar(self, declaracion: DeclaracionF29, contribuyente: Contribuyente) -> str:
        razon_social = contribuyente.razon_social or declaracion.razon_social or contribuyente.alias
        if plantilla := self.whatsapp.plantilla_mensaje:
            return plantilla.format(
                nombre=contribuyente.nombre_contacto or razon_social,
                razon_social=razon_social,
                rut=declaracion.rut.formateado,
                periodo=declaracion.periodo.etiqueta,
                periodo_codigo=declaracion.periodo.codigo,
                folio=declaracion.folio,
                monto=pesos(declaracion.monto_a_pagar),
                vencimiento=fecha_con_dia_semana(self._vencimiento(declaracion, contribuyente)),
                estudio=self.config.estudio.nombre,
            )

        saludo = f"Hola {contribuyente.nombre_contacto}" if contribuyente.nombre_contacto else "Hola"
        partes = [
            f"{saludo} 👋",
            "",
            f"Ya presentamos el F29 de *{razon_social}* ({declaracion.rut.formateado}) "
            f"del período *{declaracion.periodo.etiqueta}*.",
        ]
        if declaracion.folio:
            partes.append(f"Folio SII: {declaracion.folio}")
        partes.append("")
        if declaracion.hay_que_pagar:
            partes += [
                f"*Total a pagar: {pesos(declaracion.monto_a_pagar)}*",
                f"Plazo: hasta el {fecha_con_dia_semana(self._vencimiento(declaracion, contribuyente))} (23:59 hrs)",
                "",
            ]
            partes += self._instrucciones_pago(declaracion)
        else:
            partes.append("Este período no genera impuesto a pagar ✅")
            partes.append("")
        partes.append("Te envío el detalle en el PDF adjunto.")
        if self.config.estudio.nombre:
            partes += ["", self.config.estudio.nombre]
        return "\n".join(partes)

    @staticmethod
    def _vencimiento(declaracion: DeclaracionF29, contribuyente: Contribuyente):
        return declaracion.periodo.vencimiento_legal(
            facturador_electronico=contribuyente.facturador_electronico
        )

    def _instrucciones_pago(self, declaracion: DeclaracionF29) -> list[str]:
        pago = self.config.pago
        lineas: list[str] = []
        if pago.modo in ("transferencia", "ambos") and pago.numero_cuenta:
            lineas.append("Datos para transferir:")
            for etiqueta, valor in (
                ("Titular", pago.titular),
                ("RUT", pago.rut_titular),
                ("Banco", pago.banco),
                ("Cuenta", f"{pago.tipo_cuenta} {pago.numero_cuenta}".strip()),
            ):
                if valor:
                    lineas.append(f"• {etiqueta}: {valor}")
            lineas.append(f"• Glosa: F29 {declaracion.periodo.codigo}")
            lineas.append("")
        if pago.modo in ("sii", "ambos"):
            lineas += [f"O paga directo en el SII: {pago.url_pago_sii}", ""]
        if pago.nota:
            lineas += [pago.nota, ""]
        return lineas

    # -- proveedores --------------------------------------------------------
    def _url_publica(self, ruta: str) -> str:
        """URL desde la que el proveedor puede descargar el adjunto."""
        base = self.whatsapp.url_publica_base
        if not base or not ruta:
            return ""
        return urljoin(base.rstrip("/") + "/", Path(ruta).name)

    def _enviar_twilio(self, destino: str, texto: str, adjunto: str, enlace: str) -> ResultadoWhatsApp:
        cfg = self.whatsapp
        if not (cfg.twilio_sid and cfg.twilio_token and cfg.twilio_desde):
            raise ErrorEnvioWhatsApp(
                "Faltan credenciales de Twilio (twilio_sid, twilio_token, twilio_desde)."
            )
        datos = {
            "From": cfg.twilio_desde if cfg.twilio_desde.startswith("whatsapp:") else f"whatsapp:{cfg.twilio_desde}",
            "To": f"whatsapp:+{normalizar_numero(destino)}",
            "Body": texto,
        }
        if url_media := self._url_publica(adjunto):
            datos["MediaUrl"] = url_media

        try:
            respuesta = requests.post(
                f"{URL_TWILIO}/Accounts/{cfg.twilio_sid}/Messages.json",
                data=datos,
                auth=(cfg.twilio_sid, cfg.twilio_token),
                timeout=30,
            )
        except requests.RequestException as exc:
            raise ErrorEnvioWhatsApp(f"No se pudo contactar a Twilio: {exc}") from exc

        if respuesta.status_code >= 400:
            raise ErrorEnvioWhatsApp(f"Twilio respondió {respuesta.status_code}: {respuesta.text[:400]}")
        sid = (respuesta.json() or {}).get("sid", "")
        _log.info("WhatsApp enviado vía Twilio (sid %s)", sid)
        return ResultadoWhatsApp(enviado=True, enlace=enlace, identificador=sid, detalle="twilio")

    def _enviar_meta(
        self, destino: str, texto: str, imagen: str, pdf: str, enlace: str
    ) -> ResultadoWhatsApp:
        cfg = self.whatsapp
        if not (cfg.meta_phone_number_id and cfg.meta_token):
            raise ErrorEnvioWhatsApp(
                "Faltan credenciales de Meta (meta_phone_number_id, meta_token)."
            )
        numero = normalizar_numero(destino)
        url = f"{URL_META}/{cfg.meta_phone_number_id}/messages"
        cabeceras = {
            "Authorization": f"Bearer {cfg.meta_token}",
            "Content-Type": "application/json",
        }

        if cfg.meta_plantilla:
            # Fuera de la ventana de 24 h, Meta sólo acepta plantillas aprobadas.
            cuerpo = {
                "messaging_product": "whatsapp",
                "to": numero,
                "type": "template",
                "template": {
                    "name": cfg.meta_plantilla,
                    "language": {"code": cfg.meta_idioma},
                },
            }
        else:
            cuerpo = {
                "messaging_product": "whatsapp",
                "to": numero,
                "type": "text",
                "text": {"preview_url": True, "body": texto},
            }

        identificador = self._postear_meta(url, cabeceras, cuerpo)

        # Los adjuntos van como mensajes aparte, sólo si hay una URL pública.
        for ruta, tipo in ((imagen, "image"), (pdf, "document")):
            url_media = self._url_publica(ruta)
            if not url_media:
                continue
            medios: dict = {"link": url_media}
            if tipo == "document":
                medios["filename"] = Path(ruta).name
            self._postear_meta(
                url,
                cabeceras,
                {"messaging_product": "whatsapp", "to": numero, "type": tipo, tipo: medios},
            )

        _log.info("WhatsApp enviado vía Meta Cloud API (id %s)", identificador)
        return ResultadoWhatsApp(enviado=True, enlace=enlace, identificador=identificador, detalle="meta")

    @staticmethod
    def _postear_meta(url: str, cabeceras: dict, cuerpo: dict) -> str:
        try:
            respuesta = requests.post(url, json=cuerpo, headers=cabeceras, timeout=30)
        except requests.RequestException as exc:
            raise ErrorEnvioWhatsApp(f"No se pudo contactar a Meta: {exc}") from exc
        if respuesta.status_code >= 400:
            raise ErrorEnvioWhatsApp(f"Meta respondió {respuesta.status_code}: {respuesta.text[:400]}")
        datos = respuesta.json() or {}
        mensajes = datos.get("messages") or [{}]
        return mensajes[0].get("id", "")
