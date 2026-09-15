"""Salvaguardas del repositorio: que nada sensible pueda versionarse por descuido."""

from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]

# Rutas que jamás deben poder llegar al repositorio. La primera es la ruta por
# defecto del almacén de claves tributarias; las demás, datos de contribuyentes.
RUTAS_PROHIBIDAS = [
    ".secretos/",
    "secretos/",
    ".env",
    "config/clientes.yml",
    "salida/",
    ".estado_sii/",
]


@pytest.fixture(scope="module")
def reglas() -> set[str]:
    contenido = (RAIZ / ".gitignore").read_text(encoding="utf-8")
    return {
        linea.strip()
        for linea in contenido.splitlines()
        if linea.strip() and not linea.startswith("#")
    }


@pytest.mark.parametrize("ruta", RUTAS_PROHIBIDAS)
def test_gitignore_cubre_lo_sensible(reglas, ruta):
    assert ruta in reglas, f"Falta '{ruta}' en .gitignore"


def test_el_ejemplo_de_configuracion_no_trae_secretos():
    contenido = (RAIZ / "config" / "clientes.example.yml").read_text(encoding="utf-8")
    # Los secretos del ejemplo sólo pueden ser referencias a variables de entorno.
    for linea in contenido.splitlines():
        limpia = linea.split("#", 1)[0].strip()
        if not limpia.startswith(("clave:", "clave_sii:", "twilio_token:", "meta_token:")):
            continue
        valor = limpia.split(":", 1)[1].strip().strip('"')
        assert valor == "" or valor.startswith("env:"), f"Secreto literal en el ejemplo: {linea}"


def test_el_ejemplo_de_entorno_no_trae_valores():
    contenido = (RAIZ / ".env.example").read_text(encoding="utf-8")
    for linea in contenido.splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith("#"):
            continue
        nombre, _, valor = limpia.partition("=")
        assert valor == "", f"{nombre} trae un valor en .env.example"
