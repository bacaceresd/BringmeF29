"""Orquestador: del SII al aviso enviado.

Un solo recorrido: autenticar, traer el F29 del período, armar los documentos y
despacharlos por correo y WhatsApp. Cada paso es opcional para poder detenerse
donde haga falta (por ejemplo, generar el PDF y revisarlo antes de enviar).
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from pathlib import Path

from .config import Config
from .documentos import ConstructorDocumentos
from .envio.correo import EnviadorCorreo, ErrorEnvioCorreo
from .envio.whatsapp import EnviadorWhatsApp, ErrorEnvioWhatsApp
from .modelos import (
    PROCEDENCIA_DESCONOCIDA,
    AvisoPago,
    Contribuyente,
    DeclaracionF29,
    LineaCodigo,
    Periodo,
)
from .rut import Rut
from .sii import errores as errores_sii
from .sii.f29_api import ClienteF29Api
from .sii.f29_navegador import obtener_declaracion as obtener_con_navegador
from .sii.sesion import autenticar

FUENTES = ("guardada", "presentada", "auto")

_log = logging.getLogger(__name__)


class ResultadoObtencion:
    """Declaración traída del SII junto con la evidencia capturada."""

    def __init__(self, declaracion: DeclaracionF29, captura: str = "", pdf_oficial: str = "") -> None:
        self.declaracion = declaracion
        self.captura = captura
        self.pdf_oficial = pdf_oficial


# --------------------------------------------------------------------------- #
# Obtención
# --------------------------------------------------------------------------- #


def obtener(
    config: Config,
    contribuyente: Contribuyente,
    periodo: Periodo,
    *,
    fuente: str = "",
    modo: str = "",
    headless: bool | None = None,
) -> ResultadoObtencion:
    """Trae el F29 del período.

    ``fuente`` elige **cuál** de los formularios del SII se lee:

    ``guardada``
        El F29 que el contribuyente llenó y guardó, sin enviar. Es el valor por
        defecto: es la versión del contador, no la del SII.
    ``presentada``
        La declaración ya enviada, con folio.
    ``auto``
        La guardada y, si no existe, la presentada.

    ``modo`` elige **cómo** se lee. La vía API sólo alcanza las declaraciones
    presentadas; el formulario guardado vive en la aplicación de declaración y
    requiere navegador, así que pedir ``guardada`` por API es un error.
    """
    fuente = (fuente or config.sii.fuente or "guardada").lower()
    if fuente not in FUENTES:
        raise ValueError(f"Fuente desconocida: {fuente!r} (usa {', '.join(FUENTES)})")

    modo = (modo or config.sii.modo or "auto").lower()
    if modo not in ("auto", "api", "navegador"):
        raise ValueError(f"Modo de obtención desconocido: {modo!r} (usa auto, api o navegador)")

    clave = config.clave_sii(contribuyente)
    headless = config.sii.headless if headless is None else headless

    if modo == "api" and fuente != "presentada":
        raise ValueError(
            f"La vía API sólo alcanza las declaraciones presentadas, y pediste "
            f"la fuente '{fuente}'. Usa --modo navegador, o --fuente presentada."
        )

    if modo == "navegador" or fuente != "presentada":
        # El F29 guardado sólo se alcanza con el navegador.
        return _obtener_navegador(config, contribuyente, periodo, clave, headless, fuente)
    if modo == "api":
        return ResultadoObtencion(_obtener_api(config, contribuyente, periodo, clave))

    try:
        return ResultadoObtencion(_obtener_api(config, contribuyente, periodo, clave))
    except errores_sii.ErrorAutenticacion:
        raise
    except errores_sii.ErrorSii as exc:
        _log.warning("La vía API falló (%s). Reintentando con el navegador.", exc)
        return _obtener_navegador(config, contribuyente, periodo, clave, headless, fuente)


def _obtener_api(
    config: Config, contribuyente: Contribuyente, periodo: Periodo, clave: str
) -> DeclaracionF29:
    with autenticar(contribuyente.rut, clave, timeout=config.sii.timeout_ms // 1000) as sesion:
        return ClienteF29Api(sesion).obtener(contribuyente.rut, periodo)


def _obtener_navegador(
    config: Config,
    contribuyente: Contribuyente,
    periodo: Periodo,
    clave: str,
    headless: bool,
    fuente: str = "guardada",
) -> ResultadoObtencion:
    declaracion, captura, pdf_oficial = obtener_con_navegador(
        contribuyente.rut,
        clave,
        periodo,
        fuente=fuente,
        headless=headless,
        ejecutable=config.sii.ruta_chromium,
        timeout_ms=config.sii.timeout_ms,
        directorio_estado=Path(config.sii.directorio_estado),
        directorio_salida=config.directorio_salida,
        guardar_capturas=config.sii.guardar_capturas,
    )
    return ResultadoObtencion(declaracion, captura, pdf_oficial)


# --------------------------------------------------------------------------- #
# Guardia de procedencia
# --------------------------------------------------------------------------- #


def verificar_procedencia(declaracion: DeclaracionF29, *, permitir_propuesta: bool = False) -> None:
    """Se niega a seguir si lo que se leyó no es el F29 del contribuyente.

    El costo de equivocarse es asimétrico: cobrarle a un cliente el monto de la
    propuesta del SII —que no lleva sus PPM, retenciones ni remanentes— es un
    error que llega a su bolsillo. Ante una procedencia que no se pudo
    determinar, esto se detiene en vez de adivinar.
    """
    if declaracion.es_propuesta_del_sii:
        if permitir_propuesta:
            _log.warning(
                "Se continúa con la PROPUESTA DEL SII por pedido explícito: los montos "
                "no son los que declaró el contribuyente."
            )
            return
        raise errores_sii.DeclaracionEsPropuesta(
            "Lo que se leyó es la propuesta del SII, no el F29 del contribuyente. "
            "No se generó ningún aviso. Si de verdad quieres usar la propuesta, "
            "repite con --permitir-propuesta."
        )
    if declaracion.procedencia == PROCEDENCIA_DESCONOCIDA:
        raise errores_sii.RespuestaInesperada(
            "No se pudo determinar si el formulario leído es el del contribuyente o la "
            "propuesta del SII, así que no se generó ningún aviso. Revísalo con:\n"
            "  bringmef29 traer <cliente> --modo navegador --sin-headless -v"
        )
    _log.info("Procedencia verificada: %s", declaracion.procedencia_glosa)


# --------------------------------------------------------------------------- #
# Flujo completo
# --------------------------------------------------------------------------- #


def procesar(
    config: Config,
    referencia_cliente: str,
    periodo: Periodo,
    *,
    fuente: str = "",
    modo: str = "",
    headless: bool | None = None,
    permitir_propuesta: bool = False,
    enviar_correo: bool = True,
    enviar_whatsapp: bool = True,
    simular_envio: bool = False,
    solo_documentos: bool = False,
    destinatarios: list[str] | None = None,
    guardar_html: bool = False,
    desde_archivo: str = "",
) -> AvisoPago:
    """Ejecuta el flujo completo para un cliente y período."""
    contribuyente = config.cliente(referencia_cliente)

    if desde_archivo:
        declaracion = cargar_declaracion(desde_archivo)
        captura, pdf_oficial = "", ""
    else:
        resultado = obtener(
            config, contribuyente, periodo, fuente=fuente, modo=modo, headless=headless
        )
        declaracion, captura, pdf_oficial = (
            resultado.declaracion,
            resultado.captura,
            resultado.pdf_oficial,
        )
        guardar_declaracion(config, declaracion)

    # Nada se genera ni se envía hasta saber que el formulario es el del
    # contribuyente y no la propuesta del SII.
    verificar_procedencia(declaracion, permitir_propuesta=permitir_propuesta)

    documentos = ConstructorDocumentos(config).construir(
        declaracion, contribuyente, captura_sii=captura, guardar_html=guardar_html
    )

    aviso = AvisoPago(
        declaracion=declaracion,
        contribuyente=contribuyente,
        pdf=documentos.pdf,
        imagen=documentos.imagen,
        captura_sii=captura,
        comprobante_sii=pdf_oficial,
    )
    if solo_documentos:
        return aviso

    adjuntos = [p for p in (documentos.pdf, documentos.imagen, pdf_oficial) if p]

    if enviar_correo:
        try:
            EnviadorCorreo(config).enviar(
                declaracion,
                contribuyente,
                adjuntos,
                destinatarios=destinatarios,
                simular=simular_envio,
            )
            aviso.enviado_correo = not simular_envio
        except ErrorEnvioCorreo as exc:
            aviso.incidencias.append(f"Correo: {exc}")
            _log.error("No se envió el correo: %s", exc)

    if enviar_whatsapp:
        try:
            resultado_wa = EnviadorWhatsApp(config).enviar(
                declaracion,
                contribuyente,
                imagen=documentos.imagen,
                pdf=documentos.pdf,
                simular=simular_envio,
            )
            aviso.enviado_whatsapp = resultado_wa.enviado
            aviso.enlace_whatsapp = resultado_wa.enlace
        except ErrorEnvioWhatsApp as exc:
            aviso.incidencias.append(f"WhatsApp: {exc}")
            _log.error("No se envió el WhatsApp: %s", exc)

    return aviso


# --------------------------------------------------------------------------- #
# Persistencia de la declaración
# --------------------------------------------------------------------------- #


def guardar_declaracion(config: Config, declaracion: DeclaracionF29) -> str:
    """Deja la declaración en JSON para auditoría y para reimprimir sin volver al SII."""
    carpeta = config.directorio_salida / declaracion.rut.sin_formato / declaracion.periodo.codigo
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / "declaracion.json"
    destino.write_text(
        json.dumps(_a_dict(declaracion), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _log.info("Declaración guardada en %s", destino)
    return str(destino)


def cargar_declaracion(ruta: str | Path) -> DeclaracionF29:
    """Relee una declaración guardada por :func:`guardar_declaracion`."""
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    return DeclaracionF29(
        rut=Rut.parsear(datos["rut"]),
        periodo=Periodo.parsear(datos["periodo"]),
        folio=datos.get("folio", ""),
        estado=datos.get("estado", ""),
        razon_social=datos.get("razon_social", ""),
        via=datos.get("via", "archivo"),
        procedencia=datos.get("procedencia", PROCEDENCIA_DESCONOCIDA),
        url_comprobante=datos.get("url_comprobante", ""),
        lineas=[
            LineaCodigo(
                codigo=str(l["codigo"]),
                valor=Decimal(str(l["valor"])),
                glosa=l.get("glosa", ""),
            )
            for l in datos.get("lineas", [])
        ],
        crudo=datos.get("crudo", {}),
    )


def _a_dict(declaracion: DeclaracionF29) -> dict:
    return {
        "rut": declaracion.rut.con_guion,
        "periodo": str(declaracion.periodo),
        "folio": declaracion.folio,
        "estado": declaracion.estado,
        "razon_social": declaracion.razon_social,
        "via": declaracion.via,
        "procedencia": declaracion.procedencia,
        "url_comprobante": declaracion.url_comprobante,
        "monto_a_pagar": str(declaracion.monto_a_pagar),
        "lineas": [
            {"codigo": l.codigo, "valor": str(l.valor), "glosa": l.glosa}
            for l in declaracion.lineas
        ],
    }
