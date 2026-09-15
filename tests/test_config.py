import pytest

from bringmef29 import config as modulo_config
from bringmef29.config import ErrorConfig
from bringmef29.rut import Rut
from bringmef29.seguridad import AlmacenClaves

from .conftest import CONFIG_BASE


def test_carga_secciones(config):
    assert config.estudio.nombre == "Estudio de Prueba"
    assert config.pago.banco == "Banco de Chile"
    assert config.correo.configurado
    assert config.whatsapp.proveedor == "enlace"


def test_busca_cliente_por_alias_y_por_rut(config):
    por_alias = config.cliente("acme")
    assert por_alias.rut == Rut.parsear("76086428-5")
    assert config.cliente("76.086.428-5") is por_alias
    assert config.cliente("ACME") is por_alias


def test_cliente_inexistente(config):
    with pytest.raises(ErrorConfig, match="No hay un cliente"):
        config.cliente("no-existe")


def test_claves_desconocidas_en_el_yaml_fallan():
    datos = {"estudio": {"nombre": "X", "telefno": "typo"}}
    with pytest.raises(ErrorConfig, match="Claves desconocidas"):
        modulo_config.desde_dict(datos)


def test_cliente_sin_rut_falla():
    with pytest.raises(ErrorConfig, match="sin RUT"):
        modulo_config.desde_dict({"clientes": [{"alias": "x"}]})


def test_correo_como_texto_separado_por_comas():
    datos = dict(CONFIG_BASE)
    datos = {**datos, "clientes": [{"alias": "x", "rut": "76086428-5",
                                    "correo": "a@x.cl, b@x.cl"}]}
    cliente = modulo_config.desde_dict(datos).cliente("x")
    assert cliente.correo == ["a@x.cl", "b@x.cl"]


def test_secreto_desde_variable_de_entorno(monkeypatch):
    monkeypatch.setenv("MI_SMTP", "clave-smtp")
    datos = {**CONFIG_BASE, "correo": {**CONFIG_BASE["correo"], "clave": "env:MI_SMTP"}}
    assert modulo_config.desde_dict(datos).correo.clave == "clave-smtp"


def test_secreto_referenciado_pero_ausente(monkeypatch):
    monkeypatch.delenv("NO_DEFINIDA", raising=False)
    datos = {**CONFIG_BASE, "correo": {**CONFIG_BASE["correo"], "clave": "env:NO_DEFINIDA"}}
    with pytest.raises(ErrorConfig, match="env:NO_DEFINIDA"):
        modulo_config.desde_dict(datos)


def test_clave_sii_desde_variable_por_alias(config, monkeypatch):
    monkeypatch.setenv("BRINGMEF29_CLAVE_ACME", "clave-del-sii")
    assert config.clave_sii(config.cliente("acme")) == "clave-del-sii"


def test_clave_sii_desde_el_almacen(config, clave_maestra, monkeypatch):
    monkeypatch.delenv("BRINGMEF29_CLAVE_ACME", raising=False)
    AlmacenClaves(config.ruta_almacen_claves).guardar("76086428-5", "clave-guardada")
    assert config.clave_sii(config.cliente("acme")) == "clave-guardada"


def test_sin_clave_sii_el_mensaje_explica_como_guardarla(config, monkeypatch):
    for variable in ("BRINGMEF29_CLAVE_ACME", "SII_CLAVE_ACME", "BRINGMEF29_CLAVE_SII"):
        monkeypatch.delenv(variable, raising=False)
    with pytest.raises(ErrorConfig, match="bringmef29 clave guardar acme"):
        config.clave_sii(config.cliente("acme"))


def test_el_layout_del_resumen_define_los_grupos_esperados():
    from bringmef29 import resumen

    layout = resumen.cargar_layout()
    assert [g["titulo"] for g in layout["grupos"]] == ["IVA", "Retenciones", "PPM"]
    assert layout["total"]["codigos"][0] == "94"


def test_el_ejemplo_versionado_es_cargable(monkeypatch, tmp_path):
    """El config de ejemplo debe cargar tal cual: RUTs válidos y claves conocidas."""
    from pathlib import Path

    for variable in ("BRINGMEF29_SMTP_CLAVE", "BRINGMEF29_TWILIO_TOKEN", "BRINGMEF29_META_TOKEN"):
        monkeypatch.setenv(variable, "valor-de-prueba")

    ejemplo = Path(__file__).resolve().parents[1] / "config" / "clientes.example.yml"
    config = modulo_config.cargar(ejemplo)

    assert config.clientes
    assert config.cliente("acme").rut == Rut.parsear("76.086.428-5")
    assert Rut.parsear(config.estudio.rut)
    assert Rut.parsear(config.pago.rut_titular)
