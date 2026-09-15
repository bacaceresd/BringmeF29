import pytest

from bringmef29.envio.correo import EnviadorCorreo, ErrorEnvioCorreo
from bringmef29.envio.whatsapp import (
    EnviadorWhatsApp,
    ErrorEnvioWhatsApp,
    enlace_wa_me,
    normalizar_numero,
)


# --------------------------------------------------------------------------- #
# Correo
# --------------------------------------------------------------------------- #


def test_correo_se_compone_sin_enviar(config, declaracion_con_pago, tmp_path):
    adjunto = tmp_path / "aviso.pdf"
    adjunto.write_bytes(b"%PDF-1.4 falso")

    mensaje = EnviadorCorreo(config).enviar(
        declaracion_con_pago, config.cliente("acme"), [str(adjunto)], simular=True
    )

    assert mensaje["To"] == "ana@acme.cl"
    assert mensaje["Subject"] == "F29 Agosto 2025 — Comercial Acme SpA"
    assert "Estudio de Prueba" in mensaje["From"]

    cuerpo = mensaje.get_body(preferencelist=("plain",)).get_content()
    assert "$1.840.000" in cuerpo
    assert "76.086.428-5" in cuerpo
    assert "Lunes 22 de septiembre, 2025" in cuerpo
    assert "00-123-45678-90" in cuerpo

    adjuntos = [p.get_filename() for p in mensaje.iter_attachments()]
    assert adjuntos == ["aviso.pdf"]


def test_correo_sin_pago_no_pide_transferencia(config, declaracion_sin_pago):
    mensaje = EnviadorCorreo(config).enviar(
        declaracion_sin_pago, config.cliente("acme"), [], simular=True
    )
    cuerpo = mensaje.get_body(preferencelist=("plain",)).get_content()
    assert "no genera impuesto a pagar" in cuerpo
    assert "00-123-45678-90" not in cuerpo
    assert "$400.000" in cuerpo   # remanente de crédito fiscal


def test_correo_a_destinatario_alternativo(config, declaracion_con_pago):
    mensaje = EnviadorCorreo(config).enviar(
        declaracion_con_pago,
        config.cliente("acme"),
        [],
        destinatarios=["otro@ejemplo.cl"],
        simular=True,
    )
    assert mensaje["To"] == "otro@ejemplo.cl"


def test_correo_sin_destinatario_falla(config, declaracion_con_pago):
    cliente = config.cliente("acme")
    cliente.correo = []
    with pytest.raises(ErrorEnvioCorreo, match="no tiene correo configurado"):
        EnviadorCorreo(config).enviar(declaracion_con_pago, cliente, [], simular=True)


def test_adjunto_inexistente_se_omite(config, declaracion_con_pago):
    mensaje = EnviadorCorreo(config).enviar(
        declaracion_con_pago, config.cliente("acme"), ["/no/existe.pdf"], simular=True
    )
    assert list(mensaje.iter_attachments()) == []


def test_asunto_personalizable(config, declaracion_con_pago):
    config.correo.asunto = "Pago F29 {periodo_codigo} — {monto}"
    mensaje = EnviadorCorreo(config).enviar(
        declaracion_con_pago, config.cliente("acme"), [], simular=True
    )
    assert mensaje["Subject"] == "Pago F29 202508 — $1.840.000"


# --------------------------------------------------------------------------- #
# WhatsApp
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("+56 9 1111 2222", "56911112222"),
        ("911112222", "56911112222"),
        ("56911112222", "56911112222"),
        ("+56911112222", "56911112222"),
    ],
)
def test_normalizacion_de_numeros(entrada, esperado):
    assert normalizar_numero(entrada) == esperado


def test_numero_vacio_falla():
    with pytest.raises(ErrorEnvioWhatsApp, match="no tiene número"):
        normalizar_numero("")


def test_enlace_wa_me_codifica_el_texto():
    enlace = enlace_wa_me("+56911112222", "Hola Ana, van $1.840.000")
    assert enlace.startswith("https://wa.me/56911112222?text=")
    assert "%24" in enlace or "$" in enlace


def test_mensaje_de_whatsapp_con_pago(config, declaracion_con_pago):
    texto = EnviadorWhatsApp(config).redactar(declaracion_con_pago, config.cliente("acme"))
    assert "Hola Ana" in texto
    assert "Comercial Acme SpA" in texto
    assert "$1.840.000" in texto
    assert "00-123-45678-90" in texto
    assert "Agosto 2025" in texto


def test_mensaje_de_whatsapp_sin_pago(config, declaracion_sin_pago):
    texto = EnviadorWhatsApp(config).redactar(declaracion_sin_pago, config.cliente("acme"))
    assert "no genera impuesto a pagar" in texto
    assert "00-123-45678-90" not in texto


def test_plantilla_de_mensaje_personalizada(config, declaracion_con_pago):
    config.whatsapp.plantilla_mensaje = "{nombre}: F29 {periodo} por {monto}, vence {vencimiento}."
    texto = EnviadorWhatsApp(config).redactar(declaracion_con_pago, config.cliente("acme"))
    assert texto == "Ana: F29 Agosto 2025 por $1.840.000, vence Lunes 22 de septiembre, 2025."


def test_proveedor_enlace_no_envia_pero_entrega_el_link(config, declaracion_con_pago):
    resultado = EnviadorWhatsApp(config).enviar(declaracion_con_pago, config.cliente("acme"))
    assert not resultado.enviado
    assert resultado.enlace.startswith("https://wa.me/56911112222?text=")


def test_proveedor_desconocido_falla(config, declaracion_con_pago):
    config.whatsapp.proveedor = "telepatia"
    with pytest.raises(ErrorEnvioWhatsApp, match="desconocido"):
        EnviadorWhatsApp(config).enviar(declaracion_con_pago, config.cliente("acme"))


def test_twilio_sin_credenciales_falla(config, declaracion_con_pago):
    config.whatsapp.proveedor = "twilio"
    with pytest.raises(ErrorEnvioWhatsApp, match="credenciales de Twilio"):
        EnviadorWhatsApp(config).enviar(declaracion_con_pago, config.cliente("acme"))


def test_meta_sin_credenciales_falla(config, declaracion_con_pago):
    config.whatsapp.proveedor = "meta"
    with pytest.raises(ErrorEnvioWhatsApp, match="credenciales de Meta"):
        EnviadorWhatsApp(config).enviar(declaracion_con_pago, config.cliente("acme"))


def test_cliente_sin_whatsapp_falla(config, declaracion_con_pago):
    cliente = config.cliente("acme")
    cliente.whatsapp = ""
    with pytest.raises(ErrorEnvioWhatsApp, match="no tiene WhatsApp"):
        EnviadorWhatsApp(config).enviar(declaracion_con_pago, cliente)


def test_url_publica_se_arma_desde_la_base(config):
    config.whatsapp.url_publica_base = "https://archivos.ejemplo.cl/f29"
    enviador = EnviadorWhatsApp(config)
    assert enviador._url_publica("/tmp/salida/aviso.pdf") == (
        "https://archivos.ejemplo.cl/f29/aviso.pdf"
    )
    assert enviador._url_publica("") == ""
