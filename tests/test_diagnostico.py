"""El chequeo previo: qué falta antes de usarlo con un cliente."""

import pytest

from bringmef29 import diagnostico as D


def por_nombre(chequeos) -> dict:
    return {c.nombre: c for c in chequeos}


def test_revisa_sin_tocar_la_red(config, tmp_path, monkeypatch):
    monkeypatch.setenv("BRINGMEF29_CONFIG", str(tmp_path / "no-existe.yml"))
    chequeos = D.revisar(con_red=False)
    assert all(c.nombre != "SII alcanzable" for c in chequeos)
    assert por_nombre(chequeos)["Python"].estado == D.BIEN


def test_una_configuracion_ausente_es_una_falla(tmp_path, monkeypatch):
    monkeypatch.setenv("BRINGMEF29_CONFIG", str(tmp_path / "no-existe.yml"))
    chequeo = por_nombre(D.revisar(con_red=False))["Configuración"]
    assert chequeo.estado == D.MAL
    assert "clientes.example.yml" in chequeo.arreglo


def test_sin_claves_no_deja_pasar(tmp_path, monkeypatch):
    """El programa no sirve de nada si ningún cliente tiene clave guardada."""
    for variable in ("BRINGMEF29_CLAVE_ACME", "SII_CLAVE_ACME", "BRINGMEF29_CLAVE_SII"):
        monkeypatch.delenv(variable, raising=False)
    ejemplo = tmp_path / "clientes.yml"
    ejemplo.write_text(
        "clientes:\n  - alias: uno\n    rut: 76.086.428-5\n", encoding="utf-8"
    )
    monkeypatch.setenv("BRINGMEF29_CONFIG", str(ejemplo))
    chequeo = por_nombre(D.revisar(con_red=False))["Claves tributarias"]
    assert chequeo.estado == D.MAL
    assert "clave guardar" in chequeo.arreglo


def test_con_clave_en_el_entorno_pasa(tmp_path, monkeypatch):
    ejemplo = tmp_path / "clientes.yml"
    ejemplo.write_text("clientes:\n  - alias: uno\n    rut: 76.086.428-5\n", encoding="utf-8")
    monkeypatch.setenv("BRINGMEF29_CONFIG", str(ejemplo))
    monkeypatch.setenv("BRINGMEF29_CLAVE_UNO", "secreta")
    chequeo = por_nombre(D.revisar(con_red=False))["Claves tributarias"]
    assert chequeo.estado == D.BIEN


def test_chromium_y_excel_estan_disponibles(monkeypatch, tmp_path):
    monkeypatch.setenv("BRINGMEF29_CONFIG", str(tmp_path / "no-existe.yml"))
    chequeos = por_nombre(D.revisar(con_red=False))
    assert chequeos["Chromium"].estado in (D.BIEN, D.AVISO)
    assert chequeos["Exportar a Excel"].estado == D.BIEN


def test_el_directorio_de_salida_se_prueba_escribiendo(config, monkeypatch, tmp_path):
    monkeypatch.setenv("BRINGMEF29_CONFIG", "/no/existe.yml")
    chequeo = D._salida(config)
    assert chequeo.estado == D.BIEN
    assert not (config.directorio_salida / ".escritura").exists()   # se limpia tras probar


@pytest.mark.parametrize("estado,glifo", [(D.BIEN, "✓"), (D.AVISO, "!"), (D.MAL, "✗")])
def test_cada_estado_tiene_su_glifo(estado, glifo):
    assert D.Chequeo("x", estado).glifo == glifo


def test_el_correo_sin_contrasena_avisa_pero_no_bloquea(config):
    config.correo.clave = ""
    chequeo = D._correo(config)
    assert chequeo.estado == D.AVISO
    assert "contraseña de aplicación" in chequeo.arreglo


def test_twilio_sin_credenciales_es_falla(config):
    config.whatsapp.proveedor = "twilio"
    config.whatsapp.twilio_sid = ""
    assert D._whatsapp(config).estado == D.MAL


def test_el_proveedor_enlace_siempre_esta_listo(config):
    config.whatsapp.proveedor = "enlace"
    assert D._whatsapp(config).estado == D.BIEN
