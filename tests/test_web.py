"""La pantalla local de RUT y clave tributaria."""

from decimal import Decimal
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from bringmef29 import flujo, web
from bringmef29.modelos import GUARDADA, DeclaracionF29, LineaCodigo, Periodo
from bringmef29.rut import Rut

from .conftest import requiere_chromium


@pytest.fixture
def servidor(config):
    web._Manejador.config = config
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web._Manejador)
    hilo = Thread(target=httpd.serve_forever, daemon=True)
    hilo.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()


def obtener(url: str, headers: dict | None = None) -> tuple[int, str]:
    try:
        with urlopen(Request(url, headers=headers or {}), timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def postear(url: str, datos: dict, headers: dict | None = None) -> tuple[int, str]:
    cuerpo = urlencode(datos).encode()
    peticion = Request(url + "/consultar", data=cuerpo, headers=headers or {})
    try:
        with urlopen(peticion, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


# --------------------------------------------------------------------------- #
# Formulario
# --------------------------------------------------------------------------- #


def test_el_menu_principal_pide_rut_y_clave(servidor):
    estado, html = obtener(servidor + "/")
    assert estado == 200
    assert "Ingrese RUT" in html
    assert "Clave tributaria" in html
    assert 'name="clave"' in html and 'type="password"' in html


def test_el_formulario_dice_que_la_clave_no_sale_del_equipo(servidor):
    _, html = obtener(servidor + "/")
    assert "no se guarda ni sale de este equipo" in html


def test_ruta_desconocida(servidor):
    assert obtener(servidor + "/lo-que-sea")[0] == 404


# --------------------------------------------------------------------------- #
# Consulta
# --------------------------------------------------------------------------- #


def test_rut_invalido_vuelve_al_formulario_con_el_error(servidor):
    estado, html = postear(servidor, {"rut": "12345678-9", "clave": "x", "periodo": "2026-08"})
    assert estado == 200
    assert "Ingrese RUT" in html
    assert "Dígito verificador inválido" in html


def test_sin_clave_no_consulta(servidor, monkeypatch):
    monkeypatch.setattr(
        flujo, "obtener", lambda *a, **k: pytest.fail("no debe consultarse el SII sin clave")
    )
    estado, html = postear(servidor, {"rut": "11.111.111-1", "clave": "", "periodo": "2026-08"})
    assert estado == 200
    assert "Falta la clave tributaria" in html


@requiere_chromium
def test_la_consulta_devuelve_la_tabla(servidor, config, monkeypatch):
    declaracion = DeclaracionF29(
        rut=Rut.parsear("11111111-1"),
        periodo=Periodo(2026, 8),
        razon_social="Comercial Acme SpA",
        via="navegador",
        procedencia=GUARDADA,
        lineas=[
            LineaCodigo(c, Decimal(str(v)))
            for c, v in {"538": 1900000, "537": 2050000, "077": 150000,
                         "048": 40000, "151": 300000, "091": 340000}.items()
        ],
    )
    monkeypatch.setattr(flujo, "obtener", lambda *a, **k: flujo.ResultadoObtencion(declaracion))

    estado, html = postear(
        servidor, {"rut": "11.111.111-1", "clave": "secreta", "periodo": "2026-08"}
    )
    assert estado == 200
    assert "Comercial Acme SpA" in html
    assert "Total retenciones a pagar" in html
    assert "340.000.-" in html
    assert "TOTAL A PAGAR F29 AGOSTO 2026" in html
    assert "Lunes 21 de septiembre, 2026" in html
    # La clave nunca se refleja de vuelta en la página.
    assert "secreta" not in html


@requiere_chromium
def test_la_propuesta_se_rechaza_tambien_desde_la_web(servidor, monkeypatch):
    from bringmef29.modelos import PROPUESTA

    declaracion = DeclaracionF29(
        rut=Rut.parsear("11111111-1"),
        periodo=Periodo(2026, 8),
        procedencia=PROPUESTA,
        lineas=[LineaCodigo("091", Decimal("340000"))],
    )
    monkeypatch.setattr(flujo, "obtener", lambda *a, **k: flujo.ResultadoObtencion(declaracion))

    estado, html = postear(
        servidor, {"rut": "11.111.111-1", "clave": "x", "periodo": "2026-08"}
    )
    assert estado == 200
    assert "propuesta del SII" in html
    assert "TOTAL A PAGAR" not in html


# --------------------------------------------------------------------------- #
# Límites de acceso
# --------------------------------------------------------------------------- #


def test_rechaza_peticiones_con_otro_host(servidor):
    estado, _ = obtener(servidor + "/", {"Host": "contador.ejemplo.cl"})
    assert estado == 403


def test_no_sirve_archivos_fuera_del_directorio_de_salida(servidor):
    estado, _ = obtener(servidor + "/archivo?tipo=pdf&ruta=/etc/passwd")
    assert estado == 403


def test_sirve_lo_que_el_programa_genero(servidor, config):
    archivo = config.directorio_salida / "111111111" / "202608" / "aviso.pdf"
    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_bytes(b"%PDF-1.4 falso")
    estado, cuerpo = obtener(servidor + f"/archivo?tipo=pdf&ruta={archivo}")
    assert estado == 200
    assert cuerpo.startswith("%PDF")
