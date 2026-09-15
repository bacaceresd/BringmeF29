"""Arma el aviso de pago: HTML → PDF (correo) y HTML → PNG (WhatsApp).

El render se hace con el mismo Chromium que usa el modo navegador, así el
proyecto no arrastra un motor de PDF adicional con dependencias de sistema.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .. import formulario as armador_formulario
from .. import resumen as armador_resumen
from ..calendario import fecha_con_dia_semana
from ..config import Config
from .. import cuadratura
from ..modelos import Contribuyente, DeclaracionF29
from ..sii.f29_navegador import ruta_chromium
from .formato import fecha_larga

_log = logging.getLogger(__name__)

DIR_RECURSOS = Path(__file__).parent.parent / "recursos"


class ErrorRender(RuntimeError):
    """No se pudo generar el PDF o la imagen."""


@dataclass
class Documentos:
    """Rutas de lo generado. El resumen va por WhatsApp; el formulario, por correo."""

    pdf: str = ""                  # resumen, A4
    imagen: str = ""               # resumen, PNG para WhatsApp
    html: str = ""
    formulario_pdf: str = ""       # F29 por secciones, sólo líneas con valor
    formulario_completo_pdf: str = ""
    formulario_excel: str = ""

    @property
    def para_correo(self) -> list[str]:
        """Lo formal: el formulario y, si se generó, su versión completa."""
        return [p for p in (self.formulario_pdf, self.formulario_completo_pdf,
                            self.formulario_excel, self.pdf) if p]

    @property
    def para_whatsapp(self) -> list[str]:
        """Lo informal: la imagen del resumen."""
        return [p for p in (self.imagen,) if p]


class ConstructorDocumentos:
    """Genera los documentos del aviso a partir de una declaración."""

    def __init__(self, config: Config, *, layout: dict | None = None) -> None:
        self.config = config
        self.layout = layout if layout is not None else armador_resumen.cargar_layout()
        self.entorno = Environment(
            loader=FileSystemLoader(str(DIR_RECURSOS)),
            autoescape=select_autoescape(["html", "xml", "j2"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    # -- API pública --------------------------------------------------------
    def construir(
        self,
        declaracion: DeclaracionF29,
        contribuyente: Contribuyente,
        *,
        captura_sii: str = "",
        destino: Path | None = None,
        guardar_html: bool = False,
    ) -> Documentos:
        """Genera PDF e imagen y devuelve sus rutas."""
        carpeta = Path(
            destino
            or self.config.directorio_salida / declaracion.rut.sin_formato / declaracion.periodo.codigo
        )
        carpeta.mkdir(parents=True, exist_ok=True)

        contexto = self._contexto(declaracion, contribuyente, captura_sii=captura_sii)
        plantilla = self.entorno.get_template("aviso.html.j2")
        html_aviso = plantilla.render(**contexto)
        # La imagen es la misma tabla, con el cuerpo en modo "imagen".
        html_imagen = plantilla.render(**contexto).replace("<body>", '<body class="imagen">')

        base = f"F29-{declaracion.periodo.codigo}-{declaracion.rut.sin_formato}"
        documentos = Documentos()
        if guardar_html:
            ruta_html = carpeta / f"{base}.html"
            ruta_html.write_text(html_aviso, encoding="utf-8")
            documentos.html = str(ruta_html)

        with _pagina_chromium(self.config.sii.ruta_chromium) as pagina:
            documentos.pdf = self._a_pdf(pagina, html_aviso, carpeta / f"{base}.pdf")
            documentos.imagen = self._a_png(pagina, html_imagen, carpeta / f"{base}.png")
        return documentos

    # -- formulario F29 -----------------------------------------------------
    def construir_formulario(
        self,
        declaracion: DeclaracionF29,
        contribuyente: Contribuyente,
        *,
        destino: Path | None = None,
        compacto: bool = True,
        completo: bool = False,
        excel: bool = False,
        guardar_html: bool = False,
    ) -> Documentos:
        """Genera el F29 por secciones en los formatos pedidos."""
        carpeta = Path(
            destino
            or self.config.directorio_salida / declaracion.rut.sin_formato / declaracion.periodo.codigo
        )
        carpeta.mkdir(parents=True, exist_ok=True)
        base = f"F29-{declaracion.periodo.codigo}-{declaracion.rut.sin_formato}"
        documentos = Documentos()

        plantilla = self.entorno.get_template("formulario.html.j2")
        paginas: list[tuple[str, Path]] = []

        if compacto:
            html = plantilla.render(
                **self._contexto_formulario(declaracion, contribuyente, completo=False)
            )
            paginas.append((html, carpeta / f"{base}-formulario.pdf"))
            if guardar_html:
                (carpeta / f"{base}-formulario.html").write_text(html, encoding="utf-8")
        if completo:
            html = plantilla.render(
                **self._contexto_formulario(declaracion, contribuyente, completo=True)
            )
            paginas.append((html, carpeta / f"{base}-formulario-completo.pdf"))

        if paginas:
            with _pagina_chromium(self.config.sii.ruta_chromium) as pagina:
                for html, ruta in paginas:
                    self._a_pdf(pagina, html, ruta)
            if compacto:
                documentos.formulario_pdf = str(paginas[0][1])
            if completo:
                documentos.formulario_completo_pdf = str(paginas[-1][1])

        if excel:
            from .excel import exportar

            documentos.formulario_excel = exportar(
                armador_formulario.construir(declaracion, completo=True),
                carpeta / f"{base}-formulario.xlsx",
                estudio=self.config.estudio.nombre,
                vencimiento=fecha_con_dia_semana(self._vencimiento(declaracion, contribuyente)),
            )
        return documentos

    def _contexto_formulario(
        self, declaracion: DeclaracionF29, contribuyente: Contribuyente, *, completo: bool
    ) -> dict:
        vence = self._vencimiento(declaracion, contribuyente)
        return {
            "estudio": self.config.estudio,
            "periodo": declaracion.periodo,
            "rut": declaracion.rut.formateado,
            "razon_social": (contribuyente.razon_social or declaracion.razon_social
                             or contribuyente.alias),
            "folio": declaracion.folio,
            "procedencia_glosa": declaracion.procedencia_glosa,
            "es_propuesta_del_sii": declaracion.es_propuesta_del_sii,
            "formulario": armador_formulario.construir(declaracion, completo=completo),
            "monto": armador_formulario.monto,
            "monto_a_pagar": declaracion.monto_a_pagar,
            "hay_que_pagar": declaracion.hay_que_pagar,
            "vencimiento_texto": f"{fecha_con_dia_semana(vence)}, 23:59 hrs",
            "descuadres": [str(d) for d in cuadratura.verificar(declaracion)],
            "emitido": fecha_larga(date.today()),
            "css": (DIR_RECURSOS / "formulario.css").read_text(encoding="utf-8"),
            "logo_uri": _a_data_uri(self.config.estudio.logo),
        }

    # -- contexto de plantilla ---------------------------------------------
    def _contexto(
        self, declaracion: DeclaracionF29, contribuyente: Contribuyente, *, captura_sii: str = ""
    ) -> dict:
        razon_social = (
            contribuyente.razon_social or declaracion.razon_social or contribuyente.alias
        )
        vence = self._vencimiento(declaracion, contribuyente)
        resumen = armador_resumen.construir(
            declaracion,
            layout=self.layout,
            vencimiento_texto=f"{fecha_con_dia_semana(vence)} - 23:59 hrs",
        )
        return {
            "estudio": self.config.estudio,
            "pago": self.config.pago,
            "periodo": declaracion.periodo,
            "rut": declaracion.rut.formateado,
            "razon_social": razon_social,
            "folio": declaracion.folio,
            "estado": declaracion.estado,
            "procedencia": declaracion.procedencia,
            "procedencia_glosa": declaracion.procedencia_glosa,
            "es_propuesta_del_sii": declaracion.es_propuesta_del_sii,
            "resumen": resumen,
            "monto": armador_resumen.monto_contable,
            "emitido": fecha_larga(date.today()),
            "css": (DIR_RECURSOS / "aviso.css").read_text(encoding="utf-8"),
            "logo_uri": _a_data_uri(self.config.estudio.logo),
            "captura_uri": _a_data_uri(captura_sii),
            "contacto": contribuyente.nombre_contacto,
        }

    def _vencimiento(self, declaracion: DeclaracionF29, contribuyente: Contribuyente) -> date:
        return declaracion.periodo.vencimiento_legal(
            facturador_electronico=contribuyente.facturador_electronico
        )

    # -- render -------------------------------------------------------------
    @staticmethod
    def _a_pdf(pagina, html: str, destino: Path) -> str:
        pagina.set_content(html, wait_until="load")
        pagina.emulate_media(media="print")
        pagina.pdf(
            path=str(destino),
            format="A4",
            print_background=True,
            margin={"top": "14mm", "bottom": "14mm", "left": "13mm", "right": "13mm"},
        )
        _log.info("PDF del aviso generado en %s", destino)
        return str(destino)

    @staticmethod
    def _a_png(pagina, html: str, destino: Path) -> str:
        pagina.emulate_media(media="screen")
        pagina.set_viewport_size({"width": 820, "height": 900})
        pagina.set_content(html, wait_until="load")
        # full_page deja la tabla completa aunque sea más alta que la ventana.
        pagina.screenshot(path=str(destino), full_page=True)
        _log.info("Imagen para WhatsApp generada en %s", destino)
        return str(destino)


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #


class _PaginaChromium:
    """Context manager que abre Chromium sólo para renderizar."""

    def __init__(self, ejecutable: str = "") -> None:
        self.ejecutable = ejecutable
        self._pw = None
        self._browser = None
        self._contexto = None

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise ErrorRender(
                "Generar el PDF necesita Playwright. Instálalo con:\n"
                "  pip install playwright && playwright install chromium"
            ) from exc
        self._pw = sync_playwright().start()
        opciones = {"headless": True}
        if ruta := ruta_chromium(self.ejecutable):
            opciones["executable_path"] = ruta
        self._browser = self._pw.chromium.launch(**opciones)
        self._contexto = self._browser.new_context(locale="es-CL")
        return self._contexto.new_page()

    def __exit__(self, *_exc) -> None:
        for recurso, cerrar in (
            (self._contexto, "close"),
            (self._browser, "close"),
            (self._pw, "stop"),
        ):
            if recurso is not None:
                try:
                    getattr(recurso, cerrar)()
                except Exception:  # noqa: BLE001 - cierre best-effort
                    pass


def _pagina_chromium(ejecutable: str = "") -> _PaginaChromium:
    return _PaginaChromium(ejecutable)


def _a_data_uri(ruta: str | Path | None) -> str:
    """Incrusta una imagen en el HTML; Chromium no puede leer rutas locales aquí."""
    if not ruta:
        return ""
    archivo = Path(ruta)
    if not archivo.exists():
        _log.warning("No se encontró la imagen %s; se omite del documento.", archivo)
        return ""
    tipo, _ = mimetypes.guess_type(archivo.name)
    tipo = tipo or "image/png"
    datos = base64.b64encode(archivo.read_bytes()).decode("ascii")
    return f"data:{tipo};base64,{datos}"
