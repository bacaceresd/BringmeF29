"""El punto crítico: no confundir la propuesta del SII con el F29 del contribuyente."""

from decimal import Decimal

import pytest

from bringmef29 import flujo
from bringmef29.modelos import (
    GUARDADA,
    PRESENTADA,
    PROCEDENCIA_DESCONOCIDA,
    PROPUESTA,
    DeclaracionF29,
    LineaCodigo,
    Periodo,
)
from bringmef29.rut import Rut
from bringmef29.sii import procedencia as clasificador
from bringmef29.sii.errores import DeclaracionEsPropuesta, RespuestaInesperada
from bringmef29.sii.f29_navegador import _lineas_desde_campos


# --------------------------------------------------------------------------- #
# Clasificador
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "texto",
    [
        "Propuesta de Declaración F29",
        "PROPUESTA F29 generada a partir del Registro de Compras y Ventas",
        "Aceptar propuesta",
        "El SII le sugiere la siguiente propuesta de declaración",
        "propuesta de declaracion",   # sin acentos, como puede venir del DOM
    ],
)
def test_detecta_la_propuesta_del_sii(texto):
    assert clasificador.clasificar(texto=texto) == PROPUESTA


@pytest.mark.parametrize(
    "texto",
    [
        "Declaración guardada",
        "Continuar declaración",
        "Recuperar declaración",
        "Tiene un borrador guardado para este período",
    ],
)
def test_detecta_el_formulario_guardado(texto):
    assert clasificador.clasificar(texto=texto) == GUARDADA


def test_detecta_la_declaracion_presentada():
    assert clasificador.clasificar(texto="Comprobante de declaración", folio="7654321098") == PRESENTADA
    assert clasificador.clasificar(estado="Vigente") == PRESENTADA
    assert clasificador.clasificar(folio="7654321098") == PRESENTADA


def test_sin_senales_no_inventa_una_procedencia():
    assert clasificador.clasificar(texto="bienvenido a mi sii") == PROCEDENCIA_DESCONOCIDA
    assert clasificador.clasificar() == PROCEDENCIA_DESCONOCIDA


def test_la_propuesta_gana_sobre_cualquier_otra_senal():
    """Confundir la propuesta con lo declarado es el error caro: ante ambas, propuesta."""
    texto = "Propuesta de declaración F29 — Declaración guardada"
    assert clasificador.clasificar(texto=texto, folio="7654321098", estado="Vigente") == PROPUESTA


@pytest.mark.parametrize(
    "crudo",
    [
        {"data": {"esPropuesta": True}},
        {"a": {"b": {"tipoPropuesta": "PROPUESTA"}}},
        {"origenDatos": "RCV"},
        [{"propuesta": "propuesta"}],
    ],
)
def test_detecta_la_propuesta_en_el_json(crudo):
    assert clasificador.clasificar(crudo=crudo) == PROPUESTA


def test_el_json_de_una_declaracion_normal_no_se_marca_como_propuesta():
    crudo = {"data": {"folio": "7654321098", "detalle": [{"codigo": "538", "valor": 100}]}}
    assert clasificador.clasificar(crudo=crudo, folio="7654321098") == PRESENTADA


def test_normalizar_quita_acentos_y_colapsa_espacios():
    assert clasificador.normalizar("  Declaración   GUARDADA ") == "declaracion guardada"


# --------------------------------------------------------------------------- #
# Lectura de los campos del formulario (donde vive el F29 guardado)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "nombre",
    ["codigo_538", "cod538", "c_538", "campo_538", "form29_538", "538"],
)
def test_lee_los_codigos_desde_los_campos_del_formulario(nombre):
    lineas = list(_lineas_desde_campos([{"nombre": nombre, "valor": "3.515.000"}]))
    assert len(lineas) == 1
    assert lineas[0].codigo == "538"
    assert lineas[0].valor == Decimal(3515000)


def test_ignora_los_campos_que_no_son_codigos():
    campos = [
        {"nombre": "rutBuscar", "valor": "76086428"},
        {"nombre": "csrf_token", "valor": "abc"},
        {"nombre": "", "valor": "9"},
        {"nombre": "codigo_538", "valor": ""},
        {"nombre": "codigo_537", "valor": "2.100.000"},
    ]
    lineas = list(_lineas_desde_campos(campos))
    assert [l.codigo for l in lineas] == ["537"]


def test_el_primer_valor_de_un_codigo_repetido_gana():
    campos = [{"nombre": "codigo_091", "valor": "100"}, {"nombre": "c_91", "valor": "999"}]
    lineas = list(_lineas_desde_campos(campos))
    assert len(lineas) == 1 and lineas[0].valor == Decimal(100)


# --------------------------------------------------------------------------- #
# Guardia del flujo
# --------------------------------------------------------------------------- #


def _declaracion(procedencia: str) -> DeclaracionF29:
    return DeclaracionF29(
        rut=Rut.parsear("76086428-5"),
        periodo=Periodo(2025, 8),
        procedencia=procedencia,
        lineas=[LineaCodigo("091", Decimal("1840000"))],
    )


def test_la_guardia_rechaza_la_propuesta():
    with pytest.raises(DeclaracionEsPropuesta, match="--permitir-propuesta"):
        flujo.verificar_procedencia(_declaracion(PROPUESTA))


def test_la_guardia_rechaza_lo_que_no_pudo_clasificar():
    with pytest.raises(RespuestaInesperada, match="No se pudo determinar"):
        flujo.verificar_procedencia(_declaracion(PROCEDENCIA_DESCONOCIDA))


@pytest.mark.parametrize("procedencia", [GUARDADA, PRESENTADA])
def test_la_guardia_deja_pasar_lo_del_contribuyente(procedencia):
    flujo.verificar_procedencia(_declaracion(procedencia))   # no levanta


def test_la_propuesta_pasa_solo_si_se_pide_explicitamente():
    flujo.verificar_procedencia(_declaracion(PROPUESTA), permitir_propuesta=True)


def test_propiedades_de_procedencia():
    assert _declaracion(PROPUESTA).es_propuesta_del_sii
    assert not _declaracion(PROPUESTA).es_del_contribuyente
    assert _declaracion(GUARDADA).es_del_contribuyente
    assert _declaracion(PRESENTADA).es_del_contribuyente
    assert "guardada" in _declaracion(GUARDADA).procedencia_glosa.lower()


# --------------------------------------------------------------------------- #
# Elección de fuente en el flujo
# --------------------------------------------------------------------------- #


def test_la_fuente_por_defecto_es_el_formulario_guardado(config):
    assert config.sii.fuente == "guardada"


def test_pedir_la_guardada_por_api_es_un_error(config, monkeypatch):
    monkeypatch.setenv("BRINGMEF29_CLAVE_ACME", "x")
    with pytest.raises(ValueError, match="sólo alcanza las declaraciones presentadas"):
        flujo.obtener(
            config, config.cliente("acme"), Periodo(2025, 8), fuente="guardada", modo="api"
        )


def test_fuente_desconocida(config, monkeypatch):
    monkeypatch.setenv("BRINGMEF29_CLAVE_ACME", "x")
    with pytest.raises(ValueError, match="Fuente desconocida"):
        flujo.obtener(config, config.cliente("acme"), Periodo(2025, 8), fuente="propuesta")


def test_la_guardada_va_al_navegador_aunque_el_modo_sea_auto(config, monkeypatch):
    """El F29 guardado no existe en la vía API: no debe intentarse por ahí."""
    monkeypatch.setenv("BRINGMEF29_CLAVE_ACME", "x")
    llamadas = []

    monkeypatch.setattr(
        flujo, "_obtener_api", lambda *a, **k: llamadas.append("api") or pytest.fail("no usar api")
    )
    monkeypatch.setattr(
        flujo,
        "obtener_con_navegador",
        lambda *a, **k: (llamadas.append(k.get("fuente")), (_declaracion(GUARDADA), "", ""))[1],
    )

    resultado = flujo.obtener(config, config.cliente("acme"), Periodo(2025, 8), modo="auto")

    assert llamadas == ["guardada"]
    assert resultado.declaracion.procedencia == GUARDADA


def test_procesar_no_genera_nada_con_una_propuesta(config, monkeypatch):
    monkeypatch.setenv("BRINGMEF29_CLAVE_ACME", "x")
    monkeypatch.setattr(
        flujo, "obtener", lambda *a, **k: flujo.ResultadoObtencion(_declaracion(PROPUESTA))
    )
    monkeypatch.setattr(
        flujo, "ConstructorDocumentos", lambda *a, **k: pytest.fail("no debe generar documentos")
    )
    with pytest.raises(DeclaracionEsPropuesta):
        flujo.procesar(config, "acme", Periodo(2025, 8))
