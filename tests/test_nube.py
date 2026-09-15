"""El despliegue publicado: sin contraseña no arranca, y sin cookie no muestra nada."""

import time
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener


class _SinSeguir(HTTPRedirectHandler):
    """Deja ver la redirección en vez de seguirla: lo que importa es la cookie."""

    def redirect_request(self, *_args, **_kwargs):
        return None

import pytest

from bringmef29.web import nube


@pytest.fixture
def acceso(monkeypatch):
    clave = "contrasena-de-prueba"
    monkeypatch.setenv("BRINGMEF29_ACCESO", clave)
    return clave


@pytest.fixture
def publicado(config, acceso):
    nube._Portero.config = config
    nube._Portero.acceso = acceso
    nube._Portero.fallos = {}
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), nube._Portero)
    Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()


def pedir(url, *, cookie="", metodo="GET", datos=None, proto="https"):
    cabeceras = {"X-Forwarded-Proto": proto}
    if cookie:
        cabeceras["Cookie"] = f"{nube.COOKIE}={cookie}"
    cuerpo = urlencode(datos).encode() if datos else None
    peticion = Request(url, data=cuerpo, headers=cabeceras, method=metodo)
    try:
        with build_opener(_SinSeguir).open(peticion, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace"), dict(exc.headers)


# --------------------------------------------------------------------------- #
# La contraseña es obligatoria
# --------------------------------------------------------------------------- #


def test_sin_contrasena_no_arranca(monkeypatch, config):
    monkeypatch.delenv("BRINGMEF29_ACCESO", raising=False)
    with pytest.raises(nube.ErrorDespliegue, match="BRINGMEF29_ACCESO"):
        nube.servir(config)


def test_una_contrasena_corta_tampoco_sirve(monkeypatch, config):
    monkeypatch.setenv("BRINGMEF29_ACCESO", "corta")
    with pytest.raises(nube.ErrorDespliegue, match="12 caracteres"):
        nube.servir(config)


# --------------------------------------------------------------------------- #
# La puerta
# --------------------------------------------------------------------------- #


def test_sin_cookie_pide_la_contrasena(publicado):
    estado, html, _ = pedir(publicado + "/")
    assert estado == 401
    assert "Contraseña" in html
    # Nada de la aplicación se filtra antes de entrar.
    assert "Ingrese RUT" not in html


@pytest.mark.parametrize("ruta", ["/", "/historial", "/codigos", "/periodo?ref=x", "/archivo?ruta=/etc/passwd"])
def test_ninguna_pantalla_se_ve_sin_entrar(publicado, ruta):
    assert pedir(publicado + ruta)[0] == 401


def test_sin_https_no_atiende(publicado, acceso):
    estado, _, _ = pedir(publicado + "/", cookie=nube.emitir(acceso), proto="http")
    assert estado == 403


def test_con_la_contrasena_correcta_entrega_la_cookie(publicado, acceso):
    estado, _, cabeceras = pedir(
        publicado + "/entrar", metodo="POST", datos={"acceso": acceso}
    )
    assert estado == 303
    galleta = cabeceras["Set-Cookie"]
    assert "HttpOnly" in galleta and "Secure" in galleta and "SameSite" in galleta


def test_con_la_cookie_se_ve_la_aplicacion(publicado, acceso):
    estado, html, _ = pedir(publicado + "/", cookie=nube.emitir(acceso))
    assert estado == 200
    assert "Ingrese RUT" in html


def test_una_cookie_inventada_no_sirve(publicado):
    futuro = str(int(time.time()) + 3600)
    estado, _, _ = pedir(publicado + "/", cookie=f"{futuro}.{'0' * 64}")
    assert estado == 401


def test_una_cookie_vencida_no_sirve(publicado, acceso):
    import hashlib
    import hmac

    pasado = str(int(time.time()) - 10)
    sello = hmac.new(nube._firma(acceso), pasado.encode(), hashlib.sha256).hexdigest()
    assert pedir(publicado + "/", cookie=f"{pasado}.{sello}")[0] == 401


def test_la_contrasena_equivocada_no_entra(publicado):
    estado, html, cabeceras = pedir(
        publicado + "/entrar", metodo="POST", datos={"acceso": "la-que-no-es"}
    )
    assert estado == 401
    assert "incorrecta" in html
    assert "Set-Cookie" not in cabeceras


def test_probar_contrasenas_a_ciegas_se_frena(publicado):
    for _ in range(nube.INTENTOS):
        pedir(publicado + "/entrar", metodo="POST", datos={"acceso": "mala"})
    estado, html, _ = pedir(publicado + "/entrar", metodo="POST", datos={"acceso": "mala"})
    assert estado == 401
    assert "Demasiados intentos" in html
