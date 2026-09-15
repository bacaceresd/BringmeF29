"""El recorrido completo, con un SII de mentira: traer, armar, enviar.

Comprueba que las piezas encajan entre sí — el orden de los pasos, qué documento
sale por qué canal, qué pasa cuando el SII devuelve algo que no corresponde —
sin tocar el SII real ni mandar un correo de verdad.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from bringmef29 import flujo
from bringmef29.modelos import GUARDADA, PROPUESTA, DeclaracionF29, LineaCodigo, Periodo
from bringmef29.rut import Rut
from bringmef29.sii.errores import DeclaracionEsPropuesta, DeclaracionGuardadaNoEncontrada

from .conftest import requiere_chromium

CASO = {
    "586": 8821, "142": 55958303, "503": 22, "502": 2317063,
    "110": 7144, "111": 23030105, "817": 29, "818": 23030105, "538": 2317063,
    "511": 1986892, "519": 25, "520": 1993566, "527": 3, "528": 6674,
    "504": 2533186, "537": 4520078, "77": 2203015,
    "48": 53572, "151": 386874, "30": 13823935,
    "595": 440446, "547": 440446, "91": 440446,
}


def declaracion(codigos: dict = None, procedencia: str = GUARDADA) -> DeclaracionF29:
    return DeclaracionF29(
        rut=Rut.parsear("76086428-5"),
        periodo=Periodo(2026, 8),
        razon_social="Razón social",
        folio="",
        via="navegador",
        procedencia=procedencia,
        lineas=[LineaCodigo(c, Decimal(str(v))) for c, v in (codigos or CASO).items()],
    )


@pytest.fixture
def sii_de_mentira(monkeypatch):
    """Reemplaza la consulta al SII por una respuesta fija."""

    def instalar(resultado):
        if isinstance(resultado, Exception):
            def falso(*_a, **_k):
                raise resultado
        else:
            def falso(*_a, **_k):
                return flujo.ResultadoObtencion(resultado)
        monkeypatch.setattr(flujo, "obtener", falso)

    return instalar


@pytest.fixture
def correos(monkeypatch):
    """Intercepta el despacho SMTP y guarda los mensajes que se habrían enviado."""
    enviados = []
    from bringmef29.envio import correo as modulo

    monkeypatch.setattr(modulo.EnviadorCorreo, "_despachar",
                        lambda self, mensaje: enviados.append(mensaje))
    return enviados


# --------------------------------------------------------------------------- #
# El recorrido feliz
# --------------------------------------------------------------------------- #


@requiere_chromium
def test_del_sii_al_correo_y_al_whatsapp(config, sii_de_mentira, correos, monkeypatch):
    monkeypatch.setenv("BRINGMEF29_CLAVE_ACME", "x")
    sii_de_mentira(declaracion())

    aviso = flujo.procesar(config, "acme", Periodo(2026, 8), exportar=("compacto", "excel"))

    # Se generó todo lo que el período necesita.
    for ruta in (aviso.pdf, aviso.imagen, aviso.formulario_pdf, aviso.formulario_excel):
        assert Path(ruta).exists(), ruta

    # La declaración quedó guardada para poder reimprimir sin volver al SII.
    guardado = config.directorio_salida / "760864285" / "202608" / "declaracion.json"
    assert guardado.exists()

    # El correo salió con el formulario adjunto, no sólo con el resumen.
    assert len(correos) == 1
    adjuntos = [p.get_filename() for p in correos[0].iter_attachments()]
    assert any(n.endswith("-formulario.pdf") for n in adjuntos)
    assert any(n.endswith("-formulario.xlsx") for n in adjuntos)
    assert aviso.enviado_correo

    # WhatsApp quedó como enlace listo para enviar, con el monto en el texto.
    assert aviso.enlace_whatsapp.startswith("https://wa.me/")
    assert aviso.incidencias == []


@requiere_chromium
def test_el_monto_del_aviso_es_el_del_formulario(config, sii_de_mentira, correos, monkeypatch):
    monkeypatch.setenv("BRINGMEF29_CLAVE_ACME", "x")
    sii_de_mentira(declaracion())

    flujo.procesar(config, "acme", Periodo(2026, 8), exportar=())

    cuerpo = correos[0].get_body(preferencelist=("plain",)).get_content()
    assert "$440.446" in cuerpo
    assert "Lunes 21 de septiembre, 2026" in cuerpo


# --------------------------------------------------------------------------- #
# Cuando el SII no entrega lo que corresponde
# --------------------------------------------------------------------------- #


def test_la_propuesta_corta_el_flujo_antes_de_generar_nada(
    config, sii_de_mentira, correos, monkeypatch
):
    monkeypatch.setenv("BRINGMEF29_CLAVE_ACME", "x")
    sii_de_mentira(declaracion(procedencia=PROPUESTA))
    monkeypatch.setattr(
        flujo, "ConstructorDocumentos", lambda *a, **k: pytest.fail("no debe generar documentos")
    )

    with pytest.raises(DeclaracionEsPropuesta):
        flujo.procesar(config, "acme", Periodo(2026, 8))
    assert correos == []


def test_un_periodo_sin_declaracion_no_manda_nada(config, sii_de_mentira, correos, monkeypatch):
    monkeypatch.setenv("BRINGMEF29_CLAVE_ACME", "x")
    sii_de_mentira(DeclaracionGuardadaNoEncontrada("no hay F29 guardado para ese período"))

    with pytest.raises(DeclaracionGuardadaNoEncontrada):
        flujo.procesar(config, "acme", Periodo(2026, 8))
    assert correos == []


@requiere_chromium
def test_un_descuadre_llega_al_documento(config, sii_de_mentira, correos, monkeypatch):
    """Si los totales no calzan con sus líneas, el aviso lo dice."""
    monkeypatch.setenv("BRINGMEF29_CLAVE_ACME", "x")
    sii_de_mentira(declaracion({**CASO, "538": 9999999}))

    aviso = flujo.procesar(config, "acme", Periodo(2026, 8), exportar=("compacto",), guardar_html=True)

    html = next(Path(aviso.formulario_pdf).parent.glob("*-formulario.html")).read_text(
        encoding="utf-8"
    )
    assert "Revisa estas cifras" in html
    assert "538" in html


# --------------------------------------------------------------------------- #
# Reimprimir sin volver al SII
# --------------------------------------------------------------------------- #


@requiere_chromium
def test_se_puede_reimprimir_desde_lo_guardado(config, sii_de_mentira, correos, monkeypatch):
    monkeypatch.setenv("BRINGMEF29_CLAVE_ACME", "x")
    sii_de_mentira(declaracion())
    flujo.procesar(config, "acme", Periodo(2026, 8), exportar=(), enviar_correo=False,
                   enviar_whatsapp=False)

    guardado = str(config.directorio_salida / "760864285" / "202608" / "declaracion.json")
    monkeypatch.setattr(flujo, "obtener", lambda *a, **k: pytest.fail("no debe ir al SII"))

    aviso = flujo.procesar(config, "acme", Periodo(2026, 8), desde_archivo=guardado,
                           simular_envio=True, exportar=("compacto",))
    assert Path(aviso.formulario_pdf).exists()
    assert aviso.declaracion.monto_a_pagar == Decimal(440446)
