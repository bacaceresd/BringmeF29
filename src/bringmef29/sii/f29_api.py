"""Consulta del F29 por los servicios JSON internos del SII.

Es el camino rápido: una vez autenticado, la aplicación de "Consulta y
seguimiento de declaraciones" (``sifmConsultaInternet``) pide los datos a unos
endpoints JSON que aquí se llaman directamente, sin levantar un navegador.

Son endpoints internos, no documentados y sin contrato estable: el SII los
cambia sin aviso. Por eso el parseo es deliberadamente tolerante —busca pares
código/valor en cualquier parte del JSON— y por eso el flujo cae al modo
navegador cuando esto falla.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Iterator

import requests

from ..modelos import DeclaracionF29, LineaCodigo, Periodo
from ..rut import Rut
from . import procedencia as clasificador
from .errores import DeclaracionNoEncontrada, RespuestaInesperada
from .sesion import SesionSii

_log = logging.getLogger(__name__)

BASE = "https://www4.sii.cl/sifmConsultaInternet/services/data/facadeService"
URL_APP = "https://www4.sii.cl/sifmConsultaInternet/index.html?form=29&dest=sisadmin"

# Llaves donde el SII ha guardado el número de código y su valor.
_LLAVES_CODIGO = ("codigo", "cod", "codigoFormulario", "numeroCodigo")
_LLAVES_VALOR = ("valor", "val", "monto", "valorCodigo")
_LLAVES_FOLIO = ("folio", "numeroFolio", "folioDeclaracion")


class ClienteF29Api:
    """Cliente de los servicios JSON de consulta de declaraciones."""

    def __init__(self, sesion: SesionSii, *, base: str = BASE) -> None:
        self.sesion = sesion
        self.base = base.rstrip("/")

    # -- HTTP ---------------------------------------------------------------
    def _postear(self, servicio: str, datos: dict) -> Any:
        url = f"{self.base}/{servicio}"
        cuerpo = {
            "MetaData": {"conversationId": "", "transactionId": "", "namespace": ""},
            "data": datos,
        }
        try:
            respuesta = self.sesion.http.post(
                url,
                json=cuerpo,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Referer": URL_APP,
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
        except requests.RequestException as exc:
            raise RespuestaInesperada(f"Falló la llamada a {servicio}: {exc}") from exc

        if respuesta.status_code >= 400:
            raise RespuestaInesperada(f"{servicio} respondió HTTP {respuesta.status_code}.")
        try:
            return respuesta.json()
        except ValueError as exc:
            # Respuesta HTML = la sesión caducó o el SII devolvió su página de error.
            raise RespuestaInesperada(
                f"{servicio} no devolvió JSON. Lo más probable es que la sesión del SII "
                "haya expirado o que el servicio haya cambiado."
            ) from exc

    # -- Consultas ----------------------------------------------------------
    def listar_declaraciones(self, rut: Rut, periodo: Periodo) -> list[dict]:
        """Declaraciones presentadas para el RUT y período dados."""
        crudo = self._postear(
            "getListEventoDeclaracion",
            {
                "folio": "",
                "anoPeriodo": str(periodo.anio),
                "mesPeriodo": str(periodo.mes),
                "rutBuscar": str(rut.cuerpo),
                "dvBuscar": rut.dv,
            },
        )
        return list(_buscar_declaraciones(crudo))

    def detalle(self, rut: Rut, periodo: Periodo, folio: str) -> dict:
        return self._postear(
            "getDetalleDeclaracion",
            {
                "folio": str(folio),
                "anoPeriodo": str(periodo.anio),
                "mesPeriodo": str(periodo.mes),
                "rutBuscar": str(rut.cuerpo),
                "dvBuscar": rut.dv,
            },
        )

    def obtener(self, rut: Rut, periodo: Periodo) -> DeclaracionF29:
        """Trae la declaración **presentada** del período, con todos sus códigos.

        Esta vía consulta el servicio de seguimiento de declaraciones, que sólo ve
        los F29 ya enviados al SII. El formulario que el contribuyente guardó sin
        enviar vive en la aplicación de declaración y únicamente se alcanza por el
        modo navegador.
        """
        declaraciones = self.listar_declaraciones(rut, periodo)
        if not declaraciones:
            raise DeclaracionNoEncontrada(
                f"El SII no tiene un F29 presentado para {rut.formateado} en {periodo.etiqueta}."
            )
        # La última de la lista es la declaración vigente cuando hubo rectificatorias.
        cabecera = declaraciones[-1]
        folio = _primer_valor(cabecera, _LLAVES_FOLIO) or ""
        crudo = self.detalle(rut, periodo, folio) if folio else cabecera

        lineas = list(_extraer_lineas(crudo))
        if not lineas:
            raise RespuestaInesperada(
                f"Se encontró el folio {folio} pero no se pudo leer ningún código del F29. "
                "Reintenta con --modo navegador."
            )
        estado = str(_primer_valor(cabecera, ("estado", "glosaEstado", "descEstado")) or "")
        return DeclaracionF29(
            rut=rut,
            periodo=periodo,
            folio=str(folio),
            estado=estado,
            razon_social=str(_primer_valor(crudo, ("razonSocial", "nombreContribuyente")) or ""),
            fecha_presentacion=None,
            lineas=lineas,
            via="api",
            procedencia=clasificador.clasificar(
                crudo={"cabecera": cabecera, "detalle": crudo}, folio=str(folio), estado=estado
            ),
            crudo={"cabecera": cabecera, "detalle": crudo},
        )


# --------------------------------------------------------------------------- #
# Parseo tolerante
# --------------------------------------------------------------------------- #


def _recorrer(nodo: Any) -> Iterator[Any]:
    """Recorre en profundidad cualquier estructura de dicts y listas."""
    yield nodo
    if isinstance(nodo, dict):
        for valor in nodo.values():
            yield from _recorrer(valor)
    elif isinstance(nodo, list):
        for item in nodo:
            yield from _recorrer(item)


def _primer_valor(nodo: Any, llaves: tuple[str, ...]) -> Any:
    for sub in _recorrer(nodo):
        if isinstance(sub, dict):
            for llave in llaves:
                if llave in sub and sub[llave] not in (None, ""):
                    return sub[llave]
    return None


def _buscar_declaraciones(crudo: Any) -> Iterator[dict]:
    """Encuentra las cabeceras de declaración dentro de la respuesta."""
    for nodo in _recorrer(crudo):
        if isinstance(nodo, list) and nodo and all(isinstance(i, dict) for i in nodo):
            if any(any(l in i for l in _LLAVES_FOLIO) for i in nodo):
                yield from (i for i in nodo if any(l in i for l in _LLAVES_FOLIO))
                return
    # Respuesta con una única declaración, sin lista envolvente.
    for nodo in _recorrer(crudo):
        if isinstance(nodo, dict) and any(l in nodo for l in _LLAVES_FOLIO):
            yield nodo
            return


def _extraer_lineas(crudo: Any) -> Iterator[LineaCodigo]:
    """Extrae los pares código/valor del F29 estén donde estén en el JSON."""
    vistos: set[str] = set()
    for nodo in _recorrer(crudo):
        if not isinstance(nodo, dict):
            continue
        codigo = _valor_directo(nodo, _LLAVES_CODIGO)
        if codigo is None:
            continue
        codigo_txt = str(codigo).strip()
        if not codigo_txt.isdigit():
            continue
        bruto = _valor_directo(nodo, _LLAVES_VALOR)
        if bruto is None:
            continue
        monto = a_decimal(bruto)
        if monto is None:
            continue
        clave = codigo_txt.lstrip("0") or "0"
        if clave in vistos:
            continue
        vistos.add(clave)
        glosa = str(_valor_directo(nodo, ("glosa", "descripcion", "nombre", "desc")) or "")
        yield LineaCodigo(codigo=codigo_txt, valor=monto, glosa=glosa)


def _valor_directo(nodo: dict, llaves: tuple[str, ...]) -> Any:
    for llave in llaves:
        if llave in nodo and nodo[llave] not in (None, ""):
            return nodo[llave]
    return None


def a_decimal(bruto: Any) -> Decimal | None:
    """Convierte montos del SII (``"1.234.567"``, ``"1234,50"``, ``1234``) a Decimal."""
    if isinstance(bruto, bool):
        return None
    if isinstance(bruto, (int, float, Decimal)):
        return Decimal(str(bruto))
    texto = str(bruto).strip().replace("$", "").replace(" ", "")
    if not texto:
        return None
    negativo = texto.startswith("-") or (texto.startswith("(") and texto.endswith(")"))
    texto = texto.strip("()-")
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")   # 1.234.567,89
    elif "," in texto:
        texto = texto.replace(",", ".")                    # 1234,50
    elif texto.count(".") >= 1 and len(texto.rsplit(".", 1)[-1]) == 3:
        texto = texto.replace(".", "")                     # 1.234.567
    try:
        valor = Decimal(texto)
    except InvalidOperation:
        return None
    return -valor if negativo else valor
