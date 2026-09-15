"""Interfaz de línea de comandos de BringmeF29."""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
from pathlib import Path

from . import __version__
from .config import Config, ErrorConfig, cargar
from .documentos.formato import fecha_larga, pesos
from .modelos import AvisoPago, Periodo
from .seguridad import (
    AlmacenClaves,
    ErrorSeguridad,
    FiltroRedaccion,
    VAR_CLAVE_MAESTRA,
    generar_clave_maestra,
)
from .sii.errores import ErrorSii

_log = logging.getLogger("bringmef29")

EJEMPLO_CONFIG = Path(__file__).parent.parent.parent / "config" / "clientes.example.yml"


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bringmef29",
        description=(
            "Trae el F29 declarado en el SII y arma el aviso de pago del contribuyente "
            "para enviarlo por correo y WhatsApp."
        ),
    )
    parser.add_argument("--version", action="version", version=f"bringmef29 {__version__}")
    parser.add_argument("-c", "--config", help="Ruta del archivo de configuración YAML.")
    parser.add_argument("-v", "--verboso", action="store_true", help="Muestra el detalle de cada paso.")

    sub = parser.add_subparsers(dest="comando", required=True)

    # -- comandos que consultan el SII --------------------------------------
    for nombre, ayuda in (
        ("traer", "Consulta el F29 en el SII y muestra el resumen."),
        ("documentos", "Consulta el F29 y genera el PDF y la imagen, sin enviar nada."),
        ("enviar", "Flujo completo: consulta, genera documentos y despacha el aviso."),
    ):
        p = sub.add_parser(nombre, help=ayuda, description=ayuda)
        p.add_argument("cliente", help="Alias o RUT del cliente configurado.")
        _opciones_periodo(p)
        _opciones_sii(p)
        if nombre != "traer":
            p.add_argument("--html", action="store_true", help="Guarda también el HTML del aviso.")
        if nombre == "enviar":
            p.add_argument("--solo-correo", action="store_true", help="No envía por WhatsApp.")
            p.add_argument("--solo-whatsapp", action="store_true", help="No envía por correo.")
            p.add_argument(
                "--simular",
                action="store_true",
                help="Prepara todo y muestra qué se enviaría, sin despachar.",
            )
            p.add_argument(
                "--para",
                action="append",
                metavar="CORREO",
                help="Destinatario alternativo (repetible).",
            )
            p.add_argument(
                "--desde-archivo",
                metavar="JSON",
                help="Usa una declaración ya guardada en vez de consultar el SII.",
            )

    # -- lote ---------------------------------------------------------------
    p_lote = sub.add_parser(
        "lote", help="Procesa varios clientes en una pasada.", description="Procesa varios clientes."
    )
    _opciones_periodo(p_lote)
    _opciones_sii(p_lote)
    p_lote.add_argument("--clientes", help="Lista de alias separados por coma (por defecto: todos).")
    p_lote.add_argument("--simular", action="store_true", help="No despacha nada.")
    p_lote.add_argument(
        "--sin-envio", action="store_true", help="Sólo genera los documentos de cada cliente."
    )
    p_lote.add_argument(
        "--continuar-con-errores",
        action="store_true",
        help="Sigue con el resto de los clientes si uno falla.",
    )

    # -- utilitarios --------------------------------------------------------
    sub.add_parser("clientes", help="Lista los clientes configurados.")

    p_clave = sub.add_parser("clave", help="Administra las claves tributarias cifradas.")
    sub_clave = p_clave.add_subparsers(dest="accion_clave", required=True)
    sub_clave.add_parser("generar-maestra", help="Genera una clave maestra nueva.")
    g = sub_clave.add_parser("guardar", help="Guarda cifrada la clave tributaria de un cliente.")
    g.add_argument("cliente", help="Alias o RUT del cliente.")
    e = sub_clave.add_parser("eliminar", help="Borra la clave tributaria almacenada.")
    e.add_argument("cliente", help="Alias o RUT del cliente.")
    sub_clave.add_parser("listar", help="Muestra los RUT con clave almacenada.")

    return parser


def _opciones_periodo(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "-p",
        "--periodo",
        help="Período tributario AAAA-MM (por defecto, el mes anterior al actual).",
    )


def _opciones_sii(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--fuente",
        choices=("guardada", "presentada", "auto"),
        help=(
            "Cuál F29 leer: 'guardada' (el que llenaste y grabaste, por defecto), "
            "'presentada' (la enviada, con folio) o 'auto'. Nunca la propuesta del SII."
        ),
    )
    p.add_argument(
        "--permitir-propuesta",
        action="store_true",
        help="Continúa aunque lo leído sea la propuesta del SII. Los montos no serán los tuyos.",
    )
    p.add_argument(
        "--modo",
        choices=("auto", "api", "navegador"),
        help="Cómo consultar el SII (por defecto, el de la configuración).",
    )
    p.add_argument(
        "--sin-headless",
        action="store_true",
        help="Muestra el navegador en pantalla (útil para ver qué pide el SII).",
    )


# --------------------------------------------------------------------------- #
# Ejecución
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    _configurar_logging(args.verboso)

    try:
        return _despachar(args)
    except (ErrorConfig, ErrorSeguridad) as exc:
        print(f"\n✗ {exc}\n", file=sys.stderr)
        return 2
    except ErrorSii as exc:
        print(f"\n✗ SII: {exc}\n", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("\nInterrumpido.", file=sys.stderr)
        return 130


def _despachar(args: argparse.Namespace) -> int:
    if args.comando == "clave":
        return _comando_clave(args)

    config = cargar(args.config)
    if args.comando == "clientes":
        return _comando_clientes(config)
    if args.comando == "lote":
        return _comando_lote(config, args)
    return _comando_cliente(config, args)


# -- comandos ---------------------------------------------------------------


def _comando_cliente(config: Config, args: argparse.Namespace) -> int:
    from . import flujo

    periodo = _resolver_periodo(args.periodo)
    headless = False if args.sin_headless else None

    if args.comando == "traer":
        contribuyente = config.cliente(args.cliente)
        resultado = flujo.obtener(
            config,
            contribuyente,
            periodo,
            fuente=args.fuente or "",
            modo=args.modo or "",
            headless=headless,
        )
        flujo.guardar_declaracion(config, resultado.declaracion)
        _imprimir_declaracion(resultado.declaracion)
        if resultado.captura:
            print(f"  Captura del SII : {resultado.captura}")
        if resultado.pdf_oficial:
            print(f"  PDF oficial SII : {resultado.pdf_oficial}")
        return 0

    aviso = flujo.procesar(
        config,
        args.cliente,
        periodo,
        fuente=args.fuente or "",
        modo=args.modo or "",
        headless=headless,
        permitir_propuesta=getattr(args, "permitir_propuesta", False),
        solo_documentos=args.comando == "documentos",
        enviar_correo=not getattr(args, "solo_whatsapp", False),
        enviar_whatsapp=not getattr(args, "solo_correo", False),
        simular_envio=getattr(args, "simular", False),
        destinatarios=getattr(args, "para", None),
        guardar_html=getattr(args, "html", False),
        desde_archivo=getattr(args, "desde_archivo", "") or "",
    )
    _imprimir_aviso(aviso, simulado=getattr(args, "simular", False))
    return 1 if aviso.incidencias else 0


def _comando_lote(config: Config, args: argparse.Namespace) -> int:
    from . import flujo

    periodo = _resolver_periodo(args.periodo)
    alias = (
        [a.strip() for a in args.clientes.split(",") if a.strip()]
        if args.clientes
        else sorted(config.clientes)
    )
    if not alias:
        print("No hay clientes configurados.", file=sys.stderr)
        return 2

    print(f"\nProcesando {len(alias)} cliente(s) para el período {periodo.etiqueta}\n")
    fallidos: list[str] = []
    for referencia in alias:
        print(f"── {referencia} " + "─" * max(0, 60 - len(referencia)))
        try:
            aviso = flujo.procesar(
                config,
                referencia,
                periodo,
                fuente=args.fuente or "",
                modo=args.modo or "",
                headless=False if args.sin_headless else None,
                permitir_propuesta=args.permitir_propuesta,
                solo_documentos=args.sin_envio,
                simular_envio=args.simular,
            )
            _imprimir_aviso(aviso, simulado=args.simular)
            if aviso.incidencias:
                fallidos.append(referencia)
        except (ErrorConfig, ErrorSii, ErrorSeguridad) as exc:
            fallidos.append(referencia)
            print(f"  ✗ {exc}\n", file=sys.stderr)
            if not args.continuar_con_errores:
                print("Se detuvo el lote. Usa --continuar-con-errores para seguir.", file=sys.stderr)
                return 1

    if fallidos:
        print(f"\nTerminó con problemas en: {', '.join(fallidos)}\n", file=sys.stderr)
        return 1
    print("\n✓ Lote completo sin incidencias.\n")
    return 0


def _comando_clientes(config: Config) -> int:
    if not config.clientes:
        print("No hay clientes configurados.")
        return 0
    print(f"\n{len(config.clientes)} cliente(s) en {config.ruta_archivo}\n")
    ancho = max(len(c.alias) for c in config.clientes.values())
    for contribuyente in sorted(config.clientes.values(), key=lambda c: c.alias):
        canales = []
        if contribuyente.correo:
            canales.append("correo")
        if contribuyente.whatsapp:
            canales.append("whatsapp")
        print(
            f"  {contribuyente.alias.ljust(ancho)}  {contribuyente.rut.formateado:>13}  "
            f"{contribuyente.razon_social or '—'}  [{', '.join(canales) or 'sin canales'}]"
        )
    print()
    return 0


def _comando_clave(args: argparse.Namespace) -> int:
    if args.accion_clave == "generar-maestra":
        clave = generar_clave_maestra()
        print("\nClave maestra generada. Guárdala fuera del repositorio:\n")
        print(f"  export {VAR_CLAVE_MAESTRA}='{clave}'\n")
        print("Si la pierdes, habrá que volver a guardar las claves tributarias.\n")
        return 0

    config = cargar(args.config)
    almacen = AlmacenClaves(config.ruta_almacen_claves)

    if args.accion_clave == "listar":
        ruts = almacen.ruts()
        if not ruts:
            print("No hay claves almacenadas.")
            return 0
        print(f"\n{len(ruts)} clave(s) en {config.ruta_almacen_claves}\n")
        for rut in ruts:
            print(f"  {rut}")
        print()
        return 0

    contribuyente = config.cliente(args.cliente)

    if args.accion_clave == "eliminar":
        if almacen.eliminar(contribuyente.rut.con_guion):
            print(f"✓ Clave eliminada para {contribuyente.rut.formateado}")
            return 0
        print(f"No había clave almacenada para {contribuyente.rut.formateado}")
        return 1

    # guardar
    print(f"\nClave tributaria del SII para {contribuyente.rut.formateado}")
    print("(no se muestra al escribir y se guarda cifrada)\n")
    clave = getpass.getpass("Clave: ")
    if not clave:
        print("No se ingresó nada; no se guardó.", file=sys.stderr)
        return 1
    if clave != getpass.getpass("Repite la clave: "):
        print("Las claves no coinciden.", file=sys.stderr)
        return 1
    almacen.guardar(contribuyente.rut.con_guion, clave, nota=contribuyente.alias)
    print(f"\n✓ Clave guardada cifrada en {config.ruta_almacen_claves}\n")
    return 0


# -- salida -----------------------------------------------------------------


def _imprimir_declaracion(declaracion) -> None:
    print(f"\n  F29 {declaracion.periodo.etiqueta} · {declaracion.rut.formateado}")
    if declaracion.razon_social:
        print(f"  {declaracion.razon_social}")
    print(f"  Folio           : {declaracion.folio or '—'}")
    if declaracion.estado:
        print(f"  Estado          : {declaracion.estado}")
    marca = "✓" if declaracion.es_del_contribuyente else "⚠"
    print(f"  {marca} Formulario    : {declaracion.procedencia_glosa}")
    print(f"  Leído vía       : {declaracion.via or '—'}")
    print(f"  Códigos leídos  : {len(declaracion.lineas)}")
    if declaracion.hay_que_pagar:
        print(f"  Total a pagar   : {pesos(declaracion.monto_a_pagar)}")
        print(f"  Vence           : {fecha_larga(declaracion.periodo.vencimiento_legal())}")
    else:
        remanente = declaracion.remanente_periodo_siguiente
        print("  Total a pagar   : sin pago asociado")
        if remanente and remanente > 0:
            print(f"  Remanente (077) : {pesos(remanente)}")
    print()


def _imprimir_aviso(aviso: AvisoPago, *, simulado: bool = False) -> None:
    _imprimir_declaracion(aviso.declaracion)
    if aviso.pdf:
        print(f"  PDF     : {aviso.pdf}")
    if aviso.imagen:
        print(f"  Imagen  : {aviso.imagen}")
    if aviso.comprobante_sii:
        print(f"  SII PDF : {aviso.comprobante_sii}")
    if simulado:
        print("\n  (simulación: no se envió nada)")
    else:
        if aviso.enviado_correo:
            print(f"  ✓ Correo enviado a {', '.join(aviso.contribuyente.correo)}")
        if aviso.enviado_whatsapp:
            print(f"  ✓ WhatsApp enviado a {aviso.contribuyente.whatsapp}")
    if aviso.enlace_whatsapp and not aviso.enviado_whatsapp:
        print(f"\n  Abre este enlace para enviar el WhatsApp:\n  {aviso.enlace_whatsapp}")
    for incidencia in aviso.incidencias:
        print(f"  ⚠ {incidencia}", file=sys.stderr)
    print()


def _resolver_periodo(valor: str | None) -> Periodo:
    return Periodo.parsear(valor) if valor else Periodo.anterior_a_hoy()


def _configurar_logging(verboso: bool) -> None:
    nivel = logging.DEBUG if verboso else logging.INFO
    manejador = logging.StreamHandler(sys.stderr)
    manejador.setFormatter(logging.Formatter("%(levelname)-7s %(name)s: %(message)s"))
    manejador.addFilter(FiltroRedaccion())
    raiz = logging.getLogger("bringmef29")
    raiz.handlers.clear()
    raiz.addHandler(manejador)
    raiz.setLevel(nivel)
    raiz.propagate = False
    # Las librerías de red son ruidosas y pueden incluir cabeceras en modo debug.
    logging.getLogger("urllib3").setLevel(logging.WARNING)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
