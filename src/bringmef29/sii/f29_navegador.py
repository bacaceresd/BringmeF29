"""Consulta del F29 manejando el sitio del SII con un navegador real.

Es el camino robusto y el único que alcanza los tres formularios que el SII
mantiene para un mismo período:

* la **propuesta** que el SII arma desde el Registro de Compras y Ventas,
* el **F29 guardado** por el contribuyente, que todavía no se envía,
* la **declaración presentada**, con folio.

En vez de adivinar endpoints, abre el sitio, se autentica en el formulario real
y deja que la aplicación del SII pida sus propios datos. El programa escucha las
respuestas JSON que pasan por la red y les aplica un parseo tolerante, de modo
que un cambio de esquema en el SII no rompe la navegación. Cuando el formulario
está en pantalla en modo edición, lee además los valores directo de los campos,
que es donde vive el F29 guardado.

De paso captura lo que el aviso al cliente necesita: una imagen de la pantalla y,
cuando el SII lo ofrece, el PDF oficial del formulario.
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from ..modelos import (
    GUARDADA,
    PRESENTADA,
    PROPUESTA,
    DeclaracionF29,
    LineaCodigo,
    Periodo,
)
from ..rut import Rut
from . import procedencia as clasificador
from .errores import (
    DeclaracionEsPropuesta,
    DeclaracionGuardadaNoEncontrada,
    DeclaracionNoEncontrada,
    ErrorAutenticacion,
    RespuestaInesperada,
)
from .f29_api import _extraer_lineas, _primer_valor, a_decimal

_log = logging.getLogger(__name__)

URL_LOGIN = "https://zeusr.sii.cl/AUT2000/InicioAutenticacion/IngresoRutClave.html"
# Consulta y seguimiento de declaraciones: sólo ve los F29 ya presentados.
URL_CONSULTA = "https://www4.sii.cl/sifmConsultaInternet/index.html?form=29&dest=sisadmin"
# Declarar y pagar: aquí viven la propuesta y el formulario guardado sin enviar.
URL_DECLARAR = "https://www4.sii.cl/sifmDeclaracionInternet/index.html?form=29&dest=sisadmin"

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

# Cómo entrar al formulario que el contribuyente guardó. Se prueban en orden y
# ninguno menciona la propuesta: entrar por ahí traería los datos del SII.
_ACCESOS_A_LO_GUARDADO = (
    "a:has-text('Continuar declaración')",
    "button:has-text('Continuar declaración')",
    "a:has-text('Recuperar declaración')",
    "button:has-text('Recuperar declaración')",
    "a:has-text('Declaración guardada')",
    "button:has-text('Declaración guardada')",
    "a:has-text('Continuar')",
    "button:has-text('Continuar')",
)

# Lo contrario: si el SII ofrece esto, es la propuesta y hay que no tocarla.
_ACCESOS_A_LA_PROPUESTA = (
    "button:has-text('Aceptar propuesta')",
    "a:has-text('Aceptar propuesta')",
    "button:has-text('Usar propuesta')",
    "a:has-text('Ver propuesta')",
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
        if "sifm" not in url:
            return
        tipo = (respuesta.headers or {}).get("content-type", "")
        if "json" not in tipo.lower():
            return
        try:
            self._respuestas.append({"url": url, "json": respuesta.json()})
        except Exception:  # noqa: BLE001 - respuestas parciales o no-JSON reales
            _log.debug("Respuesta JSON ilegible desde %s", url)

    # -- autenticación ------------------------------------------------------
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

    # -- F29 guardado por el contribuyente ----------------------------------
    def consultar_guardada(self, rut: Rut, periodo: Periodo) -> DeclaracionF29:
        """Trae el F29 que el contribuyente llenó y guardó, sin enviar.

        Entra por la aplicación de declaración y busca explícitamente la opción
        de continuar lo guardado. Si el SII sólo ofrece la propuesta, se detiene
        con :class:`DeclaracionEsPropuesta` en vez de devolver datos que el
        contribuyente nunca declaró.
        """
        pagina = self.pagina
        self._respuestas.clear()
        pagina.goto(URL_DECLARAR, wait_until="domcontentloaded")
        pagina.wait_for_timeout(1500)

        self._fijar_periodo(periodo)
        self._esperar_red()

        if not self._entrar_a_lo_guardado():
            if self._solo_hay_propuesta():
                self._capturar("solo-propuesta")
                raise DeclaracionEsPropuesta(
                    f"Para {rut.formateado} en {periodo.etiqueta} el SII sólo ofrece su "
                    "propuesta: no hay un F29 guardado por el contribuyente. "
                    f"Revisa la captura en {self.directorio_estado}."
                )
            self._capturar("sin-declaracion-guardada")
            raise DeclaracionGuardadaNoEncontrada(
                f"No se encontró un F29 guardado para {rut.formateado} en {periodo.etiqueta}. "
                "Si ya lo enviaste, pídelo con --fuente presentada. "
                f"Revisa la captura en {self.directorio_estado}."
            )

        self._esperar_red()
        declaracion = self._leer_formulario(rut, periodo, procedencia_esperada=GUARDADA)
        self._exigir_que_no_sea_propuesta(declaracion)
        return declaracion

    # -- F29 ya presentado --------------------------------------------------
    def consultar_presentada(self, rut: Rut, periodo: Periodo) -> DeclaracionF29:
        """Trae la declaración ya enviada al SII, con su folio."""
        pagina = self.pagina
        self._respuestas.clear()
        pagina.goto(URL_CONSULTA, wait_until="domcontentloaded")
        pagina.wait_for_timeout(1500)

        self._completar_busqueda(rut, periodo)
        self._esperar_red()

        declaracion = self._leer_formulario(rut, periodo, procedencia_esperada=PRESENTADA)
        self._exigir_que_no_sea_propuesta(declaracion)
        return declaracion

    # -- navegación ---------------------------------------------------------
    def _esperar_red(self) -> None:
        try:
            self.pagina.wait_for_load_state("networkidle")
        except Exception:  # noqa: BLE001 - el SII deja conexiones abiertas
            self.pagina.wait_for_timeout(3000)
        self.pagina.wait_for_timeout(1500)

    def _entrar_a_lo_guardado(self) -> bool:
        for selector in _ACCESOS_A_LO_GUARDADO:
            elemento = self.pagina.locator(selector)
            if not elemento.count():
                continue
            texto = clasificador.normalizar(elemento.first.inner_text() or "")
            if "propuesta" in texto:
                continue
            _log.info("Entrando al F29 guardado mediante: %s", selector)
            elemento.first.click()
            return True
        # Puede que el SII ya haya abierto el formulario guardado directamente.
        return self._hay_formulario_en_pantalla()

    def _solo_hay_propuesta(self) -> bool:
        if any(self.pagina.locator(s).count() for s in _ACCESOS_A_LA_PROPUESTA):
            return True
        return clasificador.clasificar(texto=self._texto_pagina(), url=self.pagina.url) == PROPUESTA

    def _hay_formulario_en_pantalla(self) -> bool:
        return bool(self.pagina.locator("input[name='codigo_538'], input#codigo_538, input[id^='codigo_']").count())

    def _fijar_periodo(self, periodo: Periodo) -> None:
        self._seleccionar_si_existe(
            ["select[name='anoPeriodo']", "#anoPeriodo", "select#ano", "select[ng-model*='ano']"],
            str(periodo.anio),
        )
        self._seleccionar_si_existe(
            ["select[name='mesPeriodo']", "#mesPeriodo", "select#mes", "select[ng-model*='mes']"],
            str(periodo.mes),
        )

    def _completar_busqueda(self, rut: Rut, periodo: Periodo) -> None:
        """Llena el formulario de búsqueda tolerando variaciones de la interfaz."""
        pagina = self.pagina
        self._fijar_periodo(periodo)
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

    # -- lectura del formulario --------------------------------------------
    def _leer_formulario(
        self, rut: Rut, periodo: Periodo, *, procedencia_esperada: str
    ) -> DeclaracionF29:
        """Lee los códigos de la pantalla, por el camino que dé resultado."""
        texto = self._texto_pagina()

        for extractor in (
            self._lineas_desde_campos,
            self._lineas_desde_trafico,
            lambda: list(_lineas_desde_texto(texto)),
        ):
            lineas = extractor()
            if len(lineas) >= 2:
                break
        else:
            self._capturar("formulario-ilegible")
            raise DeclaracionNoEncontrada(
                f"No se pudo leer ningún código del F29 de {rut.formateado} en "
                f"{periodo.etiqueta}. Revisa la captura en {self.directorio_estado}."
            )

        crudo = {
            "respuestas": [r["url"] for r in self._respuestas],
            "detalle": self._respuestas[-1]["json"] if self._respuestas else {},
        }
        folio = ""
        if m := re.search(r"folio[^0-9]{0,20}(\d{6,})", texto, re.IGNORECASE):
            folio = m.group(1)
        estado = str(_primer_valor(crudo, ("estado", "glosaEstado", "descEstado")) or "")

        procedencia = clasificador.clasificar(
            texto=texto, url=self.pagina.url, crudo=crudo, folio=folio, estado=estado
        )
        if procedencia == clasificador.PROCEDENCIA_DESCONOCIDA:
            # La pantalla no se delató, pero sabemos por dónde entramos.
            procedencia = procedencia_esperada

        return DeclaracionF29(
            rut=rut,
            periodo=periodo,
            folio=folio,
            estado=estado,
            razon_social=str(_primer_valor(crudo, ("razonSocial", "nombreContribuyente")) or ""),
            lineas=lineas,
            via="navegador",
            procedencia=procedencia,
            url_comprobante=self.pagina.url,
            crudo=crudo,
        )

    def _lineas_desde_campos(self) -> list[LineaCodigo]:
        """Lee los valores directo de los campos del formulario.

        Es el camino que importa para el F29 guardado: cuando el formulario está
        abierto en modo edición, lo que el contribuyente escribió está en los
        ``input``, no en una respuesta JSON de consulta.
        """
        try:
            campos = self.pagina.eval_on_selector_all(
                "input, textarea",
                """elementos => elementos.map(e => ({
                    nombre: e.name || e.id || '',
                    valor: e.value || ''
                }))""",
            )
        except Exception as exc:  # noqa: BLE001 - página cerrada o sin formulario
            _log.debug("No se pudieron leer los campos del formulario: %s", exc)
            return []
        return list(_lineas_desde_campos(campos))

    def _lineas_desde_trafico(self) -> list[LineaCodigo]:
        for captura in reversed(self._respuestas):
            lineas = list(_extraer_lineas(captura["json"]))
            if len(lineas) >= 2:
                return lineas
        return []

    def _texto_pagina(self) -> str:
        try:
            return self.pagina.inner_text("body")
        except Exception:  # noqa: BLE001 - página en transición
            return self.pagina.content() or ""

    def _exigir_que_no_sea_propuesta(self, declaracion: DeclaracionF29) -> None:
        if not declaracion.es_propuesta_del_sii:
            return
        self._capturar("es-propuesta")
        raise DeclaracionEsPropuesta(
            "Lo que quedó en pantalla es la propuesta que arma el SII desde el Registro "
            "de Compras y Ventas, no el F29 del contribuyente. No se generó ningún aviso. "
            f"Revisa la captura en {self.directorio_estado} y reintenta con --sin-headless."
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
        pantalla (pasa con el formulario guardado y con declaraciones antiguas).
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


# --------------------------------------------------------------------------- #
# Extractores
# --------------------------------------------------------------------------- #

_LINEA_CODIGO = re.compile(r"\[?\s*(\d{2,3})\s*\]?\s*[-–:]?\s*([\d.,()\-]+)\s*$")
# Nombres de campo del formulario del SII: codigo_538, cod538, c_538, form29_538…
_NOMBRE_CAMPO = re.compile(r"(?:^|[^0-9a-z])(?:codigo|cod|c|campo)?[_\-]?(\d{2,3})$", re.IGNORECASE)


def _lineas_desde_campos(campos: list[dict]) -> Iterator[LineaCodigo]:
    """Convierte los ``input`` del formulario en líneas código/valor."""
    vistos: set[str] = set()
    for campo in campos:
        nombre = str(campo.get("nombre") or "")
        bruto = campo.get("valor")
        if not nombre or bruto in (None, ""):
            continue
        m = _NOMBRE_CAMPO.search(nombre)
        if not m:
            continue
        valor = a_decimal(bruto)
        if valor is None:
            continue
        codigo = m.group(1)
        clave = codigo.lstrip("0") or "0"
        if clave in vistos:
            continue
        vistos.add(clave)
        yield LineaCodigo(codigo=codigo, valor=valor)


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


# --------------------------------------------------------------------------- #
# Flujo completo
# --------------------------------------------------------------------------- #


def obtener_declaracion(
    rut: Rut,
    clave: str,
    periodo: Periodo,
    *,
    fuente: str = "guardada",
    headless: bool = True,
    ejecutable: str = "",
    timeout_ms: int = 45000,
    directorio_estado: Path = Path(".estado_sii"),
    directorio_salida: Path = Path("salida"),
    guardar_capturas: bool = True,
) -> tuple[DeclaracionF29, str, str]:
    """Flujo completo en navegador.

    ``fuente`` elige qué formulario traer: ``guardada`` (el del contribuyente, sin
    enviar), ``presentada`` (la enviada, con folio) o ``auto`` (guardada y, si no
    hay, presentada).

    Devuelve ``(declaración, ruta de la captura, ruta del PDF oficial o "")``.
    """
    with navegador(headless=headless, ejecutable=ejecutable, timeout_ms=timeout_ms) as pagina:
        consulta = ConsultaNavegador(
            pagina, directorio_estado=directorio_estado, guardar_capturas=guardar_capturas
        )
        consulta.autenticar(rut, clave)

        if fuente == "presentada":
            declaracion = consulta.consultar_presentada(rut, periodo)
        elif fuente == "guardada":
            declaracion = consulta.consultar_guardada(rut, periodo)
        elif fuente == "auto":
            try:
                declaracion = consulta.consultar_guardada(rut, periodo)
            except (DeclaracionGuardadaNoEncontrada, DeclaracionEsPropuesta) as exc:
                _log.info("No hay F29 guardado (%s). Buscando la declaración presentada.", exc)
                declaracion = consulta.consultar_presentada(rut, periodo)
        else:
            raise ValueError(f"Fuente desconocida: {fuente!r} (usa guardada, presentada o auto)")

        base = Path(directorio_salida) / rut.sin_formato / periodo.codigo
        captura = consulta.capturar_comprobante(base / "comprobante-sii.png")
        pdf_oficial = consulta.descargar_pdf_oficial(base / "f29-sii.pdf")
        return declaracion, captura, pdf_oficial
