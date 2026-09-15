"""El F29 por secciones: la versión formal del período, la que va por correo."""

from decimal import Decimal

import pytest

from bringmef29 import formulario as F
from bringmef29.cuadratura import describir, verificar
from bringmef29.modelos import GUARDADA, DeclaracionF29, LineaCodigo, Periodo
from bringmef29.rut import Rut

from .conftest import requiere_chromium

# Un período con remanente: el crédito supera al débito, y lo único que se
# entera son las retenciones. Las liquidaciones factura emitidas (818) anulan
# el débito de las boletas.
CASO = {
    "586": 8821, "142": 55958303,
    "503": 22, "502": 2317063,
    "110": 7144, "111": 23030105,
    "817": 29, "818": 23030105,
    "538": 2317063,
    "511": 1986892,
    "519": 25, "520": 1993566,
    "527": 3, "528": 6674,
    "504": 2533186,
    "537": 4520078,
    "77": 2203015,
    "48": 53572, "151": 386874,
    "30": 13823935,
    "595": 440446, "547": 440446, "91": 440446,
}


def declaracion(codigos: dict = None) -> DeclaracionF29:
    return DeclaracionF29(
        rut=Rut.parsear("76086428-5"),
        periodo=Periodo(2026, 8),
        razon_social="Razón social",
        procedencia=GUARDADA,
        lineas=[LineaCodigo(c, Decimal(str(v))) for c, v in (codigos or CASO).items()],
    )


def lineas_de(formulario: F.Formulario) -> dict[int, F.LineaFormulario]:
    return {l.numero: l for s in formulario.secciones for l in s.lineas}


# --------------------------------------------------------------------------- #
# Estructura
# --------------------------------------------------------------------------- #


def test_la_estructura_cubre_las_secciones_del_formulario():
    secciones = F.cargar_estructura()["secciones"]
    titulos = {s["titulo"] for s in secciones}
    assert {"DÉBITOS Y VENTAS", "CRÉDITOS Y COMPRAS",
            "IMPUESTO A LA RENTA D.L. 824/74", "RESULTADO"} <= titulos


def test_cada_seccion_declara_sus_columnas():
    for seccion in F.cargar_estructura()["secciones"]:
        assert seccion.get("lineas"), f"sección vacía: {seccion['titulo']}"
        assert "columnas" in seccion


def test_los_totales_del_formulario_estan_donde_corresponde():
    lineas = {l["n"]: l for s in F.cargar_estructura()["secciones"] for l in s["lineas"]}
    assert lineas[24]["codigo"] == "538"     # total débitos
    assert lineas[50]["codigo"] == "537"     # total créditos
    assert lineas[81]["codigo"] == "595"     # subtotal anverso
    assert lineas[141]["codigo"] == "547"    # total determinado
    assert lineas[148]["codigo"] == "91"     # total a pagar en plazo


def test_las_liquidaciones_emitidas_restan_del_debito():
    """El 818 es el que anula el débito de las ventas por cuenta de terceros."""
    lineas = {l["n"]: l for s in F.cargar_estructura()["secciones"] for l in s["lineas"]}
    assert lineas[18]["codigo"] == "818"
    assert lineas[18]["signo"] == "-"
    assert lineas[17]["codigo"] == "501"
    assert lineas[17]["signo"] == "+"
    assert describir("818")["signo"] == "-"


# --------------------------------------------------------------------------- #
# Armado compacto
# --------------------------------------------------------------------------- #


def test_el_compacto_deja_solo_las_lineas_con_valor():
    compacto = F.construir(declaracion())
    assert compacto.lineas_con_valor == 17
    numeros = sorted(lineas_de(compacto))
    assert numeros == [2, 7, 10, 18, 24, 25, 29, 33, 37, 50, 51, 61, 62, 70, 81, 141, 148]


def test_el_compacto_omite_las_secciones_que_quedan_vacias():
    """Un contribuyente sin impuestos adicionales no ve esa sección."""
    solo_iva = F.construir(declaracion({"538": 100, "537": 50, "89": 50, "91": 50}))
    titulos = [f"{s.titulo} · {s.subtitulo}" for s in solo_iva.secciones]
    assert not any("Ley 20.765" in t and len(t) > 40 for t in titulos[:1])
    assert all(s.tiene_valor for s in solo_iva.secciones)


def test_una_linea_cuenta_por_cualquiera_de_sus_casillas():
    """La línea 70 aparece por la pérdida del art. 90, aunque el PPM esté vacío."""
    linea = lineas_de(F.construir(declaracion()))[70]
    assert linea.monto.codigo == "62"
    assert not linea.monto.tiene_valor
    assert linea.tiene_valor
    perdida = next(c for c in linea.extra if c.codigo == "30")
    assert perdida.valor == Decimal(13823935)
    assert perdida.etiqueta == "Monto pérdida Art. 90"


def test_las_cantidades_de_documentos_viajan_con_su_monto():
    boletas = lineas_de(F.construir(declaracion()))[10]
    assert boletas.cantidad.codigo == "110" and boletas.cantidad.valor == Decimal(7144)
    assert boletas.monto.codigo == "111" and boletas.monto.valor == Decimal(23030105)


def test_los_totales_quedan_marcados():
    total_debitos = lineas_de(F.construir(declaracion()))[24]
    assert total_debitos.total
    assert total_debitos.signo == "="


# --------------------------------------------------------------------------- #
# Armado completo
# --------------------------------------------------------------------------- #


def test_el_completo_trae_todas_las_lineas():
    completo = F.construir(declaracion(), completo=True)
    assert sum(len(s.lineas) for s in completo.secciones) == 87
    assert completo.completo
    # Las vacías siguen ahí, con su código y sin valor.
    exportaciones = lineas_de(completo)[1]
    assert exportaciones.monto.codigo == "20"
    assert not exportaciones.monto.tiene_valor


def test_el_completo_no_omite_secciones():
    vacia = F.construir(declaracion({"91": 0}), completo=True)
    assert len(vacia.secciones) == len(F.cargar_estructura()["secciones"])


# --------------------------------------------------------------------------- #
# Cuadratura sobre la estructura vigente
# --------------------------------------------------------------------------- #


def test_el_caso_real_cuadra_entero():
    """Con el 818 restando, los totales del formulario calzan con sus líneas."""
    assert verificar(declaracion()) == []


def test_un_total_alterado_se_detecta():
    descuadres = verificar(declaracion({**CASO, "538": 9999999}))
    assert any(d.codigo == "538" for d in descuadres)


# --------------------------------------------------------------------------- #
# Formato
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "valor,esperado",
    [(2317063, "2.317.063"), (0, "0"), (None, ""), (Decimal("6674"), "6.674")],
)
def test_formato_de_monto(valor, esperado):
    assert F.monto(valor) == esperado


# --------------------------------------------------------------------------- #
# Documentos
# --------------------------------------------------------------------------- #


@requiere_chromium
def test_genera_los_tres_exportables(config, tmp_path):
    from bringmef29.documentos import ConstructorDocumentos

    documentos = ConstructorDocumentos(config).construir_formulario(
        declaracion(), config.cliente("acme"),
        destino=tmp_path, compacto=True, completo=True, excel=True, guardar_html=True,
    )
    from pathlib import Path

    assert Path(documentos.formulario_pdf).read_bytes().startswith(b"%PDF")
    assert Path(documentos.formulario_completo_pdf).read_bytes().startswith(b"%PDF")
    assert Path(documentos.formulario_excel).read_bytes().startswith(b"PK")

    html = next(tmp_path.glob("*-formulario.html")).read_text(encoding="utf-8")
    assert "DÉBITOS Y VENTAS" in html
    assert "2.317.063" in html
    assert ".seccion{margin-bottom" in html          # el CSS llega sin escapar
    assert "&gt;" not in html.split("</style>")[0]


@requiere_chromium
def test_el_correo_lleva_el_formulario_y_whatsapp_la_imagen(config, tmp_path):
    from bringmef29.documentos import ConstructorDocumentos

    constructor = ConstructorDocumentos(config)
    cliente = config.cliente("acme")
    resumen = constructor.construir(declaracion(), cliente, destino=tmp_path)
    formulario = constructor.construir_formulario(
        declaracion(), cliente, destino=tmp_path, compacto=True
    )
    resumen.formulario_pdf = formulario.formulario_pdf

    assert resumen.formulario_pdf in resumen.para_correo
    assert resumen.pdf in resumen.para_correo
    assert resumen.para_whatsapp == [resumen.imagen]


def test_el_excel_necesita_openpyxl_o_lo_dice():
    from bringmef29.documentos.excel import ErrorExcel

    assert issubclass(ErrorExcel, RuntimeError)
