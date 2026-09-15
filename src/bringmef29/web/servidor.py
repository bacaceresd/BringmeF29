"""Servidor de la aplicación local: una pantalla por URL, nada de tableros.

Corre en tu propia máquina y escucha sólo en ``127.0.0.1``. Eso no es un
detalle de implementación: la clave tributaria de un contribuyente da acceso
completo a su situación ante el SII, así que viaja del formulario al proceso
que la usa y nada más — no se guarda en disco, no entra a los registros y no
sale del equipo.

Usa la biblioteca estándar a propósito: un servidor de un solo usuario no
justifica sumar un framework, y menos dependencias es menos superficie por
donde se escape una credencial.
"""

from __future__ import annotations

import logging
import mimetypes
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from .. import cuadratura, flujo
from ..config import Config, ErrorConfig
from ..documentos import ConstructorDocumentos
from ..documentos.constructor import ErrorRender
from ..modelos import Contribuyente, DeclaracionF29, Periodo
from ..rut import Rut, RutInvalido
from ..sii.errores import ErrorSii
from . import historial, vistas

_log = logging.getLogger(__name__)

# Sólo se atienden peticiones cuyo Host sea el equipo local: cierra la puerta a
# que una página cualquiera del navegador le hable a este servidor.
_HOSTS_PERMITIDOS = {"localhost", "127.0.0.1", "[::1]"}

# El orden es el que se ve en pantalla: primero lo del cliente, después lo formal.
ETIQUETAS = [
    ("imagen", "Imagen del resumen · WhatsApp"),
    ("pdf", "Resumen en PDF"),
    ("formulario_pdf", "Formulario F29 compacto · PDF"),
    ("formulario_completo_pdf", "Formulario F29 completo · PDF"),
    ("formulario_excel", "Formulario F29 completo · Excel"),
]


class ErrorWeb(RuntimeError):
    """Algo que el usuario puede corregir desde el formulario."""


# --------------------------------------------------------------------------- #
# Lógica
# --------------------------------------------------------------------------- #


def consultar(config: Config, rut_texto: str, clave: str, periodo_texto: str, fuente: str) -> dict:
    """Trae el F29 del SII, genera los documentos y anota la consulta."""
    if not clave:
        raise ErrorWeb("Falta la clave tributaria.")
    try:
        rut = Rut.parsear(rut_texto)
    except RutInvalido as exc:
        raise ErrorWeb(str(exc)) from exc
    periodo = Periodo.parsear(periodo_texto) if periodo_texto else Periodo.anterior_a_hoy()

    # Si el RUT ya está configurado como cliente usamos sus datos; si no, se
    # consulta igual y el envío queda deshabilitado.
    try:
        contribuyente = config.cliente(rut.con_guion)
    except ErrorConfig:
        contribuyente = Contribuyente(alias=rut.sin_formato, rut=rut)
    contribuyente.clave_sii = clave

    resultado = flujo.obtener(config, contribuyente, periodo, fuente=fuente)
    declaracion = resultado.declaracion
    flujo.verificar_procedencia(declaracion)

    carpeta = historial.carpeta(config, declaracion)
    flujo.guardar_declaracion(config, declaracion)
    flujo.guardar_declaracion(config, declaracion, carpeta=carpeta)

    rutas, incidencia = generar_documentos(
        config, declaracion, contribuyente, carpeta, captura_sii=resultado.captura
    )
    entrada = historial.registrar(config, declaracion, rutas)
    return {"declaracion": declaracion, "entrada": entrada, "incidencia": incidencia}


def generar_documentos(
    config: Config,
    declaracion: DeclaracionF29,
    contribuyente: Contribuyente,
    carpeta: Path,
    *,
    captura_sii: str = "",
) -> tuple[dict, str]:
    """Arma los cinco archivos del aviso. Devuelve ``{etiqueta: ruta}`` y el aviso de fallo."""
    constructor = ConstructorDocumentos(config)
    reunidos: dict[str, str] = {}
    incidencia = ""
    try:
        aviso = constructor.construir(
            declaracion, contribuyente, captura_sii=captura_sii, destino=carpeta
        )
        form = constructor.construir_formulario(
            declaracion, contribuyente, destino=carpeta,
            compacto=True, completo=True, excel=True,
        )
        for documentos in (aviso, form):
            for campo, _ in ETIQUETAS:
                if valor := getattr(documentos, campo, ""):
                    reunidos[campo] = valor
    except (ErrorRender, OSError) as exc:
        _log.error("No se pudieron generar los documentos: %s", exc)
        incidencia = (f"El F29 se trajo bien, pero no se pudieron generar los archivos: {exc}. "
                      f"Revisa Chromium con «bringmef29 diagnostico».")
    return {etiqueta: reunidos.get(campo, "") for campo, etiqueta in ETIQUETAS}, incidencia


def declaracion_de(config: Config, ref: str) -> tuple[DeclaracionF29, dict]:
    """Relee una consulta del historial. Lanza :class:`ErrorWeb` si no está."""
    entrada = historial.buscar(config, ref)
    if not entrada:
        raise ErrorWeb("Esa consulta ya no está guardada. Tráela de nuevo del SII.")
    archivo = Path(entrada["carpeta"]) / "declaracion.json"
    if not archivo.exists():
        raise ErrorWeb("Falta el archivo de esa consulta. Tráela de nuevo del SII.")
    return flujo.cargar_declaracion(archivo), entrada


def _rutas_vigentes(entrada: dict) -> dict:
    """Las descargas que siguen existiendo en disco."""
    return {etiqueta: ruta for etiqueta, ruta in (entrada.get("rutas") or {}).items()
            if ruta and Path(ruta).exists()}


# --------------------------------------------------------------------------- #
# Servidor
# --------------------------------------------------------------------------- #


class _Manejador(BaseHTTPRequestHandler):
    config: Config = None            # type: ignore[assignment]
    server_version = "BringmeF29"
    sys_version = ""

    # -- utilidades -----------------------------------------------------
    def _responder(self, cuerpo: bytes, estado: int = 200, tipo: str = "text/html; charset=utf-8"):
        self.send_response(estado)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _redirigir(self, destino: str) -> None:
        self.send_response(303)
        self.send_header("Location", destino)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _texto(self, mensaje: str, estado: int) -> None:
        self._responder(mensaje.encode("utf-8"), estado, "text/plain; charset=utf-8")

    def _host_local(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        return host in _HOSTS_PERMITIDOS

    def log_message(self, formato: str, *args) -> None:
        # El log por defecto imprime la línea completa de la petición; aquí sólo
        # se registra el método y la ruta, nunca el cuerpo con la clave.
        _log.debug("%s %s", self.command, urlparse(self.path).path)

    # -- rutas ----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        if not self._host_local():
            self._texto("Host no permitido", 403)
            return
        url = urlparse(self.path)
        consulta = parse_qs(url.query)
        uno = lambda clave: (consulta.get(clave) or [""])[0]  # noqa: E731

        if url.path == "/":
            self._responder(vistas.consultar(self.config))
        elif url.path == "/periodo":
            self._pantalla_periodo(uno("ref"))
        elif url.path == "/formulario":
            self._pantalla_formulario(uno("ref"), bool(uno("completo")))
        elif url.path == "/historial":
            self._responder(vistas.historial(historial.listar(self.config)))
        elif url.path == "/codigos":
            self._responder(vistas.codigos(cuadratura.cargar_catalogo(), uno("q")))
        elif url.path == "/archivo":
            self._servir_archivo(uno("ruta"))
        else:
            self._texto("No encontrado", 404)

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_local():
            self._texto("Host no permitido", 403)
            return
        if urlparse(self.path).path != "/consultar":
            self._texto("No encontrado", 404)
            return

        largo = int(self.headers.get("Content-Length") or 0)
        campos = parse_qs(self.rfile.read(largo).decode("utf-8"))
        rut = (campos.get("rut") or [""])[0].strip()
        clave = (campos.get("clave") or [""])[0]
        fuente = (campos.get("fuente") or ["guardada"])[0]
        mes = (campos.get("mes") or [""])[0].strip()
        anio = (campos.get("anio") or [""])[0].strip()
        periodo = (campos.get("periodo") or [""])[0].strip()
        if not periodo and mes and anio:
            periodo = f"{anio}-{int(mes):02d}"
        devolver = {"rut": rut, "mes": mes, "anio": anio}

        try:
            datos = consultar(self.config, rut, clave, periodo, fuente)
        except (ErrorWeb, ErrorSii, ErrorConfig, ValueError) as exc:
            self._responder(vistas.consultar(self.config, error=str(exc), valores=devolver))
            return
        except Exception as exc:  # noqa: BLE001 - un fallo inesperado no debe tumbar el servidor
            _log.exception("Falla inesperada al consultar")
            self._responder(
                vistas.consultar(self.config, error=f"Error inesperado: {exc}", valores=devolver)
            )
            return
        finally:
            del clave

        # Redirigir deja el POST atrás: recargar la pantalla no reenvía la clave.
        self._redirigir("/periodo?" + urlencode({"ref": datos["entrada"]["ref"]}))

    # -- pantallas ------------------------------------------------------
    def _pantalla_periodo(self, ref: str) -> None:
        try:
            declaracion, entrada = declaracion_de(self.config, ref)
        except ErrorWeb as exc:
            self._responder(vistas.consultar(self.config, error=str(exc)))
            return
        self._responder(
            vistas.resumen(declaracion, ref, _rutas_vigentes(entrada))
        )

    def _pantalla_formulario(self, ref: str, completo: bool) -> None:
        try:
            declaracion, _ = declaracion_de(self.config, ref)
        except ErrorWeb as exc:
            self._responder(vistas.consultar(self.config, error=str(exc)))
            return
        self._responder(vistas.formulario(declaracion, ref, completo=completo))

    def _servir_archivo(self, texto: str) -> None:
        ruta = Path(texto)
        salida = self.config.directorio_salida.resolve()
        try:
            # Sólo se sirven archivos que el propio programa generó.
            ruta.resolve().relative_to(salida)
        except ValueError:
            self._texto("Ruta fuera del directorio de salida", 403)
            return
        if not ruta.is_file():
            self._texto("No encontrado", 404)
            return
        tipo = mimetypes.guess_type(ruta.name)[0] or "application/octet-stream"
        cuerpo = ruta.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Content-Disposition", f'attachment; filename="{ruta.name}"')
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(cuerpo)


def servir(config: Config, *, puerto: int = 8029, abrir: bool = True) -> None:
    """Levanta el servidor local y queda escuchando hasta Ctrl-C."""
    _Manejador.config = config
    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), _Manejador)
    url = f"http://127.0.0.1:{puerto}/"
    print(f"\n  BringmeF29 escuchando en {url}")
    print("  Sólo acepta conexiones desde este equipo. Ctrl-C para detener.\n")
    if abrir:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\n  Detenido.\n")
    finally:
        servidor.server_close()
