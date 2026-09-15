"""Envío del aviso por correo electrónico (SMTP) con los adjuntos del período."""

from __future__ import annotations

import logging
import mimetypes
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

from ..config import ConfigCorreo, Config
from ..calendario import fecha_con_dia_semana
from ..documentos.formato import pesos
from ..modelos import Contribuyente, DeclaracionF29

_log = logging.getLogger(__name__)


class ErrorEnvioCorreo(RuntimeError):
    """No se pudo enviar el correo."""


class EnviadorCorreo:
    """Compone y despacha el correo con el aviso de pago."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.correo: ConfigCorreo = config.correo

    # -- API ----------------------------------------------------------------
    def enviar(
        self,
        declaracion: DeclaracionF29,
        contribuyente: Contribuyente,
        adjuntos: list[str],
        *,
        destinatarios: list[str] | None = None,
        simular: bool = False,
    ) -> EmailMessage:
        """Envía el aviso. Con ``simular=True`` arma el mensaje pero no lo despacha."""
        if not self.correo.configurado and not simular:
            raise ErrorEnvioCorreo(
                "Falta configurar la sección 'correo' (servidor y remitente) en clientes.yml."
            )
        para = destinatarios if destinatarios is not None else list(contribuyente.correo)
        if not para:
            raise ErrorEnvioCorreo(
                f"El cliente '{contribuyente.alias}' no tiene correo configurado."
            )

        mensaje = self._componer(declaracion, contribuyente, adjuntos, para)
        if simular:
            _log.info("[simulación] Correo listo para %s — no se envía.", ", ".join(para))
            return mensaje
        self._despachar(mensaje)
        _log.info("Aviso enviado por correo a %s", ", ".join(para))
        return mensaje

    # -- composición --------------------------------------------------------
    def _componer(
        self,
        declaracion: DeclaracionF29,
        contribuyente: Contribuyente,
        adjuntos: list[str],
        para: list[str],
    ) -> EmailMessage:
        razon_social = contribuyente.razon_social or declaracion.razon_social or contribuyente.alias
        mensaje = EmailMessage()
        mensaje["Subject"] = self.correo.asunto.format(
            periodo=declaracion.periodo.etiqueta,
            periodo_codigo=declaracion.periodo.codigo,
            razon_social=razon_social,
            rut=declaracion.rut.formateado,
            folio=declaracion.folio,
            monto=pesos(declaracion.monto_a_pagar),
        )
        mensaje["From"] = formataddr(
            (self.correo.nombre_remitente or self.config.estudio.nombre or "", self.correo.remitente)
        )
        mensaje["To"] = ", ".join(para)
        if contribuyente.correo_copia:
            mensaje["Cc"] = ", ".join(contribuyente.correo_copia)
        if self.correo.responder_a:
            mensaje["Reply-To"] = self.correo.responder_a
        mensaje["Date"] = formatdate(localtime=True)
        mensaje["Message-ID"] = make_msgid()

        mensaje.set_content(self._texto(declaracion, contribuyente, razon_social))
        mensaje.add_alternative(
            self._html(declaracion, contribuyente, razon_social), subtype="html"
        )
        for ruta in adjuntos:
            self._adjuntar(mensaje, ruta)
        return mensaje

    def _texto(
        self, declaracion: DeclaracionF29, contribuyente: Contribuyente, razon_social: str
    ) -> str:
        saludo = f"Hola {contribuyente.nombre_contacto}," if contribuyente.nombre_contacto else "Hola,"
        lineas = [
            saludo,
            "",
            f"Ya quedó presentado en el SII el Formulario 29 de {razon_social} "
            f"({declaracion.rut.formateado}) correspondiente al período {declaracion.periodo.etiqueta}.",
            "",
        ]
        if declaracion.folio:
            lineas.append(f"Folio SII: {declaracion.folio}")
        if declaracion.hay_que_pagar:
            lineas += [
                f"Total a pagar: {pesos(declaracion.monto_a_pagar)}",
                f"Plazo: hasta el {fecha_con_dia_semana(self._vencimiento(declaracion, contribuyente))} (23:59 hrs)",
                "",
            ]
            lineas += self._instrucciones_pago(declaracion)
        else:
            remanente = declaracion.remanente_periodo_siguiente
            lineas.append("Este período no genera impuesto a pagar.")
            if remanente and remanente > 0:
                lineas.append(
                    f"Queda un remanente de crédito fiscal de {pesos(remanente)} "
                    "para el período siguiente."
                )
            lineas.append("")
        lineas += [
            "En el PDF adjunto está el detalle de la declaración.",
            "",
            "Saludos,",
            self.config.estudio.nombre or "",
        ]
        if self.config.estudio.telefono:
            lineas.append(self.config.estudio.telefono)
        return "\n".join(l for l in lineas if l is not None)

    @staticmethod
    def _vencimiento(declaracion: DeclaracionF29, contribuyente: Contribuyente):
        return declaracion.periodo.vencimiento_legal(
            facturador_electronico=contribuyente.facturador_electronico
        )

    def _instrucciones_pago(self, declaracion: DeclaracionF29) -> list[str]:
        pago = self.config.pago
        lineas: list[str] = []
        if pago.modo in ("transferencia", "ambos") and pago.numero_cuenta:
            lineas += ["Datos para transferencia:"]
            for etiqueta, valor in (
                ("Titular", pago.titular),
                ("RUT", pago.rut_titular),
                ("Banco", pago.banco),
                ("Tipo de cuenta", pago.tipo_cuenta),
                ("N° de cuenta", pago.numero_cuenta),
            ):
                if valor:
                    lineas.append(f"  {etiqueta}: {valor}")
            lineas.append(f"  Monto: {pesos(declaracion.monto_a_pagar)}")
            lineas.append(
                f"  Glosa: F29 {declaracion.periodo.codigo} · {declaracion.rut.formateado}"
            )
            if pago.correo_confirmacion:
                lineas.append(f"  Comprobante a: {pago.correo_confirmacion}")
            lineas.append("")
        if pago.modo in ("sii", "ambos"):
            lineas += [
                "También puedes pagar directamente en el SII:",
                f"  {pago.url_pago_sii}",
                "",
            ]
        if pago.nota:
            lineas += [pago.nota, ""]
        return lineas

    def _html(
        self, declaracion: DeclaracionF29, contribuyente: Contribuyente, razon_social: str
    ) -> str:
        from html import escape

        saludo = (
            f"Hola {escape(contribuyente.nombre_contacto)},"
            if contribuyente.nombre_contacto
            else "Hola,"
        )
        if declaracion.hay_que_pagar:
            destacado = f"""
            <div style="background:#fdf3e3;border-left:5px solid #8a5100;border-radius:8px;
                        padding:16px 20px;margin:20px 0;">
              <div style="font-size:12px;letter-spacing:1.2px;text-transform:uppercase;
                          color:#8a5100;font-weight:700;">Total a pagar</div>
              <div style="font-size:30px;font-weight:700;color:#10233a;">
                {escape(pesos(declaracion.monto_a_pagar))}</div>
              <div style="font-size:13px;color:#5b6b7f;">Plazo: hasta el
                {escape(fecha_con_dia_semana(self._vencimiento(declaracion, contribuyente)))} (23:59 hrs)</div>
            </div>"""
        else:
            destacado = """
            <div style="background:#e9f5ee;border-left:5px solid #1f6b46;border-radius:8px;
                        padding:16px 20px;margin:20px 0;">
              <div style="font-size:12px;letter-spacing:1.2px;text-transform:uppercase;
                          color:#1f6b46;font-weight:700;">Sin pago asociado</div>
              <div style="font-size:14px;color:#10233a;">
                La declaración de este período no genera impuesto a pagar.</div>
            </div>"""

        pago_html = ""
        instrucciones = self._instrucciones_pago(declaracion) if declaracion.hay_que_pagar else []
        if instrucciones:
            cuerpo = "<br>".join(escape(l) for l in instrucciones if l)
            pago_html = (
                '<div style="background:#f4f7fb;border-radius:8px;padding:14px 18px;'
                'font-size:13px;color:#10233a;line-height:1.7;">' + cuerpo + "</div>"
            )

        return f"""<!doctype html>
<html lang="es"><body style="margin:0;padding:24px;background:#eef2f7;
  font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;color:#10233a;">
  <div style="max-width:620px;margin:0 auto;background:#fff;border-radius:12px;padding:28px 32px;">
    <p style="margin:0 0 14px;">{saludo}</p>
    <p style="margin:0 0 4px;font-size:15px;">
      Ya quedó presentado en el SII el <strong>Formulario 29</strong> de
      <strong>{escape(razon_social)}</strong> ({escape(declaracion.rut.formateado)})
      del período <strong>{escape(declaracion.periodo.etiqueta)}</strong>.
    </p>
    {f'<p style="margin:0;font-size:13px;color:#5b6b7f;">Folio SII: {escape(declaracion.folio)}</p>' if declaracion.folio else ''}
    {destacado}
    {pago_html}
    <p style="margin:20px 0 0;font-size:13px;color:#5b6b7f;">
      El detalle completo de la declaración va en el PDF adjunto.
    </p>
    <p style="margin:18px 0 0;font-size:13px;">
      Saludos,<br><strong>{escape(self.config.estudio.nombre or '')}</strong>
      {f"<br>{escape(self.config.estudio.telefono)}" if self.config.estudio.telefono else ""}
    </p>
  </div>
</body></html>"""

    @staticmethod
    def _adjuntar(mensaje: EmailMessage, ruta: str) -> None:
        archivo = Path(ruta)
        if not archivo.exists():
            _log.warning("Se omite el adjunto inexistente %s", archivo)
            return
        tipo, _ = mimetypes.guess_type(archivo.name)
        principal, _, secundario = (tipo or "application/octet-stream").partition("/")
        mensaje.add_attachment(
            archivo.read_bytes(),
            maintype=principal,
            subtype=secundario or "octet-stream",
            filename=archivo.name,
        )

    # -- transporte ---------------------------------------------------------
    def _despachar(self, mensaje: EmailMessage) -> None:
        cfg = self.correo
        contexto = ssl.create_default_context()
        try:
            if cfg.seguridad == "ssl":
                with smtplib.SMTP_SSL(cfg.servidor, cfg.puerto, context=contexto, timeout=30) as smtp:
                    self._autenticar_y_enviar(smtp, mensaje)
            else:
                with smtplib.SMTP(cfg.servidor, cfg.puerto, timeout=30) as smtp:
                    if cfg.seguridad == "starttls":
                        smtp.starttls(context=contexto)
                    self._autenticar_y_enviar(smtp, mensaje)
        except smtplib.SMTPAuthenticationError as exc:
            raise ErrorEnvioCorreo(
                "El servidor SMTP rechazó las credenciales. Si usas Gmail o Microsoft 365 "
                "necesitas una contraseña de aplicación, no la del correo."
            ) from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise ErrorEnvioCorreo(f"Falló el envío por SMTP: {exc}") from exc

    def _autenticar_y_enviar(self, smtp: smtplib.SMTP, mensaje: EmailMessage) -> None:
        if self.correo.usuario and self.correo.clave:
            smtp.login(self.correo.usuario, self.correo.clave)
        smtp.send_message(mensaje)
