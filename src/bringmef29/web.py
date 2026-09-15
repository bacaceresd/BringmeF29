"""Interfaz web local: ingresas RUT y clave tributaria, y sale la tabla del F29.

Corre en tu propia máquina y escucha sólo en ``127.0.0.1``. Eso no es un detalle
de implementación: la clave tributaria de un contribuyente da acceso completo a
su situación ante el SII, así que viaja del formulario al proceso que la usa y
nada más — no se guarda en disco, no entra a los logs y no sale del equipo.

Usa la biblioteca estándar a propósito: un servidor de un solo usuario no
justifica sumar un framework, y menos dependencias es menos superficie por donde
se escape una credencial.
"""

from __future__ import annotations

import html
import logging
import threading
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import flujo, resumen as armador_resumen
from .calendario import fecha_con_dia_semana
from .config import Config, ErrorConfig
from .documentos import ConstructorDocumentos
from .modelos import Contribuyente, Periodo
from .rut import Rut, RutInvalido
from .sii.errores import ErrorSii

_log = logging.getLogger(__name__)

# Sólo se atienden peticiones cuyo Host sea el equipo local: cierra la puerta a
# que una página cualquiera del navegador le hable a este servidor.
_HOSTS_PERMITIDOS = {"localhost", "127.0.0.1", "[::1]"}


class ErrorWeb(RuntimeError):
    """Algo que el usuario puede corregir desde el formulario."""


# --------------------------------------------------------------------------- #
# Lógica
# --------------------------------------------------------------------------- #


def consultar(config: Config, rut_texto: str, clave: str, periodo_texto: str, fuente: str) -> dict:
    """Trae el F29 y arma el resumen y los documentos. Devuelve datos para la vista."""
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
    flujo.guardar_declaracion(config, declaracion)

    documentos = ConstructorDocumentos(config).construir(
        declaracion, contribuyente, captura_sii=resultado.captura
    )
    vence = periodo.vencimiento_legal(
        facturador_electronico=contribuyente.facturador_electronico
    )
    resumen = armador_resumen.construir(
        declaracion, vencimiento_texto=f"{fecha_con_dia_semana(vence)} - 23:59 hrs"
    )
    return {
        "declaracion": declaracion,
        "contribuyente": contribuyente,
        "resumen": resumen,
        "pdf": documentos.pdf,
        "imagen": documentos.imagen,
        "puede_enviar": bool(contribuyente.correo or contribuyente.whatsapp),
    }


# --------------------------------------------------------------------------- #
# Vistas
# --------------------------------------------------------------------------- #

_ESTILOS = """
:root{--ground:#eef1f5;--surface:#fff;--line:#d4dbe4;--ink:#111a24;--ink-2:#4a5a6d;
--ink-3:#77869a;--accent:#1a4f8a;--pay:#8a5100;--pay-soft:#fdf3e3;--ok:#1f6b46;
--ok-soft:#e9f5ee;--stop:#a32020;--stop-soft:#fbe9e9}
@media(prefers-color-scheme:dark){:root{--ground:#0d1218;--surface:#161d26;--line:#2b3542;
--ink:#e7edf4;--ink-2:#a3b1c2;--ink-3:#7a8a9d;--accent:#6aa6e8;--pay:#e8a33d;
--pay-soft:#2e2313;--ok:#4dbd8a;--ok-soft:#12291f;--stop:#e87b7b;--stop-soft:#2e1616}}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--ground);color:var(--ink);font:15px/1.5 "Helvetica Neue",Helvetica,Arial,sans-serif;
padding:32px 20px 64px}
.caja{max-width:560px;margin:0 auto;background:var(--surface);border:1px solid var(--line);
border-radius:12px;padding:30px 32px}
.ancho{max-width:860px}
h1{font-size:20px;margin-bottom:4px}
.sub{color:var(--ink-3);font-size:13.5px;margin-bottom:24px}
label{display:block;margin-bottom:16px;font-size:13px;color:var(--ink-2)}
label span{display:block;font-weight:600;margin-bottom:5px}
input,select{width:100%;padding:10px 12px;font:inherit;color:var(--ink);
background:var(--ground);border:1px solid var(--line);border-radius:8px}
.duo{display:flex;gap:14px}.duo>*{flex:1}
button{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:11px 20px;
font:600 15px/1 inherit;cursor:pointer;width:100%}
button:disabled{opacity:.6;cursor:progress}
.enlace{display:inline-block;padding:9px 16px;border:1px solid var(--line);border-radius:8px;
color:var(--ink);text-decoration:none;font-size:13.5px;font-weight:600;background:var(--surface)}
.enlace:hover{border-color:var(--accent);color:var(--accent)}
.acciones{display:flex;gap:10px;flex-wrap:wrap;margin-top:22px}
.aviso{padding:12px 16px;border-radius:8px;margin-bottom:20px;font-size:13.5px}
.error{background:var(--stop-soft);border-left:4px solid var(--stop);color:var(--stop)}
.ok{background:var(--ok-soft);border-left:4px solid var(--ok)}
.nota{color:var(--ink-3);font-size:12.5px;margin-top:18px;text-align:center}
table.resumen{width:100%;border-collapse:collapse;font-size:14px}
table.resumen th{text-align:left;font-size:15px;padding:18px 0 6px;border-bottom:1.5px solid var(--ink)}
table.resumen tbody:first-child th{padding-top:0}
table.resumen td{padding:5px 0}
table.resumen .monto{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
table.resumen .signo{display:inline-block;width:24px;color:var(--ink-3)}
table.resumen tr.total td{font-weight:700;border-top:1px solid var(--line);padding-top:7px}
table.resumen tr.separador td{height:10px;padding:0}
.nota-grupo{color:var(--ink-3);font-style:italic;font-size:13px}
.total-final{display:flex;justify-content:space-between;align-items:baseline;gap:16px;
margin-top:26px;padding:14px 18px;background:var(--pay-soft);border-left:5px solid var(--pay)}
.total-final.sin{background:var(--ok-soft);border-left-color:var(--ok)}
.total-glosa{font-weight:700;font-size:14px}
.total-monto{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
.vence{margin-top:10px;font-size:13.5px}
.quien{margin-bottom:20px}.quien .razon{font-size:19px;font-weight:700}
.quien .rut{color:var(--ink-3);font-size:13px}
@media(max-width:480px){.duo{flex-direction:column;gap:0}.caja{padding:22px 20px}}
"""

_JS_ESPERA = """
document.getElementById('formulario').addEventListener('submit', function(){
  var b = document.getElementById('enviar');
  b.disabled = true;
  b.textContent = 'Consultando el SII… puede tardar medio minuto';
});
"""


def _pagina(titulo: str, cuerpo: str, *, ancho: bool = False) -> bytes:
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(titulo)}</title><style>{_ESTILOS}</style></head>
<body><div class="caja{' ancho' if ancho else ''}">{cuerpo}</div></body></html>""".encode("utf-8")


def vista_formulario(error: str = "", valores: dict | None = None) -> bytes:
    v = valores or {}
    hoy = date.today()
    periodo_defecto = v.get("periodo") or str(Periodo.anterior_a_hoy(hoy))
    return _pagina("Traer F29 del SII", f"""
      <h1>Traer F29 del SII</h1>
      <p class="sub">Tu clave no se guarda ni sale de este equipo.</p>
      {f'<p class="aviso error">{html.escape(error)}</p>' if error else ''}
      <form method="post" action="/consultar" id="formulario">
        <label for="rut"><span>Ingrese RUT</span>
          <input id="rut" name="rut" inputmode="text" autocomplete="off" required
                 placeholder="Sin puntos ni guión" value="{html.escape(v.get('rut',''))}"></label>
        <label for="clave"><span>Clave tributaria</span>
          <input id="clave" name="clave" type="password" autocomplete="off" required></label>
        <div class="duo">
          <label for="periodo"><span>Período</span>
            <input id="periodo" name="periodo" placeholder="AAAA-MM"
                   value="{html.escape(periodo_defecto)}"></label>
          <label for="fuente"><span>Formulario</span>
            <select id="fuente" name="fuente">
              <option value="guardada">Guardado por mí</option>
              <option value="presentada">Ya presentado</option>
              <option value="auto">El que haya</option>
            </select></label>
        </div>
        <button type="submit" id="enviar">Traer la información</button>
      </form>
      <p class="nota">Nunca se usa la propuesta del SII.</p>
      <script>{_JS_ESPERA}</script>""")


def vista_resultado(datos: dict) -> bytes:
    declaracion = datos["declaracion"]
    contribuyente = datos["contribuyente"]
    resumen = datos["resumen"]
    razon = contribuyente.razon_social or declaracion.razon_social or "Contribuyente"

    filas = []
    for grupo in resumen.grupos:
        filas.append(f"<tbody><tr><th colspan='2'>{html.escape(grupo.titulo)}</th></tr>")
        for linea in grupo.lineas:
            if linea.separador:
                filas.append("<tr class='separador'><td colspan='2'></td></tr>")
                continue
            signo = f"<span class='signo'>({linea.signo})</span>" if linea.signo else ""
            clase = " class='total'" if linea.total else ""
            monto = armador_resumen.monto_contable(linea.monto, parentesis=linea.parentesis)
            filas.append(
                f"<tr{clase}><td>{signo}{html.escape(linea.glosa)}</td>"
                f"<td class='monto'>{html.escape(monto)}</td></tr>"
            )
        if grupo.nota:
            filas.append(f"<tr class='nota-grupo'><td colspan='2'>{html.escape(grupo.nota)}</td></tr>")
        filas.append("</tbody>")

    descuadres = ""
    if resumen.descuadres:
        items = "".join(f"<li>{html.escape(d)}</li>" for d in resumen.descuadres)
        descuadres = f"<div class='aviso error'><strong>Revisa estas cifras:</strong><ul>{items}</ul></div>"

    return _pagina(f"F29 {declaracion.periodo.etiqueta}", f"""
      <div class="quien">
        <div class="razon">{html.escape(razon)}</div>
        <div class="rut">{html.escape(declaracion.rut.formateado)} · F29 {html.escape(declaracion.periodo.etiqueta)}
        {(' · Folio ' + html.escape(declaracion.folio)) if declaracion.folio else ''}</div>
      </div>
      <p class="aviso ok">{html.escape(declaracion.procedencia_glosa)}</p>
      {descuadres}
      <table class="resumen">{''.join(filas)}</table>
      <div class="total-final{'' if resumen.hay_que_pagar else ' sin'}">
        <span class="total-glosa">{html.escape(resumen.total_glosa)}</span>
        <span class="total-monto">{html.escape(armador_resumen.monto_contable(resumen.total_monto))}</span>
      </div>
      {f'<p class="vence">Fecha de vencimiento: <strong>{html.escape(resumen.vencimiento_texto)}</strong></p>'
        if resumen.hay_que_pagar else ''}
      <div class="acciones">
        <a class="enlace" href="/archivo?tipo=pdf&amp;ruta={html.escape(datos['pdf'])}">Descargar PDF</a>
        <a class="enlace" href="/archivo?tipo=png&amp;ruta={html.escape(datos['imagen'])}">Descargar imagen</a>
        <a class="enlace" href="/">Otra consulta</a>
      </div>
      {'' if datos["puede_enviar"] else
        '<p class="nota">Para enviar por correo o WhatsApp, agrega este RUT a config/clientes.yml.</p>'}
    """, ancho=True)


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
            self._responder(b"Host no permitido", 403, "text/plain; charset=utf-8")
            return
        ruta = urlparse(self.path)
        if ruta.path == "/":
            self._responder(vista_formulario())
        elif ruta.path == "/archivo":
            self._servir_archivo(parse_qs(ruta.query))
        else:
            self._responder(b"No encontrado", 404, "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_local():
            self._responder(b"Host no permitido", 403, "text/plain; charset=utf-8")
            return
        if urlparse(self.path).path != "/consultar":
            self._responder(b"No encontrado", 404, "text/plain; charset=utf-8")
            return

        largo = int(self.headers.get("Content-Length") or 0)
        campos = parse_qs(self.rfile.read(largo).decode("utf-8"))
        rut = (campos.get("rut") or [""])[0].strip()
        clave = (campos.get("clave") or [""])[0]
        periodo = (campos.get("periodo") or [""])[0].strip()
        fuente = (campos.get("fuente") or ["guardada"])[0]

        try:
            datos = consultar(self.config, rut, clave, periodo, fuente)
        except (ErrorWeb, ErrorSii, ErrorConfig, ValueError) as exc:
            self._responder(vista_formulario(str(exc), {"rut": rut, "periodo": periodo}), 200)
            return
        except Exception as exc:  # noqa: BLE001 - un fallo inesperado no debe tumbar el servidor
            _log.exception("Falla inesperada al consultar")
            self._responder(vista_formulario(f"Error inesperado: {exc}", {"rut": rut}), 200)
            return
        finally:
            del clave

        self._responder(vista_resultado(datos))

    def _servir_archivo(self, consulta: dict) -> None:
        ruta = Path((consulta.get("ruta") or [""])[0])
        tipos = {"pdf": "application/pdf", "png": "image/png"}
        tipo = tipos.get((consulta.get("tipo") or [""])[0], "application/octet-stream")
        salida = self.config.directorio_salida.resolve()
        try:
            # Sólo se sirven archivos que el propio programa generó.
            ruta.resolve().relative_to(salida)
        except ValueError:
            self._responder(b"Ruta fuera del directorio de salida", 403, "text/plain; charset=utf-8")
            return
        if not ruta.exists():
            self._responder(b"No encontrado", 404, "text/plain; charset=utf-8")
            return
        cuerpo = ruta.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Content-Disposition", f'attachment; filename="{ruta.name}"')
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
