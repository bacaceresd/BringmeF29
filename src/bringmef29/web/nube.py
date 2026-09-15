"""La misma aplicación, pero servida desde un contenedor en vez de tu equipo.

Esto cambia una premisa del programa y conviene tenerla a la vista: en local la
clave tributaria no sale del computador, mientras que aquí viaja por internet
hasta el servidor. Por eso este modo **no arranca sin contraseña de acceso**: un
formulario de RUT y clave del SII abierto en una URL pública es exactamente lo
que no debe existir.

Sobre el mismo servidor local se agregan tres cosas: escuchar en el puerto que
asigna la plataforma, exigir la contraseña antes de cualquier pantalla, y exigir
HTTPS.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from http.server import ThreadingHTTPServer
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlparse

from ..config import Config
from . import vistas
from .servidor import _Manejador

_log = logging.getLogger(__name__)

COOKIE = "bringmef29_sesion"
DURACION = 12 * 3600          # una jornada de trabajo
INTENTOS = 8                  # por dirección, antes de la espera
ESPERA = 300                  # cinco minutos de castigo


class ErrorDespliegue(RuntimeError):
    """Falta algo sin lo cual no se puede publicar de forma segura."""


def clave_de_acceso() -> str:
    """La contraseña que protege el despliegue. Sin ella no se levanta nada."""
    clave = os.environ.get("BRINGMEF29_ACCESO", "")
    if len(clave) < 12:
        raise ErrorDespliegue(
            "Falta BRINGMEF29_ACCESO, o es muy corta (mínimo 12 caracteres). "
            "Es la contraseña que protege la aplicación publicada: sin ella "
            "cualquiera que dé con la dirección tendría delante un formulario "
            "para entrar al SII."
        )
    return clave


def _firma(clave: str) -> bytes:
    """Llave para firmar la cookie, derivada de la contraseña.

    Derivarla en vez de sortearla mantiene la sesión válida aunque la plataforma
    levante otra instancia, y evita un segundo secreto que administrar.
    """
    return hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), b"bringmef29-cookie", 120_000)


def emitir(clave: str) -> str:
    vence = str(int(time.time()) + DURACION)
    sello = hmac.new(_firma(clave), vence.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{vence}.{sello}"


def vigente(galleta: str, clave: str) -> bool:
    vence, _, sello = (galleta or "").partition(".")
    if not vence.isdigit() or not sello:
        return False
    esperado = hmac.new(_firma(clave), vence.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sello, esperado):
        return False
    return int(vence) > time.time()


class _Portero(_Manejador):
    """El servidor local, con la puerta cerrada con llave."""

    acceso: str = ""
    fallos: dict[str, list] = {}

    # -- identidad de quien pide ----------------------------------------
    def _quien(self) -> str:
        reenviado = self.headers.get("X-Forwarded-For", "")
        return reenviado.split(",")[0].strip() or self.client_address[0]

    def _castigado(self) -> int:
        """Segundos que faltan para poder reintentar. Cero si puede."""
        intentos, desde = self.fallos.get(self._quien(), [0, 0.0])
        if intentos < INTENTOS:
            return 0
        return max(0, int(desde + ESPERA - time.time()))

    def _anotar_fallo(self) -> None:
        quien = self._quien()
        intentos, desde = self.fallos.get(quien, [0, 0.0])
        if time.time() - desde > ESPERA:
            intentos, desde = 0, time.time()
        self.fallos[quien] = [intentos + 1, desde or time.time()]

    # -- la puerta ------------------------------------------------------
    def _host_local(self) -> bool:
        # Publicado no hay «equipo local» que comprobar; la barrera es la
        # contraseña. Lo que sí se exige es que la conexión venga cifrada.
        protocolo = self.headers.get("X-Forwarded-Proto", "https")
        return protocolo == "https"

    def _autenticado(self) -> bool:
        galleta = SimpleCookie(self.headers.get("Cookie", "")).get(COOKIE)
        return bool(galleta) and vigente(galleta.value, self.acceso)

    def _pedir_entrada(self, error: str = "") -> None:
        espera = self._castigado()
        if espera:
            error = f"Demasiados intentos fallidos. Prueba de nuevo en {espera // 60 + 1} minutos."
        self._responder(vistas.entrar(error=error, bloqueado=bool(espera)), 401)

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_local():
            self._texto("Sólo por HTTPS", 403)
            return
        if not self._autenticado():
            self._pedir_entrada()
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_local():
            self._texto("Sólo por HTTPS", 403)
            return
        if urlparse(self.path).path == "/entrar":
            self._entrar()
            return
        if not self._autenticado():
            self._pedir_entrada()
            return
        super().do_POST()

    def _entrar(self) -> None:
        if self._castigado():
            self._pedir_entrada()
            return
        largo = int(self.headers.get("Content-Length") or 0)
        enviada = (parse_qs(self.rfile.read(largo).decode("utf-8")).get("acceso") or [""])[0]
        if not secrets.compare_digest(enviada, self.acceso):
            self._anotar_fallo()
            _log.warning("Intento de acceso fallido desde %s", self._quien())
            self._pedir_entrada("Contraseña incorrecta.")
            return
        self.fallos.pop(self._quien(), None)
        self.send_response(303)
        self.send_header("Location", "/")
        self.send_header(
            "Set-Cookie",
            f"{COOKIE}={emitir(self.acceso)}; Path=/; Max-Age={DURACION}; "
            f"HttpOnly; Secure; SameSite=Lax",
        )
        self.send_header("Content-Length", "0")
        self.end_headers()


def servir(config: Config, *, puerto: int | None = None) -> None:
    """Levanta la aplicación publicada. Falla de entrada si falta la contraseña."""
    _Portero.config = config
    _Portero.acceso = clave_de_acceso()
    puerto = puerto or int(os.environ.get("PORT", "8080"))
    servidor = ThreadingHTTPServer(("0.0.0.0", puerto), _Portero)  # noqa: S104
    _log.info("BringmeF29 publicado, escuchando en el puerto %s", puerto)
    try:
        servidor.serve_forever()
    finally:
        servidor.server_close()
