"""Hoja de estilo compartida por las pantallas de la aplicación local."""

CSS = """
:root{
  --ground:#f2f2f7; --surface:#fff; --fill:rgba(118,118,128,.12);
  --fill-fuerte:rgba(118,118,128,.20); --hairline:rgba(60,60,67,.29);
  --ink:#000; --ink-2:rgba(60,60,67,.60); --ink-3:rgba(60,60,67,.30);
  --azul:#007aff; --azul-suave:rgba(0,122,255,.10);
  --verde:#34c759; --verde-suave:rgba(52,199,89,.12);
  --naranja:#ff9500; --naranja-suave:rgba(255,149,0,.12);
  --rojo:#ff3b30; --rojo-suave:rgba(255,59,48,.10);
  --sombra:0 1px 2px rgba(0,0,0,.04); --r:12px;
  --sans:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",system-ui,
         Roboto,"Helvetica Neue",Arial,sans-serif;
  --mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){
  :root{
    --ground:#000; --surface:#1c1c1e; --fill:rgba(118,118,128,.24);
    --fill-fuerte:rgba(118,118,128,.36); --hairline:rgba(84,84,88,.65);
    --ink:#fff; --ink-2:rgba(235,235,245,.60); --ink-3:rgba(235,235,245,.30);
    --azul:#0a84ff; --azul-suave:rgba(10,132,255,.18);
    --verde:#30d158; --verde-suave:rgba(48,209,88,.18);
    --naranja:#ff9f0a; --naranja-suave:rgba(255,159,10,.18);
    --rojo:#ff453a; --rojo-suave:rgba(255,69,58,.18); --sombra:none;
  }
}
*{box-sizing:border-box;margin:0;padding:0}
[hidden]{display:none!important}
body{
  background:var(--ground);color:var(--ink);font-family:var(--sans);
  font-size:17px;line-height:1.45;letter-spacing:-.01em;
  -webkit-font-smoothing:antialiased;
}
a{color:var(--azul);text-decoration:none}
button,input,select{font:inherit;color:inherit;letter-spacing:inherit}
:focus-visible{outline:2.5px solid var(--azul);outline-offset:2px;border-radius:6px}

.marco{max-width:680px;margin:0 auto;min-height:100vh;background:var(--ground)}
.barra{
  position:sticky;top:0;z-index:10;display:grid;
  grid-template-columns:96px minmax(0,1fr) 96px;align-items:center;gap:6px;
  padding:11px 14px;min-height:52px;border-bottom:1px solid var(--hairline);
  background:color-mix(in srgb,var(--ground) 88%,transparent);
  backdrop-filter:saturate(180%) blur(20px);
}
.barra h1{font-size:17px;font-weight:600;text-align:center;grid-column:2;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.barra .izq{grid-column:1}.barra .der{grid-column:3;text-align:right}
.barra a{font-size:16px}
.lienzo{padding:18px 16px 48px;display:flex;flex-direction:column;gap:22px}

.rotulo{font-size:13px;color:var(--ink-2);text-transform:uppercase;
  letter-spacing:.04em;padding:0 16px 7px}
.grupo{background:var(--surface);border-radius:var(--r);box-shadow:var(--sombra);overflow:hidden}
.fila{display:flex;align-items:center;gap:12px;padding:11px 16px;min-height:46px;
  border-top:1px solid var(--hairline)}
.fila:first-child{border-top:0}
.fila .k{font-size:17px;flex:none;min-width:130px}
.fila .v{flex:1;min-width:0;display:flex;justify-content:flex-end}
.fila input,.fila select{width:100%;background:transparent;border:0;padding:0;
  font-size:17px;text-align:right;color:var(--ink);-webkit-appearance:none;appearance:none}
.fila input::placeholder{color:var(--ink-3)}
.fila select{cursor:pointer;direction:rtl;text-overflow:ellipsis}
.fila select option{direction:ltr}
.pista{padding:9px 16px 13px;font-size:13px;color:var(--ink-2);line-height:1.38}
.pista code{font-family:var(--mono);font-size:12px;background:var(--fill);
  padding:1px 5px;border-radius:5px}

.principal{width:100%;background:var(--azul);color:#fff;border:0;border-radius:var(--r);
  padding:14px 20px;font-size:17px;font-weight:600;cursor:pointer}
.principal:disabled{opacity:.6;cursor:progress}
.enlace-fila{display:flex;align-items:center;gap:12px;width:100%;padding:13px 16px;
  border:0;border-top:1px solid var(--hairline);background:transparent;color:var(--ink);
  font-size:17px;cursor:pointer;text-align:left}
.enlace-fila:first-child{border-top:0}
.enlace-fila:hover{background:var(--fill)}
.enlace-fila .txt{flex:1;min-width:0}
.enlace-fila .cuenta{color:var(--ink-2);font-size:16px;font-variant-numeric:tabular-nums}
.enlace-fila .chev{width:8px;height:13px;color:var(--ink-3);flex:none}

.aviso{padding:12px 16px;border-radius:var(--r);font-size:14px;line-height:1.4}
.aviso.error{background:var(--rojo-suave);color:var(--rojo)}
.aviso.ok{background:var(--verde-suave);color:var(--verde)}
.aviso.info{background:var(--azul-suave);color:var(--azul)}
.nota{font-size:13px;color:var(--ink-2);text-align:center;padding:0 16px;line-height:1.4}
.vacio{padding:30px 22px;text-align:center;color:var(--ink-2);font-size:15px;line-height:1.5}
"""
