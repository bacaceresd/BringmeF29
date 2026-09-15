import json
import os
import stat

import pytest

from bringmef29.seguridad import (
    AlmacenClaves,
    ErrorSeguridad,
    cifrar,
    descifrar,
    generar_clave_maestra,
    redactar,
)


def test_ciclo_cifrado(clave_maestra):
    token = cifrar("MiClaveTributaria2025")
    assert "MiClaveTributaria2025" not in token
    assert descifrar(token) == "MiClaveTributaria2025"


def test_sin_clave_maestra_falla(monkeypatch):
    monkeypatch.delenv("BRINGMEF29_MASTER_KEY", raising=False)
    monkeypatch.delenv("BRINGMEF29_MASTER_KEY_FILE", raising=False)
    with pytest.raises(ErrorSeguridad, match="Falta la clave maestra"):
        cifrar("x")


def test_otra_clave_maestra_no_descifra(monkeypatch, clave_maestra):
    token = cifrar("secreto")
    monkeypatch.setenv("BRINGMEF29_MASTER_KEY", generar_clave_maestra())
    with pytest.raises(ErrorSeguridad, match="no se pudo descifrar|No se pudo descifrar"):
        descifrar(token)


def test_clave_maestra_malformada_es_rechazada(monkeypatch):
    monkeypatch.setenv("BRINGMEF29_MASTER_KEY", "no-es-una-clave")
    with pytest.raises(ErrorSeguridad, match="no es una clave Fernet válida"):
        cifrar("x")


def test_almacen_guarda_cifrado_y_con_permisos_restringidos(tmp_path, clave_maestra):
    almacen = AlmacenClaves(tmp_path / "claves.json")
    almacen.guardar("11.111.111-1", "ClaveDelCliente", nota="acme")

    contenido = (tmp_path / "claves.json").read_text(encoding="utf-8")
    assert "ClaveDelCliente" not in contenido
    assert json.loads(contenido)["11.111.111-1"]["nota"] == "acme"

    modo = stat.S_IMODE(os.stat(tmp_path / "claves.json").st_mode)
    assert modo == 0o600

    assert almacen.obtener("11.111.111-1") == "ClaveDelCliente"
    assert almacen.ruts() == ["11.111.111-1"]


def test_almacen_elimina(tmp_path, clave_maestra):
    almacen = AlmacenClaves(tmp_path / "claves.json")
    almacen.guardar("11.111.111-1", "x")
    assert almacen.eliminar("11.111.111-1")
    assert not almacen.eliminar("11.111.111-1")
    assert almacen.obtener("11.111.111-1") is None


def test_almacen_rechaza_archivo_legible_por_otros(tmp_path, clave_maestra):
    ruta = tmp_path / "claves.json"
    ruta.write_text("{}", encoding="utf-8")
    os.chmod(ruta, 0o644)
    with pytest.raises(ErrorSeguridad, match="legible por otros"):
        AlmacenClaves(ruta).obtener("11.111.111-1")


@pytest.mark.parametrize(
    "texto",
    [
        "POST login clave=SuperSecreta123",
        'cuerpo {"clave": "SuperSecreta123"}',
        "Authorization: Bearer abc.def.ghi",
    ],
)
def test_redaccion_de_credenciales(texto):
    limpio = redactar(texto)
    assert "SuperSecreta123" not in limpio
    assert "abc.def.ghi" not in limpio
    assert "***" in limpio


def test_redaccion_de_literales():
    assert redactar("la clave va suelta: Zzz123", ("Zzz123",)) == "la clave va suelta: ***"
