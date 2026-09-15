"""Autenticación con RUT y clave tributaria en el SII (vía HTTP, sin navegador).

El SII no publica una API de autenticación: el login real es un POST al CGI
histórico ``CAutInicio.cgi``, que responde con cookies de sesión. Este módulo
replica ese POST y verifica que la sesión haya quedado abierta.

Cuando el SII cambia el formulario —cosa que ocurre— este camino falla de forma
explícita y el flujo cae al modo navegador (:mod:`bringmef29.sii.f29_navegador`),
que usa el sitio real y por eso aguanta mejor los cambios.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

from ..rut import Rut
from .errores import ErrorAutenticacion, RespuestaInesperada

_log = logging.getLogger(__name__)

URL_LOGIN = "https://zeusr.sii.cl/cgi_AUT2000/CAutInicio.cgi"
URL_HOME = "https://misiir.sii.cl/cgi_misii/siihome.cgi"
AGENTE = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Frases que el SII muestra cuando las credenciales no sirven.
_SENALES_DE_FALLA = (
    "clave incorrecta",
    "rut o clave",
    "datos ingresados no son correctos",
    "no coincide",
    "usuario bloqueado",
    "clave bloqueada",
    "intentos fallidos",
    "debe ingresar su clave",
)
# Frases que sólo aparecen cuando ya estás dentro.
_SENALES_DE_EXITO = (
    "mi sii",
    "cerrar sesi",
    "siihome",
)


@dataclass
class SesionSii:
    """Sesión autenticada. Envuelve la ``requests.Session`` con sus cookies."""

    rut: Rut
    http: requests.Session

    @property
    def cookies(self) -> dict[str, str]:
        return {c.name: c.value for c in self.http.cookies}

    def cerrar(self) -> None:
        self.http.close()

    def __enter__(self) -> "SesionSii":
        return self

    def __exit__(self, *_exc) -> None:
        self.cerrar()


def nueva_sesion_http(timeout: int = 45) -> requests.Session:
    sesion = requests.Session()
    sesion.headers.update(
        {
            "User-Agent": AGENTE,
            "Accept-Language": "es-CL,es;q=0.9",
        }
    )
    sesion.request = _con_timeout(sesion.request, timeout)  # type: ignore[method-assign]
    return sesion


def _con_timeout(metodo, timeout: int):
    def envoltura(*args, **kwargs):
        kwargs.setdefault("timeout", timeout)
        return metodo(*args, **kwargs)

    return envoltura


def autenticar(rut: Rut, clave: str, *, referencia: str = URL_HOME, timeout: int = 45) -> SesionSii:
    """Inicia sesión en el SII y devuelve la sesión con cookies.

    Lanza :class:`ErrorAutenticacion` si el SII rechaza las credenciales y
    :class:`RespuestaInesperada` si la respuesta no se pudo clasificar.
    """
    http = nueva_sesion_http(timeout)
    # Visitar el formulario primero deja las cookies previas que el CGI espera.
    try:
        http.get("https://zeusr.sii.cl/AUT2000/InicioAutenticacion/IngresoRutClave.html")
    except requests.RequestException as exc:
        _log.debug("No se pudo precargar el formulario de login: %s", exc)

    formulario = {
        "rut": str(rut.cuerpo),
        "dv": rut.dv,
        "referencia": referencia,
        "411": "",
        "rutcntr": rut.sin_formato,
        "clave": clave,
    }
    try:
        respuesta = http.post(
            URL_LOGIN,
            data=formulario,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://zeusr.sii.cl",
                "Referer": "https://zeusr.sii.cl/AUT2000/InicioAutenticacion/IngresoRutClave.html",
            },
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        raise RespuestaInesperada(f"No se pudo contactar el login del SII: {exc}") from exc

    _clasificar_respuesta_login(respuesta.text, respuesta.status_code, http)
    _log.info("Sesión SII abierta para %s", rut.formateado)
    return SesionSii(rut=rut, http=http)


def _clasificar_respuesta_login(html: str, estado: int, http: requests.Session) -> None:
    texto = _texto_plano(html).lower()

    for senal in _SENALES_DE_FALLA:
        if senal in texto:
            raise ErrorAutenticacion(
                "El SII rechazó las credenciales. Verifica el RUT y la clave tributaria; "
                "si la clave está bloqueada, hay que recuperarla en sii.cl."
            )

    tiene_cookie_sesion = any(
        nombre.upper() in {"TOKEN", "CAUT", "NETSCAPE_LIVEWIRE.LOCALE", "S2_TOKEN"}
        for nombre in (c.name for c in http.cookies)
    )
    if tiene_cookie_sesion or any(senal in texto for senal in _SENALES_DE_EXITO):
        return

    if estado >= 400:
        raise RespuestaInesperada(f"El login del SII respondió HTTP {estado}.")
    raise RespuestaInesperada(
        "El login del SII respondió algo no reconocible (posible cambio del sitio o "
        "segundo factor de autenticación). Usa --modo navegador para ver qué ocurre."
    )


def _texto_plano(html: str) -> str:
    try:
        return BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    except Exception:  # noqa: BLE001 - lxml puede faltar o el HTML venir roto
        return html
