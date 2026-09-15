"""La aplicación local: una pantalla por URL y los documentos a la vista."""

from decimal import Decimal
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from bringmef29 import flujo
from bringmef29.modelos import GUARDADA, DeclaracionF29, LineaCodigo, Periodo
from bringmef29.rut import Rut
from bringmef29.web import historial, servidor

from .conftest import requiere_chromium


@pytest.fixture
def servidor_local(config):
    servidor._Manejador.config = config
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), servidor._Manejador)
    hilo = Thread(target=httpd.serve_forever, daemon=True)
    hilo.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()


def obtener(url: str, headers: dict | None = None, seguir: bool = True) -> tuple[int, str]:
    peticion = Request(url, headers=headers or {})
    try:
        with urlopen(peticion, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def postear(url: str, datos: dict, headers: dict | None = None) -> tuple[int, str]:
    cuerpo = urlencode(datos).encode()
    peticion = Request(url + "/consultar", data=cuerpo, headers=headers or {})
    try:
        with urlopen(peticion, timeout=120) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


@pytest.fixture
def declaracion_guardada():
    return DeclaracionF29(
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


# --------------------------------------------------------------------------- #
# Pantalla de consulta
# --------------------------------------------------------------------------- #


def test_el_menu_principal_pide_rut_y_clave(servidor_local):
    estado, html = obtener(servidor_local + "/")
    assert estado == 200
    assert "Ingrese RUT" in html
    assert "Clave tributaria" in html
    assert 'name="clave"' in html and 'type="password"' in html


def test_el_formulario_dice_que_la_clave_no_sale_del_equipo(servidor_local):
    _, html = obtener(servidor_local + "/")
    assert "no se guarda ni sale de este equipo" in html


def test_el_menu_lleva_al_historial_y_a_los_codigos(servidor_local):
    _, html = obtener(servidor_local + "/")
    assert 'href="/historial"' in html
    assert 'href="/codigos"' in html


def test_ruta_desconocida(servidor_local):
    assert obtener(servidor_local + "/lo-que-sea")[0] == 404


# --------------------------------------------------------------------------- #
# Consulta
# --------------------------------------------------------------------------- #


def test_rut_invalido_vuelve_al_formulario_con_el_error(servidor_local):
    estado, html = postear(
        servidor_local, {"rut": "12345678-9", "clave": "x", "mes": "8", "anio": "2026"}
    )
    assert estado == 200
    assert "Ingrese RUT" in html
    assert "Dígito verificador inválido" in html


def test_sin_clave_no_consulta(servidor_local, monkeypatch):
    monkeypatch.setattr(
        flujo, "obtener", lambda *a, **k: pytest.fail("no debe consultarse el SII sin clave")
    )
    estado, html = postear(
        servidor_local, {"rut": "11.111.111-1", "clave": "", "mes": "8", "anio": "2026"}
    )
    assert estado == 200
    assert "Falta la clave tributaria" in html


@requiere_chromium
def test_la_consulta_muestra_el_resumen_y_los_documentos(
    servidor_local, config, monkeypatch, declaracion_guardada
):
    monkeypatch.setattr(
        flujo, "obtener", lambda *a, **k: flujo.ResultadoObtencion(declaracion_guardada)
    )
    estado, html = postear(
        servidor_local,
        {"rut": "11.111.111-1", "clave": "secreta", "mes": "8", "anio": "2026"},
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
def test_la_consulta_genera_los_cinco_documentos(
    servidor_local, config, monkeypatch, declaracion_guardada
):
    monkeypatch.setattr(
        flujo, "obtener", lambda *a, **k: flujo.ResultadoObtencion(declaracion_guardada)
    )
    _, html = postear(
        servidor_local,
        {"rut": "11.111.111-1", "clave": "secreta", "mes": "8", "anio": "2026"},
    )
    entrada = historial.listar(config)[0]
    rutas = entrada["rutas"]
    assert len(rutas) == 5
    for etiqueta, ruta in rutas.items():
        assert Path(ruta).is_file(), etiqueta
        assert "/archivo?" in html
    sufijos = sorted(Path(r).suffix for r in rutas.values())
    assert sufijos == [".pdf", ".pdf", ".pdf", ".png", ".xlsx"]


@requiere_chromium
def test_los_documentos_se_descargan(servidor_local, config, monkeypatch, declaracion_guardada):
    monkeypatch.setattr(
        flujo, "obtener", lambda *a, **k: flujo.ResultadoObtencion(declaracion_guardada)
    )
    postear(servidor_local, {"rut": "11.111.111-1", "clave": "x", "mes": "8", "anio": "2026"})
    rutas = historial.listar(config)[0]["rutas"]
    ruta_pdf = next(r for r in rutas.values() if r.endswith("-formulario.pdf"))
    estado, cuerpo = obtener(servidor_local + "/archivo?" + urlencode({"ruta": ruta_pdf}))
    assert estado == 200
    assert cuerpo.startswith("%PDF")


@requiere_chromium
def test_el_resumen_lleva_al_formulario_por_secciones(
    servidor_local, config, monkeypatch, declaracion_guardada
):
    monkeypatch.setattr(
        flujo, "obtener", lambda *a, **k: flujo.ResultadoObtencion(declaracion_guardada)
    )
    postear(servidor_local, {"rut": "11.111.111-1", "clave": "x", "mes": "8", "anio": "2026"})
    ref = historial.listar(config)[0]["ref"]

    estado, html = obtener(servidor_local + "/formulario?" + urlencode({"ref": ref}))
    assert estado == 200
    assert "DÉBITOS Y VENTAS" in html
    assert "IMPUESTO A LA RENTA D.L. 824/74" in html
    # El compacto muestra sólo lo que trajo valor; el completo, todo el formulario.
    assert "líneas con valor" in html
    _, completo = obtener(
        servidor_local + "/formulario?" + urlencode({"ref": ref, "completo": "1"})
    )
    assert "Todas las líneas del formulario" in completo


def test_la_propuesta_se_rechaza_tambien_desde_la_web(servidor_local, monkeypatch):
    from bringmef29.modelos import PROPUESTA

    declaracion = DeclaracionF29(
        rut=Rut.parsear("11111111-1"),
        periodo=Periodo(2026, 8),
        procedencia=PROPUESTA,
        lineas=[LineaCodigo("091", Decimal("340000"))],
    )
    monkeypatch.setattr(flujo, "obtener", lambda *a, **k: flujo.ResultadoObtencion(declaracion))

    estado, html = postear(
        servidor_local, {"rut": "11.111.111-1", "clave": "x", "mes": "8", "anio": "2026"}
    )
    assert estado == 200
    assert "propuesta del SII" in html
    assert "TOTAL A PAGAR" not in html


# --------------------------------------------------------------------------- #
# Historial
# --------------------------------------------------------------------------- #


def test_historial_vacio_lo_dice(servidor_local):
    estado, html = obtener(servidor_local + "/historial")
    assert estado == 200
    assert "Todavía no hay consultas" in html


def test_repetir_la_misma_consulta_no_duplica(config, declaracion_guardada):
    servidor.historial.registrar(config, declaracion_guardada, {"Resumen en PDF": "a.pdf"})
    servidor.historial.registrar(config, declaracion_guardada, {"Resumen en PDF": "a.pdf"})
    assert len(historial.listar(config)) == 1


def test_un_codigo_distinto_es_otra_consulta(config, declaracion_guardada):
    historial.registrar(config, declaracion_guardada, {})
    otra = DeclaracionF29(
        rut=declaracion_guardada.rut,
        periodo=declaracion_guardada.periodo,
        procedencia=GUARDADA,
        lineas=[LineaCodigo(l.codigo, l.valor) for l in declaracion_guardada.lineas[:-1]]
        + [LineaCodigo("091", Decimal("999999"))],
    )
    entrada = historial.registrar(config, otra, {})
    consultas = historial.listar(config)
    assert len(consultas) == 2
    # La recién traída queda primera.
    assert consultas[0]["ref"] == entrada["ref"]


def test_el_historial_enlaza_cada_consulta(servidor_local, config, declaracion_guardada):
    entrada = historial.registrar(config, declaracion_guardada, {})
    _, html = obtener(servidor_local + "/historial")
    assert entrada["ref"] in html
    assert "Comercial Acme SpA" in html


def test_una_consulta_borrada_manda_de_vuelta_al_inicio(servidor_local, config):
    ref = "111111111-202608-deadbeef"
    estado, html = obtener(servidor_local + "/periodo?" + urlencode({"ref": ref}))
    assert estado == 200
    assert "Ingrese RUT" in html
    assert "Tráela de nuevo del SII" in html


# --------------------------------------------------------------------------- #
# Códigos
# --------------------------------------------------------------------------- #


def test_la_pantalla_de_codigos_lista_y_filtra(servidor_local):
    estado, html = obtener(servidor_local + "/codigos")
    assert estado == 200
    assert "538" in html and "537" in html

    _, filtrado = obtener(servidor_local + "/codigos?q=538")
    assert "538" in filtrado
    assert "2 código(s)" in filtrado  # el 538 y el que lo nombra en su glosa


# --------------------------------------------------------------------------- #
# Límites de acceso
# --------------------------------------------------------------------------- #


def test_rechaza_peticiones_con_otro_host(servidor_local):
    estado, _ = obtener(servidor_local + "/", {"Host": "contador.ejemplo.cl"})
    assert estado == 403


def test_no_sirve_archivos_fuera_del_directorio_de_salida(servidor_local):
    estado, _ = obtener(servidor_local + "/archivo?ruta=/etc/passwd")
    assert estado == 403


def test_sirve_lo_que_el_programa_genero(servidor_local, config):
    archivo = config.directorio_salida / "111111111" / "202608" / "aviso.pdf"
    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_bytes(b"%PDF-1.4 falso")
    estado, cuerpo = obtener(servidor_local + "/archivo?" + urlencode({"ruta": str(archivo)}))
    assert estado == 200
    assert cuerpo.startswith("%PDF")
