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

from ..config import Config, cargar_catalogo
from ..modelos import Contribuyente, DeclaracionF29
from ..sii.f29_navegador import ruta_chromium
from .formato import fecha_larga, pesos

_log = logging.getLogger(__name__)

DIR_RECURSOS = Path(__file__).parent.parent / "recursos"


class ErrorRender(RuntimeError):
    """No se pudo generar el PDF o la imagen."""


@dataclass
class Documentos:
    pdf: str = ""
    imagen: str = ""
    html: str = ""


class ConstructorDocumentos:
    """Genera los documentos del aviso a partir de una declaración."""

    def __init__(self, config: Config, *, catalogo: dict | None = None) -> None:
        self.config = config
        self.catalogo = catalogo if catalogo is not None else cargar_catalogo()
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
        html_aviso = self.entorno.get_template("aviso.html.j2").render(**contexto)
        html_tarjeta = self.entorno.get_template("tarjeta.html.j2").render(**contexto)

        base = f"F29-{declaracion.periodo.codigo}-{declaracion.rut.sin_formato}"
        documentos = Documentos()
        if guardar_html:
            ruta_html = carpeta / f"{base}.html"
            ruta_html.write_text(html_aviso, encoding="utf-8")
            documentos.html = str(ruta_html)

        with _pagina_chromium(self.config.sii.ruta_chromium) as pagina:
            documentos.pdf = self._a_pdf(pagina, html_aviso, carpeta / f"{base}.pdf")
            documentos.imagen = self._a_png(pagina, html_tarjeta, carpeta / f"{base}.png")
        return documentos

    # -- contexto de plantilla ---------------------------------------------
    def _contexto(
        self, declaracion: DeclaracionF29, contribuyente: Contribuyente, *, captura_sii: str = ""
    ) -> dict:
        razon_social = (
            contribuyente.razon_social
            or declaracion.razon_social
            or contribuyente.alias
        )
        remanente = declaracion.remanente_periodo_siguiente
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
            "hay_que_pagar": declaracion.hay_que_pagar,
            "monto_a_pagar": pesos(declaracion.monto_a_pagar),
            "remanente": pesos(remanente) if remanente and remanente > 0 else "",
            "vencimiento": fecha_larga(self._vencimiento(declaracion)),
            "emitido": fecha_larga(date.today()),
            "resumen": self._resumen(declaracion),
            "css": (DIR_RECURSOS / "aviso.css").read_text(encoding="utf-8"),
            "logo_uri": _a_data_uri(self.config.estudio.logo),
            "captura_uri": _a_data_uri(captura_sii),
            "contacto": contribuyente.nombre_contacto,
        }

    def _vencimiento(self, declaracion: DeclaracionF29) -> date:
        return declaracion.periodo.vencimiento_legal()

    def _resumen(self, declaracion: DeclaracionF29) -> list[dict]:
        """Filas del resumen: los códigos destacados que traiga la declaración."""
        glosas: dict[str, str] = self.catalogo.get("glosas", {})
        destacados: list[str] = self.catalogo.get("destacados", [])
        indice = {linea.codigo_normalizado: linea for linea in declaracion.lineas}

        filas = []
        for codigo in destacados:
            clave = str(codigo).lstrip("0") or "0"
            linea = indice.get(clave)
            if linea is None or linea.valor == 0:
                continue
            filas.append(
                {
                    "codigo": str(codigo).zfill(3),
                    "glosa": linea.glosa or glosas.get(str(codigo), f"Código {codigo}"),
                    "monto": pesos(linea.valor),
                }
            )
        return filas

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
        pagina.set_viewport_size({"width": 1080, "height": 1080})
        pagina.set_content(html, wait_until="load")
        pagina.screenshot(path=str(destino))
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
