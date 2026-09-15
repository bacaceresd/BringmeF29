"""Las pantallas de la aplicación local. Cada una es una página con su URL."""

from __future__ import annotations

import html
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlencode

from .. import cuadratura, formulario as armador_formulario, resumen as armador_resumen
from ..calendario import fecha_con_dia_semana
from ..config import Config
from ..modelos import DeclaracionF29, Periodo
from .estilos import CSS

CHEVRON = ('<svg class="chev" viewBox="0 0 8 13" fill="none" stroke="currentColor" '
           'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
           '<path d="M1.5 1.5 6.5 6.5l-5 5"/></svg>')

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
         "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

e = html.escape


def pagina(titulo: str, cuerpo: str, *, volver: str = "", accion: str = "") -> bytes:
    """Arma una pantalla: barra con título y, si corresponde, un volver."""
    izq = f'<a class="izq" href="{volver}">‹ Volver</a>' if volver else '<span class="izq"></span>'
    der = accion or '<span class="der"></span>'
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(titulo)} · BringmeF29</title><style>{CSS}</style></head>
<body><div class="marco">
  <header class="barra">{izq}<h1>{e(titulo)}</h1>{der}</header>
  <main class="lienzo">{cuerpo}</main>
</div></body></html>""".encode("utf-8")


# --------------------------------------------------------------------------- #
# 1. Consultar
# --------------------------------------------------------------------------- #


def consultar(config: Config, *, error: str = "", valores: dict | None = None) -> bytes:
    v = valores or {}
    hoy = datetime.now()
    anterior = Periodo.anterior_a_hoy(hoy.date())
    mes = int(v.get("mes") or anterior.mes)
    anio = int(v.get("anio") or anterior.anio)

    opciones_mes = "".join(
        f'<option value="{i+1}"{" selected" if i+1 == mes else ""}>{m.capitalize()}</option>'
        for i, m in enumerate(MESES)
    )
    opciones_anio = "".join(
        f'<option value="{a}"{" selected" if a == anio else ""}>{a}</option>'
        for a in range(hoy.year + 1, hoy.year - 8, -1)
    )
    clientes = "".join(
        f'<option value="{e(c.rut.con_guion)}">{e(c.alias)} — {e(c.razon_social or c.rut.formateado)}</option>'
        for c in sorted(config.clientes.values(), key=lambda c: c.alias)
    )

    return pagina("Traer F29 del SII", f"""
      {f'<p class="aviso error">{e(error)}</p>' if error else ''}

      <div>
        <p class="rotulo">Contribuyente</p>
        <form method="post" action="/consultar" id="f">
          <div class="grupo">
            {f'''<div class="fila">
              <label class="k" for="cliente">Cliente</label>
              <span class="v"><select id="cliente" name="cliente">
                <option value="">— elegir —</option>{clientes}</select></span>
            </div>''' if clientes else ''}
            <div class="fila">
              <label class="k" for="rut">Ingrese RUT</label>
              <span class="v"><input id="rut" name="rut" autocomplete="off"
                     placeholder="Sin puntos ni guión" value="{e(v.get('rut',''))}" required></span>
            </div>
            <div class="fila">
              <label class="k" for="clave">Clave tributaria</label>
              <span class="v"><input id="clave" name="clave" type="password"
                     autocomplete="off" placeholder="No sale de este equipo" required></span>
            </div>
            <p class="pista">
              La clave viaja de este formulario al proceso que entra al SII y a ningún
              otro lado: no se guarda ni sale de este equipo.
            </p>
          </div>

          <p class="rotulo" style="padding-top:22px">Período</p>
          <div class="grupo">
            <div class="fila">
              <label class="k" for="mes">Mes tributario</label>
              <span class="v"><select id="mes" name="mes">{opciones_mes}</select></span>
            </div>
            <div class="fila">
              <label class="k" for="anio">Año</label>
              <span class="v"><select id="anio" name="anio">{opciones_anio}</select></span>
            </div>
            <div class="fila">
              <label class="k" for="fuente">Formulario</label>
              <span class="v"><select id="fuente" name="fuente">
                <option value="guardada">Guardado, sin enviar</option>
                <option value="presentada">Ya presentado</option>
                <option value="auto">El que haya</option>
              </select></span>
            </div>
          </div>

          <p style="padding-top:22px"></p>
          <button type="submit" class="principal" id="btn">Traer del SII</button>
        </form>
      </div>

      <div class="grupo">
        <a class="enlace-fila" href="/historial"><span class="txt">Consultas anteriores</span>{CHEVRON}</a>
        <a class="enlace-fila" href="/codigos"><span class="txt">Códigos del F29</span>
          <span class="cuenta">215</span>{CHEVRON}</a>
      </div>

      <p class="nota">Nunca se usa la propuesta del SII: se lee el formulario que tú guardaste.</p>

      <script>
        var f = document.getElementById("f"), b = document.getElementById("btn");
        f.addEventListener("submit", function(){{
          b.disabled = true; b.textContent = "Entrando al SII… puede tardar medio minuto";
        }});
        var sel = document.getElementById("cliente");
        if (sel) sel.addEventListener("change", function(){{
          if (sel.value) document.getElementById("rut").value = sel.value;
        }});
      </script>
    """)


# --------------------------------------------------------------------------- #
# 2. Resumen del período
# --------------------------------------------------------------------------- #


def _cabecera(declaracion: DeclaracionF29) -> str:
    return f"""
      <div class="grupo"><div style="padding:16px">
        <div style="font-size:22px;font-weight:700">{e(declaracion.razon_social or 'Contribuyente')}</div>
        <div style="font-size:14px;color:var(--ink-2);margin-top:2px">
          {e(declaracion.rut.formateado)} · F29 {e(declaracion.periodo.etiqueta)}
          {f'· Folio {e(declaracion.folio)}' if declaracion.folio else ''}
        </div>
        <span style="display:inline-block;margin-top:11px;padding:4px 11px;border-radius:999px;
              font-size:13px;font-weight:600;background:var(--verde-suave);color:var(--verde)">
          {e(declaracion.procedencia_glosa)}</span>
      </div></div>"""


def _descuadres(declaracion: DeclaracionF29) -> str:
    problemas = cuadratura.verificar(declaracion)
    if not problemas:
        return ""
    items = "".join(f"<li>{e(str(p))}</li>" for p in problemas)
    return (f'<div class="aviso error"><strong>Revisa estas cifras</strong>'
            f'<ul style="margin:6px 0 0 18px">{items}</ul></div>')


def resumen(declaracion: DeclaracionF29, ref: str, rutas: dict) -> bytes:
    vence = declaracion.periodo.vencimiento_legal()
    datos = armador_resumen.construir(
        declaracion, vencimiento_texto=f"{fecha_con_dia_semana(vence)} - 23:59 hrs"
    )
    filas = []
    for grupo in datos.grupos:
        filas.append(f'<tr><th colspan="2" style="text-align:left;font-size:13px;'
                     f'text-transform:uppercase;letter-spacing:.04em;color:var(--ink-2);'
                     f'padding:16px 16px 7px;border-top:1px solid var(--hairline)">'
                     f'{e(grupo.titulo)}</th></tr>')
        for linea in grupo.lineas:
            if linea.separador:
                filas.append('<tr><td colspan="2" style="height:10px"></td></tr>')
                continue
            signo = (f'<span style="display:inline-block;width:28px;color:var(--ink-3)">'
                     f'({linea.signo})</span>' if linea.signo else '')
            peso = "font-weight:600;" if linea.total else ""
            monto = armador_resumen.monto_contable(linea.monto, parentesis=linea.parentesis)
            filas.append(
                f'<tr><td style="padding:8px 16px;border-top:1px solid var(--hairline);{peso}">'
                f'{signo}{e(linea.glosa)}</td>'
                f'<td style="padding:8px 16px;border-top:1px solid var(--hairline);text-align:right;'
                f'white-space:nowrap;font-variant-numeric:tabular-nums;{peso}">{e(monto)}</td></tr>')
        if grupo.nota:
            filas.append(f'<tr><td colspan="2" style="padding:8px 16px;font-style:italic;'
                         f'color:var(--ink-2);font-size:14px">{e(grupo.nota)}</td></tr>')

    hay_pago = datos.hay_que_pagar
    color = "naranja" if hay_pago else "verde"
    descargas = "".join(
        f'<a class="enlace-fila" href="/archivo?{urlencode({"ruta": ruta})}" download>'
        f'<span class="txt">{e(etiqueta)}</span>{CHEVRON}</a>'
        for etiqueta, ruta in rutas.items() if ruta
    ) or ('<p class="vacio">No se generaron los archivos. Revisa Chromium con '
          '<code>bringmef29 diagnostico</code> y vuelve a traer el F29.</p>')

    return pagina("Resumen", f"""
      {_cabecera(declaracion)}
      {_descuadres(declaracion)}

      <div>
        <p class="rotulo">Detalle del período</p>
        <div class="grupo"><table style="width:100%;border-collapse:collapse;font-size:16px">
          {''.join(filas)}</table></div>
      </div>

      <div style="display:flex;align-items:center;justify-content:space-between;gap:14px;
           padding:16px;border-radius:var(--r);background:var(--{color}-suave)">
        <span style="font-size:15px;font-weight:600">{e(datos.total_glosa)}</span>
        <span style="font-size:26px;font-weight:700;color:var(--{color});
              font-variant-numeric:tabular-nums;white-space:nowrap">
          {e(armador_resumen.monto_contable(datos.total_monto))}</span>
      </div>
      {f'<p style="padding:0 16px;font-size:15px">Vence el <strong>{e(datos.vencimiento_texto)}</strong></p>'
        if hay_pago else ''}

      <div>
        <p class="rotulo">Documentos generados</p>
        <div class="grupo">{descargas}</div>
        <p class="nota" style="padding-top:9px">
          La imagen del resumen es la que va por WhatsApp; el formulario, por correo.
        </p>
      </div>

      <div class="grupo">
        <a class="enlace-fila" href="/formulario?{urlencode({'ref': ref})}">
          <span class="txt">Ver el formulario F29</span>{CHEVRON}</a>
      </div>
    """, volver="/")


# --------------------------------------------------------------------------- #
# 3. Formulario F29 por secciones
# --------------------------------------------------------------------------- #


def formulario(declaracion: DeclaracionF29, ref: str, *, completo: bool = False) -> bytes:
    form = armador_formulario.construir(declaracion, completo=completo)
    bloques = []
    for seccion in form.secciones:
        filas = []
        for linea in seccion.lineas:
            cant = ""
            if linea.cantidad and (linea.cantidad.tiene_valor or completo):
                cant = (f'<span style="font-family:var(--mono);font-size:11px;color:var(--azul)">'
                        f'{linea.cantidad.codigo}</span> '
                        f'{armador_formulario.monto(linea.cantidad.valor)}')
            monto = ""
            if linea.monto and (linea.monto.tiene_valor or completo):
                monto = (f'<span style="font-family:var(--mono);font-size:11px;color:var(--azul)">'
                         f'{linea.monto.codigo}</span> '
                         f'{armador_formulario.monto(linea.monto.valor)}')
            extra = ""
            if linea.extra:
                partes = [f'{e(c.etiqueta)} <b style="font-family:var(--mono);font-size:11px">{c.codigo}</b> '
                          f'{armador_formulario.monto(c.valor)}'
                          for c in linea.extra if c.tiene_valor]
                if partes:
                    extra = (f'<div style="font-size:12.5px;color:var(--ink-2);margin-top:2px">'
                             f'{" · ".join(partes)}</div>')
            peso = "font-weight:600;" if linea.total else ""
            filas.append(
                f'<tr><td style="padding:7px 8px 7px 16px;border-top:1px solid var(--hairline);'
                f'color:var(--ink-3);font-variant-numeric:tabular-nums;width:34px;text-align:right">'
                f'{linea.numero}</td>'
                f'<td style="padding:7px 8px;border-top:1px solid var(--hairline);font-size:15px;{peso}">'
                f'{e(linea.glosa)}{extra}</td>'
                f'<td style="padding:7px 8px;border-top:1px solid var(--hairline);text-align:right;'
                f'white-space:nowrap;font-variant-numeric:tabular-nums;font-size:14px;color:var(--ink-2)">{cant}</td>'
                f'<td style="padding:7px 16px 7px 8px;border-top:1px solid var(--hairline);text-align:right;'
                f'white-space:nowrap;font-variant-numeric:tabular-nums;{peso}">{monto}</td>'
                f'<td style="padding:7px 12px 7px 0;border-top:1px solid var(--hairline);'
                f'color:var(--ink-3);text-align:center;width:14px">{linea.signo}</td></tr>')
        titulo = e(seccion.titulo) + (f' <span style="font-weight:400;color:var(--ink-2)">· '
                                      f'{e(seccion.subtitulo)}</span>' if seccion.subtitulo else '')
        bloques.append(
            f'<div><p class="rotulo" style="text-transform:none;font-size:14px;'
            f'font-weight:600;color:var(--ink)">{titulo}</p>'
            f'<div class="grupo"><table style="width:100%;border-collapse:collapse">'
            f'{"".join(filas)}</table></div></div>')

    otra = "compacto" if completo else "completo"
    enlace = "/formulario?" + urlencode(
        {"ref": ref} if completo else {"ref": ref, "completo": "1"}
    )

    return pagina("Formulario 29", f"""
      {_cabecera(declaracion)}
      {_descuadres(declaracion)}
      {"".join(bloques)}
      <div class="grupo">
        <a class="enlace-fila" href="{enlace}">
          <span class="txt">Ver el {otra}</span>{CHEVRON}</a>
      </div>
      <p class="nota">
        {f"{form.lineas_con_valor} líneas con valor" if not completo else "Todas las líneas del formulario"}
      </p>
    """, volver="/periodo?" + urlencode({"ref": ref}))


# --------------------------------------------------------------------------- #
# 4. Historial
# --------------------------------------------------------------------------- #


def _cuando(iso: str) -> str:
    """«2026-09-15T14:32:07» → «15 sep, 14:32». Distingue dos consultas del mismo período."""
    try:
        momento = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return ""
    return f"{momento.day} {MESES[momento.month - 1][:3]}, {momento:%H:%M}"


def historial(consultas: list[dict]) -> bytes:
    if not consultas:
        cuerpo = ('<div class="grupo"><p class="vacio">Todavía no hay consultas. '
                  'Las que traigas del SII quedan guardadas aquí.</p></div>')
    else:
        filas = []
        for c in consultas:
            monto = Decimal(c.get("monto") or 0)
            color = "var(--ink)" if monto else "var(--verde)"
            texto = armador_resumen.monto_contable(monto) if monto else "sin pago"
            filas.append(
                f'<a class="enlace-fila" href="/periodo?{urlencode({"ref": c["ref"]})}">'
                f'<span class="txt"><span style="font-weight:600">{e(c.get("razon") or c["rut"])}</span>'
                f'<br><span style="font-size:13.5px;color:var(--ink-2)">'
                f'{e(c["rut"])} · F29 {e(c["etiqueta"])}'
                f'{f" · {e(cuando)}" if (cuando := _cuando(c.get("cuando", ""))) else ""}'
                f'</span></span>'
                f'<span class="cuenta" style="color:{color};font-weight:600">{e(texto)}</span>'
                f'{CHEVRON}</a>')
        cuerpo = f'<div class="grupo">{"".join(filas)}</div>'
    return pagina("Consultas anteriores", cuerpo + """
      <p class="nota">Cada consulta queda guardada en el directorio de salida.</p>
    """, volver="/")


# --------------------------------------------------------------------------- #
# 5. Códigos del F29
# --------------------------------------------------------------------------- #


def codigos(catalogo: dict, filtro: str = "") -> bytes:
    filtro_bajo = filtro.strip().lower()
    filas = []
    for codigo, datos in catalogo.get("codigos", {}).items():
        glosa, linea = datos["glosa"], datos["linea"]
        seccion = cuadratura.seccion_de_linea(linea, catalogo)
        if filtro_bajo and not (codigo.startswith(filtro_bajo)
                                or filtro_bajo in glosa.lower()
                                or filtro_bajo in seccion.lower()):
            continue
        efecto = {"+": ("var(--verde)", "+"), "-": ("var(--rojo)", "−"),
                  "=": ("var(--azul)", "=")}.get(datos["signo"], ("var(--ink-3)", "·"))
        filas.append((linea, int(codigo),
            f'<div class="enlace-fila" style="cursor:default">'
            f'<span style="font-family:var(--mono);font-size:14px;font-weight:600;color:var(--azul);'
            f'min-width:44px">{codigo}</span>'
            f'<span class="txt"><span style="font-size:15px">{e(glosa)}</span>'
            f'<br><span style="font-size:12.5px;color:var(--ink-2)">Línea {linea} · {e(seccion)}'
            f'{"" if datos.get("monto") else " · no lleva monto"}</span></span>'
            f'<span style="font-family:var(--mono);font-weight:600;color:{efecto[0]};'
            f'width:20px;text-align:center">{efecto[1]}</span></div>'))
    filas.sort()

    lista = ("".join(f for _, _, f in filas) if filas
             else '<p class="vacio">Ningún código calza con esa búsqueda.</p>')
    return pagina("Códigos del F29", f"""
      <form method="get" action="/codigos">
        <div class="grupo"><div class="fila">
          <input name="q" value="{e(filtro)}" placeholder="Buscar código o glosa"
                 style="text-align:left" autocomplete="off" autofocus>
        </div></div>
      </form>
      <p class="nota" style="text-align:left">
        <b style="font-family:var(--mono);color:var(--verde)">+</b> suma ·
        <b style="font-family:var(--mono);color:var(--rojo)">−</b> resta ·
        <b style="font-family:var(--mono);color:var(--azul)">=</b> total ·
        <b style="font-family:var(--mono)">·</b> informativo
      </p>
      <div class="grupo">{lista}</div>
      <p class="nota">{len(filas)} código(s) · instrucciones del F29 del SII (12-11-2024)</p>
    """, volver="/")
