"""Consulta del F29 manejando el sitio del SII con un navegador real.

Es el camino robusto: en vez de adivinar endpoints, abre el sitio, se autentica
en el formulario real y deja que la aplicación del SII pida sus propios datos.
El programa escucha las respuestas JSON que pasan por la red y les aplica el
mismo parseo tolerante que el modo API, de modo que un cambio de esquema en el
SII no rompe la navegación.

De paso captura lo que el aviso al cliente necesita: una imagen de la pantalla
de la declaración y, cuando el SII lo ofrece, el PDF oficial del formulario.
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from ..modelos import DeclaracionF29, LineaCodigo, Periodo
from ..rut import Rut
from .errores import DeclaracionNoEncontrada, ErrorAutenticacion, RespuestaInesperada
from .f29_api import _extraer_lineas, _primer_valor, a_decimal

_log = logging.getLogger(__name__)

URL_LOGIN = "https://zeusr.sii.cl/AUT2000/InicioAutenticacion/IngresoRutClave.html"
URL_CONSULTA = "https://www4.sii.cl/sifmConsultaInternet/index.html?form=29&dest=sisadmin"

_RUTAS_CHROMIUM_CONOCIDAS = (
    "/opt/pw-browsers/chromium",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
)

_TEXTOS_CREDENCIAL_INVALIDA = (
    "clave incorrecta",
    "datos ingresados no son correctos",
    "rut o clave",
    "clave bloqueada",
    "usuario bloqueado",
)


def ruta_chromium(preferida: str = "") -> str | None:
    """Ubica un Chromium utilizable; ``None`` deja que Playwright use el suyo."""
    candidatas = [preferida, os.environ.get("BRINGMEF29_CHROMIUM", "")]
    candidatas += list(_RUTAS_CHROMIUM_CONOCIDAS)
    for candidata in candidatas:
        if candidata and Path(candidata).exists():
            return candidata
    return None


@contextmanager
def navegador(*, headless: bool = True, ejecutable: str = "", timeout_ms: int = 45000):
    """Abre Chromium y entrega una página lista para usar."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise RespuestaInesperada(
            "El modo navegador necesita Playwright. Instálalo con:\n"
            "  pip install playwright && playwright install chromium"
        ) from exc

    with sync_playwright() as pw:
        opciones: dict[str, Any] = {"headless": headless}
        if ruta := ruta_chromium(ejecutable):
            opciones["executable_path"] = ruta
        browser = pw.chromium.launch(**opciones)
        contexto = browser.new_context(
            locale="es-CL",
            viewport={"width": 1440, "height": 1000},
            accept_downloads=True,
        )
        contexto.set_default_timeout(timeout_ms)
        pagina = contexto.new_page()
        try:
            yield pagina
        finally:
            contexto.close()
            browser.close()


class ConsultaNavegador:
    """Sesión de navegador autenticada contra el SII."""

    def __init__(self, pagina, *, directorio_estado: Path, guardar_capturas: bool = True) -> None:
        self.pagina = pagina
        self.directorio_estado = Path(directorio_estado)
        self.guardar_capturas = guardar_capturas
        self._respuestas: list[Any] = []
        self.directorio_estado.mkdir(parents=True, exist_ok=True)
        pagina.on("response", self._registrar_respuesta)

    # -- captura de tráfico -------------------------------------------------
    def _registrar_respuesta(self, respuesta) -> None:
        url = respuesta.url
        if "sifmConsultaInternet" not in url and "sifm" not in url:
            return
        tipo = (respuesta.headers or {}).get("content-type", "")
        if "json" not in tipo.lower():
            return
        try:
            self._respuestas.append({"url": url, "json": respuesta.json()})
        except Exception:  # noqa: BLE001 - respuestas parciales o no-JSON reales
            _log.debug("Respuesta JSON ilegible desde %s", url)

    # -- pasos --------------------------------------------------------------
    def autenticar(self, rut: Rut, clave: str) -> None:
        pagina = self.pagina
        pagina.goto(URL_LOGIN, wait_until="domcontentloaded")
        pagina.fill("#rutcntr", rut.con_guion)
        pagina.fill("#clave", clave)
        pagina.click("#bt_ingresar")
        try:
            pagina.wait_for_load_state("networkidle")
        except Exception:  # noqa: BLE001 - el SII deja conexiones abiertas
            pagina.wait_for_timeout(2000)

        texto = (pagina.content() or "").lower()
        for senal in _TEXTOS_CREDENCIAL_INVALIDA:
            if senal in texto:
                self._capturar("login-fallido")
                raise ErrorAutenticacion(
                    "El SII rechazó el RUT o la clave tributaria. "
                    f"Revisa la captura en {self.directorio_estado}."
                )
        if "IngresoRutClave" in pagina.url:
            self._capturar("login-sin-avance")
            raise ErrorAutenticacion(
                "El login no avanzó (posible segundo factor o captcha). "
                f"Revisa la captura en {self.directorio_estado}. "
                "Puedes reintentar con --sin-headless para verlo en pantalla."
            )
        _log.info("Sesión SII abierta en el navegador para %s", rut.formateado)

    def consultar(self, rut: Rut, periodo: Periodo) -> DeclaracionF29:
        pagina = self.pagina
        self._respuestas.clear()
        pagina.goto(URL_CONSULTA, wait_until="domcontentloaded")
        pagina.wait_for_timeout(1500)

        self._completar_busqueda(rut, periodo)
        try:
            pagina.wait_for_load_state("networkidle")
        except Exception:  # noqa: BLE001
            pagina.wait_for_timeout(3000)
        pagina.wait_for_timeout(1500)

        declaracion = self._declaracion_desde_trafico(rut, periodo)
        if declaracion is None:
            declaracion = self._declaracion_desde_dom(rut, periodo)
        if declaracion is None:
            self._capturar("consulta-sin-datos")
            raise DeclaracionNoEncontrada(
                f"No se encontró un F29 presentado para {rut.formateado} en {periodo.etiqueta}. "
                f"Revisa la captura en {self.directorio_estado}."
            )
        return declaracion

    def _completar_busqueda(self, rut: Rut, periodo: Periodo) -> None:
        """Llena el formulario de búsqueda tolerando variaciones de la interfaz."""
        pagina = self.pagina
        self._seleccionar_si_existe(
            ["select[name='anoPeriodo']", "#anoPeriodo", "select#ano", "select[ng-model*='ano']"],
            str(periodo.anio),
        )
        self._seleccionar_si_existe(
            ["select[name='mesPeriodo']", "#mesPeriodo", "select#mes", "select[ng-model*='mes']"],
            str(periodo.mes),
        )
        for selector in ("#rutBuscar", "input[name='rutBuscar']", "input[ng-model*='rut']"):
            if pagina.locator(selector).count():
                try:
                    pagina.fill(selector, str(rut.cuerpo))
                except Exception:  # noqa: BLE001 - campo deshabilitado cuando consultas lo propio
                    pass
                break
        for selector in (
            "#btnConsultar",
            "button:has-text('Consultar')",
            "input[value='Consultar']",
            "a:has-text('Consultar')",
        ):
            if pagina.locator(selector).count():
                pagina.click(selector)
                return
        raise RespuestaInesperada(
            "No se encontró el botón de consulta en la pantalla del SII: el sitio cambió. "
            f"Revisa la captura en {self._capturar('sin-boton-consultar')}."
        )

    def _seleccionar_si_existe(self, selectores: list[str], valor: str) -> None:
        for selector in selectores:
            if self.pagina.locator(selector).count():
                for intento in (valor, valor.zfill(2)):
                    try:
                        self.pagina.select_option(selector, intento)
                        return
                    except Exception:  # noqa: BLE001 - opción con otro formato
                        continue
        _log.debug("No se pudo fijar %s en ninguno de %s", valor, selectores)

    # -- construcción del resultado ----------------------------------------
    def _declaracion_desde_trafico(self, rut: Rut, periodo: Periodo) -> DeclaracionF29 | None:
        for captura in reversed(self._respuestas):
            lineas = list(_extraer_lineas(captura["json"]))
            if len(lineas) < 2:
                continue
            crudo = captura["json"]
            return DeclaracionF29(
                rut=rut,
                periodo=periodo,
                folio=str(_primer_valor(crudo, ("folio", "numeroFolio", "folioDeclaracion")) or ""),
                estado=str(_primer_valor(crudo, ("estado", "glosaEstado", "descEstado")) or ""),
                razon_social=str(_primer_valor(crudo, ("razonSocial", "nombreContribuyente")) or ""),
                lineas=lineas,
                origen="navegador",
                url_comprobante=self.pagina.url,
                crudo={"respuestas": [r["url"] for r in self._respuestas], "detalle": crudo},
            )
        return None

    def _declaracion_desde_dom(self, rut: Rut, periodo: Periodo) -> DeclaracionF29 | None:
        """Último recurso: leer los códigos de la tabla renderizada."""
        texto = self.pagina.inner_text("body")
        lineas = list(_lineas_desde_texto(texto))
        if len(lineas) < 2:
            return None
        folio = ""
        if m := re.search(r"folio[^0-9]{0,20}(\d{6,})", texto, re.IGNORECASE):
            folio = m.group(1)
        return DeclaracionF29(
            rut=rut,
            periodo=periodo,
            folio=folio,
            lineas=lineas,
            origen="navegador",
            url_comprobante=self.pagina.url,
            crudo={"texto": texto[:20000]},
        )

    # -- evidencia para el cliente -----------------------------------------
    def capturar_comprobante(self, destino: Path) -> str:
        """Guarda una imagen de la pantalla de la declaración."""
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        self.pagina.screenshot(path=str(destino), full_page=True)
        _log.info("Captura del comprobante guardada en %s", destino)
        return str(destino)

    def descargar_pdf_oficial(self, destino: Path) -> str:
        """Intenta bajar el PDF del formulario que publica el SII.

        Devuelve la ruta, o cadena vacía si el SII no ofrece la descarga en esa
        pantalla (pasa con declaraciones antiguas o en mantención).
        """
        selectores = (
            "a:has-text('Comprobante')",
            "a:has-text('comprobante')",
            "button:has-text('Comprobante')",
            "a:has-text('PDF')",
            "a[href*='.pdf']",
        )
        for selector in selectores:
            if not self.pagina.locator(selector).count():
                continue
            try:
                with self.pagina.expect_download(timeout=15000) as espera:
                    self.pagina.locator(selector).first.click()
                descarga = espera.value
                destino = Path(destino)
                destino.parent.mkdir(parents=True, exist_ok=True)
                descarga.save_as(str(destino))
                _log.info("PDF oficial del SII guardado en %s", destino)
                return str(destino)
            except Exception as exc:  # noqa: BLE001 - el SII abre el PDF en pestaña a veces
                _log.debug("No se pudo descargar con %s: %s", selector, exc)
        return ""

    def _capturar(self, nombre: str) -> str:
        if not self.guardar_capturas:
            return ""
        marca = datetime.now().strftime("%Y%m%d-%H%M%S")
        destino = self.directorio_estado / f"{marca}-{nombre}.png"
        try:
            self.pagina.screenshot(path=str(destino), full_page=True)
        except Exception as exc:  # noqa: BLE001 - la página puede estar cerrada
            _log.debug("No se pudo capturar la pantalla: %s", exc)
            return ""
        return str(destino)


_LINEA_CODIGO = re.compile(r"\[?\s*(\d{2,3})\s*\]?\s*[-–:]?\s*([\d.,()\-]+)\s*$")


def _lineas_desde_texto(texto: str) -> Iterator[LineaCodigo]:
    """Lee pares ``código  valor`` de la tabla del F29 renderizada como texto."""
    vistos: set[str] = set()
    for fila in texto.splitlines():
        fila = fila.strip()
        if not fila:
            continue
        m = _LINEA_CODIGO.search(fila)
        if not m:
            continue
        codigo, bruto = m.group(1), m.group(2)
        valor = a_decimal(bruto)
        if valor is None:
            continue
        clave = codigo.lstrip("0") or "0"
        if clave in vistos:
            continue
        vistos.add(clave)
        glosa = fila[: m.start()].strip(" .:-–")
        yield LineaCodigo(codigo=codigo, valor=valor, glosa=glosa)


def obtener_declaracion(
    rut: Rut,
    clave: str,
    periodo: Periodo,
    *,
    headless: bool = True,
    ejecutable: str = "",
    timeout_ms: int = 45000,
    directorio_estado: Path = Path(".estado_sii"),
    directorio_salida: Path = Path("salida"),
    guardar_capturas: bool = True,
) -> tuple[DeclaracionF29, str, str]:
    """Flujo completo en navegador.

    Devuelve ``(declaración, ruta de la captura, ruta del PDF oficial o "")``.
    """
    with navegador(headless=headless, ejecutable=ejecutable, timeout_ms=timeout_ms) as pagina:
        consulta = ConsultaNavegador(
            pagina, directorio_estado=directorio_estado, guardar_capturas=guardar_capturas
        )
        consulta.autenticar(rut, clave)
        declaracion = consulta.consultar(rut, periodo)

        base = Path(directorio_salida) / rut.sin_formato / periodo.codigo
        captura = consulta.capturar_comprobante(base / "comprobante-sii.png")
        pdf_oficial = consulta.descargar_pdf_oficial(base / "f29-sii.pdf")
        return declaracion, captura, pdf_oficial
