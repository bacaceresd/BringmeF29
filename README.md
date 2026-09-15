# BringmeF29

Trae el **Formulario 29 que tú llenaste y guardaste** en el SII, arma un **PDF de
aviso de pago** con la imagen del comprobante y lo despacha al contribuyente por
**correo y WhatsApp**, con el monto y los datos para que transfiera o pague directo
en el SII.

> **No usa la propuesta del SII.** Ese es el punto: el programa lee tu formulario,
> no el borrador que el SII pre-arma desde el Registro de Compras y Ventas, y se
> detiene sin generar nada si no logra distinguirlos.

Pensado para el ciclo mensual de un estudio contable: declaras el F29 en el SII y,
en una sola línea de comandos, el cliente recibe cuánto tiene que pagar, hasta
cuándo y a dónde.

```
                   ┌──────────────┐
  RUT + clave ──►  │     SII      │ ──► F29 del período (folio, códigos, monto)
                   └──────────────┘                  │
                                                     ▼
                                   ┌──────────────────────────────┐
                                   │  PDF de aviso  +  PNG resumen│
                                   └──────────────────────────────┘
                                          │                  │
                                      correo             WhatsApp
```

---

## La pantalla

```bash
bringmef29 web
```

Abre en tu navegador una pantalla con **Ingrese RUT** y **Clave tributaria**, trae el
F29 del período y muestra la tabla. Escucha sólo en `127.0.0.1`: la clave va del
formulario al proceso que la usa y nada más — no se guarda en disco, no entra a los
logs y no sale del equipo. Desde ahí se descargan el PDF y la imagen.

Si prefieres la terminal, todo lo que hace la pantalla está también en los comandos
de más abajo.

## Qué genera

El aviso es una tabla y nada más, agrupada como la escribe un contador:

```
IVA
  (+) IVA DF Boletas electrónicas                      23.030.105.-
  (+) IVA DF Facturas afectas                           2.317.063.-
  (=) Total IVA Débito                                  2.317.063.-

  (-) IVA CF Facturas afectas                          (1.993.566.-)
  (+) IVA CF Notas de crédito recibidas                     6.674.-
  (-) Remanente IVA CF mes anterior                    (2.533.186.-)
  (=) Total IVA Crédito                                (4.520.078.-)

  (=) Remanente IVA CF mes siguiente                    2.203.015.-

Retenciones
      Impuesto único 2ª categoría                          53.572.-
      Honorarios serv. profesionales                      386.874.-
  (=) Total retenciones a pagar                           440.446.-

PPM
      Base imponible PPM                                13.823.935.-
      No paga PPM

TOTAL A PAGAR F29 AGOSTO 2026                            440.446.-
Fecha de vencimiento: Lunes 21 de septiembre, 2026 - 23:59 hrs
```

El PDF y la imagen son la misma tabla: el PDF en A4 para adjuntar al correo, la
imagen para mandar por WhatsApp.

Por cada cliente y período, en `salida/<rut>/<aaaamm>/`:

| Archivo | Para qué sirve |
|---|---|
| `F29-<periodo>-<rut>.pdf` | El aviso de pago. Va adjunto al correo. |
| `F29-<periodo>-<rut>.png` | La misma tabla como imagen, para WhatsApp. |
| `comprobante-sii.png` | Captura de la pantalla del SII (sólo en modo navegador). Se incrusta en el PDF. |
| `f29-sii.pdf` | El PDF oficial del SII, cuando la pantalla ofrece la descarga. |
| `declaracion.json` | Los códigos leídos, para auditoría y para reimprimir sin volver al SII. |

El aviso distingue dos casos: si hay impuesto que enterar muestra el monto, el
plazo y los datos de transferencia; si el período no genera pago, lo dice y
muestra el remanente de crédito fiscal en vez de pedir plata.

---

## Instalación

Requiere Python 3.10 o superior.

```bash
git clone <este-repo> && cd BringmeF29
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
playwright install chromium        # se usa para el SII y para generar el PDF
```

Chromium hace doble trabajo: navega el sitio del SII cuando hace falta y
renderiza el PDF y la imagen. Por eso no hay ningún motor de PDF adicional que
instalar (nada de `wkhtmltopdf`, `cairo` ni `pango`).

---

## Configuración

### 1. Clave maestra

Las claves tributarias se guardan cifradas. Genera la clave maestra una sola vez:

```bash
bringmef29 clave generar-maestra
```

Copia la línea `export BRINGMEF29_MASTER_KEY=...` a tu `.env` o a tu perfil de
shell. **Si la pierdes hay que volver a guardar todas las claves tributarias.**

### 2. Archivo de clientes

```bash
cp config/clientes.example.yml config/clientes.yml
cp .env.example .env
```

Edita `config/clientes.yml`: los datos de tu estudio, tu cuenta bancaria, el
servidor de correo y la lista de clientes. El ejemplo está comentado campo por
campo. `config/clientes.yml` y `.env` están en `.gitignore`.

### 3. Claves tributarias de cada cliente

```bash
bringmef29 clave guardar acme
```

Pide la clave sin mostrarla en pantalla y la guarda cifrada en
`.secretos/claves.json` (permisos `600`). Alternativa sin almacén: exportar
`BRINGMEF29_CLAVE_ACME` en el entorno.

---

## Uso

```bash
# La pantalla de RUT y clave en el navegador
bringmef29 web

# Qué es cada código del F29
bringmef29 codigos 538

# Ver los clientes configurados
bringmef29 clientes

# Sólo consultar: qué dice el SII del período (por defecto, el mes anterior)
bringmef29 traer acme
bringmef29 traer acme --periodo 2025-08

# Generar el PDF y la imagen, sin enviar nada
bringmef29 documentos acme -p 2025-08

# Flujo completo, pero mostrando qué se enviaría
bringmef29 enviar acme -p 2025-08 --simular

# Flujo completo de verdad
bringmef29 enviar acme -p 2025-08

# Todos los clientes de una pasada
bringmef29 lote -p 2025-08 --continuar-con-errores
```

Opciones útiles:

| Opción | Efecto |
|---|---|
| `--fuente guardada\|presentada\|auto` | Cuál F29 leer. `guardada` por defecto: el que llenaste tú. |
| `--permitir-propuesta` | Continúa aunque lo leído sea la propuesta del SII. Los montos no serán los tuyos. |
| `--modo api\|navegador\|auto` | Cómo consultar el SII. |
| `--sin-headless` | Muestra el navegador en pantalla. Imprescindible para ver qué está pidiendo el SII cuando algo falla. |
| `--solo-correo` / `--solo-whatsapp` | Usa un solo canal. |
| `--para otro@correo.cl` | Manda el aviso a otra dirección (repetible). |
| `--desde-archivo salida/.../declaracion.json` | Rehace los documentos sin volver a entrar al SII. |
| `--html` | Guarda también el HTML del aviso, para ajustar el diseño. |
| `-v` | Detalle de cada paso. |

---

## WhatsApp: tres formas de enviarlo

Se elige en `whatsapp.proveedor`:

- **`enlace`** (por defecto). No manda nada por sí solo: arma un link `wa.me` con
  el mensaje ya escrito. Lo abres y aprietas enviar desde tu teléfono o WhatsApp
  Web. No requiere cuenta de API ni plantillas aprobadas, así que funciona el
  primer día. El PDF viaja por correo.
- **`twilio`**. WhatsApp Business vía Twilio. Envía solo.
- **`meta`**. WhatsApp Cloud API, directo con Meta. Envía solo.

Los dos últimos sólo pueden adjuntar archivos que ellos mismos puedan descargar
por HTTPS: hay que publicar la carpeta de salida y poner esa URL en
`whatsapp.url_publica_base`. Sin eso, el mensaje va con texto y el PDF por correo.
Ambos respetan además la ventana de 24 horas de Meta: para iniciar una
conversación fuera de ella hace falta una plantilla aprobada (`meta_plantilla`).

---

## Cuál F29 trae (y cuál no)

El SII mantiene **tres** formularios distintos para un mismo período:

| | Qué es | ¿Sirve para cobrar? |
|---|---|---|
| **Propuesta** | El borrador que el SII pre-arma con el Registro de Compras y Ventas. | **No.** No lleva PPM, retenciones, remanentes arrastrados ni ningún ajuste que hagas a mano. |
| **Guardada** | El formulario que tú llenaste y grabaste, todavía sin enviar. | Sí. Es la versión del contador. |
| **Presentada** | La declaración ya enviada, con folio. | Sí. |

Por defecto se lee la **guardada**. Se cambia con `--fuente`:

```bash
bringmef29 enviar acme --fuente guardada     # el que llenaste tú (por defecto)
bringmef29 enviar acme --fuente presentada   # la ya enviada, con folio
bringmef29 enviar acme --fuente auto         # la guardada y, si no hay, la presentada
```

### La salvaguarda

Cobrarle a un cliente el monto de la propuesta es un error que llega a su
bolsillo, así que el programa trata ese caso como bloqueante, no como advertencia:

- Clasifica cada formulario que lee mirando el texto, la URL y el JSON crudo, y
  **ante la duda no afirma** que sea tuyo.
- Si lo leído es la propuesta, **no genera ni envía nada** y lo dice. Sólo
  continúa con `--permitir-propuesta`, y entonces el PDF sale con una advertencia
  roja encima del monto.
- Si no logró clasificarlo, también se detiene, con el comando exacto para
  revisarlo a ojo.
- La procedencia queda impresa en el PDF (fila *Formulario*), guardada en el JSON
  y visible en la terminal con un `✓` o un `⚠`.

Lo puedes ver en cualquier momento sin enviar nada:

```bash
bringmef29 traer acme -p 2025-08
```

```
  ✓ Formulario    : Declaración guardada por el contribuyente (sin enviar)
  Leído vía       : navegador
```

## Cómo se obtiene el F29

Hay dos caminos, y `auto` los usa en este orden:

1. **`api`** — Una vez autenticado, la aplicación de consulta de declaraciones del
   SII (`sifmConsultaInternet`) pide sus datos a unos endpoints JSON. El programa
   los llama directo, sin navegador. Es rápido, pero son **endpoints internos, no
   documentados y sin contrato estable**, y **sólo alcanza declaraciones
   presentadas**: el formulario guardado vive en la aplicación de declaración.
   Por eso pedir `--fuente guardada --modo api` es un error, y con la fuente por
   defecto se va directo al navegador.
2. **`navegador`** — Abre el sitio real con Chromium, se autentica en el
   formulario y deja que la propia aplicación del SII pida sus datos; el programa
   escucha las respuestas JSON que pasan por la red y, cuando el formulario está
   abierto en modo edición, lee los valores directo de los campos —que es donde
   vive el F29 guardado—. Aguanta mejor los cambios del sitio, alcanza los tres
   formularios, y es el único modo que captura la pantalla y baja el PDF oficial.

En ambos casos el parseo es deliberadamente tolerante: busca pares
código/valor en cualquier parte del JSON, sin depender de una estructura fija, y
como último recurso lee los códigos del texto de la pantalla.

### Si el SII cambia y deja de funcionar

Es cuestión de tiempo: el SII no ofrece una API pública para esto.

```bash
bringmef29 traer acme --modo navegador --sin-headless -v
```

Verás el navegador en pantalla y, cuando algo falle, quedará una captura en
`.estado_sii/`. Con eso se ajustan los selectores en
`src/bringmef29/sii/f29_navegador.py` o los endpoints en
`src/bringmef29/sii/f29_api.py`. Mientras tanto, `--desde-archivo` permite
reemitir avisos con lo ya descargado.

**Dos límites conocidos.** Si la cuenta tiene segundo factor activado, el login
automático se detiene y hay que completarlo con `--sin-headless`. Y los códigos
del F29 se leen tal como vienen: el programa no recalcula el impuesto ni valida
la declaración, sólo reporta lo que el SII ya tiene registrado.

---

## Los códigos del F29

`src/bringmef29/recursos/codigos_f29.yml` tiene los **215 códigos del formulario**,
generados desde las fuentes oficiales del SII: las
[instrucciones de llenado vigentes](https://www.sii.cl/servicios_online/instrucciones_f29_20241112.pdf)
y el [formulario con su mapa de líneas](https://www.sii.cl/formularios/imagen/F29.pdf).

De cada código se guarda **qué efecto tiene**, que es lo que permite cuadrar:

| Campo | Qué dice |
|---|---|
| `linea` | En qué línea del formulario va |
| `signo` | `+` suma, `-` resta, `=` es un total, vacío = no entra en ningún total |
| `monto` | Si es el código de la línea que lleva el monto. Cada línea pide varios —cantidad de documentos, tasa, base, monto— y sólo el último suma |
| `glosa` | Para qué sirve |

```bash
bringmef29 codigos 538              # qué es un código
bringmef29 codigos --buscar boleta  # buscar por glosa
bringmef29 codigos --seccion cred --solo-montos
```

```
  Código 538
  TOTAL DÉBITOS

  Línea   : 23
  Sección : Débitos
  Efecto  : es un total
```

Tres cosas que este catálogo dejó en claro, y que estaban mal antes:

- **`511` no es crédito fiscal.** Es el total de documentos electrónicos recibidos,
  con y sin derecho a crédito: informativo. El crédito por facturas del giro es el
  **`520`**.
- **`527` es la cantidad** de notas de crédito recibidas; el monto es el **`528`**,
  y **resta** del crédito.
- **La pérdida del art. 90** que suspende los PPM es el **`30`**, y las
  **liquidaciones factura** son el **`501`**.

## Que cuadre

El formulario tiene identidades propias, y el programa las comprueba sobre lo que
trajo del SII:

| Identidad | Fuente |
|---|---|
| `538` = suma de las líneas 7 a 22 | Instrucciones, línea 23 |
| `537` = suma de las líneas 28 a 48 | Instrucciones, línea 49 |
| `89` = `538` − `537`, cuando es positivo | Anverso, línea 50 |
| `77` = `537` − `538`, cuando es positivo | Anverso, línea 50 |
| `94` = `91` + `92` + `93` | Anverso, total con recargo |

Si una no se cumple, el aviso lo dice encima del monto en vez de callarlo:

```
Revisa estas cifras:
  Total débitos (código 538): el SII trae 9.999.999 y las líneas dan
  2.317.063 — diferencia 7.682.936
```

Un descuadre casi siempre significa que el programa **leyó mal una línea**, no que
el contribuyente declaró mal. Es la señal de que el resultado todavía no calza con
lo que dejaste guardado en el SII, y hay que mirarlo antes de mandarle nada al
cliente.

Las identidades están en el mismo `codigos_f29.yml`, al final, y el verificador en
`src/bringmef29/cuadratura.py`.

## Cómo se arma el resumen

Las líneas del aviso, sus glosas, sus signos y de qué código sale cada monto están
en `src/bringmef29/recursos/resumen_f29.yml`. Ese archivo está hecho para que lo
edites: cada contribuyente usa un subconjunto distinto del formulario.

Tres reglas que conviene conocer:

- **Un código que no venga en la declaración no imprime nada.** Una línea mal
  mapeada desaparece del resumen; nunca inventa una cifra.
- **Si omites la glosa, se usa la oficial del catálogo.**
- **Una línea admite varios códigos** (`codigo: ["520", "511"]`): se usa el primero
  que exista, para cubrir variantes del formulario sin tocar código.

El **total a pagar** es el primero de estos códigos con valor mayor que cero:

| Prioridad | Código | Glosa |
|---|---|---|
| 1 | `94` | Total a pagar con recargo (declaración fuera de plazo) |
| 2 | `91` | Total a pagar dentro del plazo legal |
| 3 | `547` | Total determinado |

## La fecha de vencimiento

Se calcula, no se escribe a mano: **día 20 del mes siguiente** para facturadores
electrónicos —día 12 en papel, con `facturador_electronico: false` en el cliente—
corrido al día hábil siguiente cuando cae sábado, domingo o feriado.

Los feriados chilenos están en `src/bringmef29/calendario.py`: los fijos, Semana
Santa calculada, y los movibles por ley (29 de junio, 12 de octubre, 31 de
octubre) con sus reglas de traslado. Lo que no está —elecciones, feriados
regionales, prórrogas que el SII decreta para un año puntual— se agrega con
`feriados_extra`. El calendario oficial lo publica la Dirección del Trabajo.

Así, el F29 de agosto 2026 vence el **lunes 21 de septiembre**: el día 20 cae
domingo y el 18 y 19 son feriados.

## Seguridad

Estás manejando claves tributarias de terceros, que dan acceso completo a su
situación ante el SII. El programa toma estas precauciones:

- Las claves se cifran con Fernet (AES-128 + HMAC) y la clave maestra vive fuera
  del repositorio, en el entorno o en un archivo con permisos `600`.
- El almacén se crea con permisos `600` y se niega a leer un archivo que sea
  legible por otros usuarios.
- Los logs pasan por un filtro que enmascara claves y tokens. El código, además,
  nunca los entrega a un logger.
- `.gitignore` excluye `config/clientes.yml`, `.env`, `.secretos/`, `salida/` y
  `.estado_sii/`: ni las claves ni los datos tributarios de tus clientes pueden
  llegar al repositorio por descuido.

Lo que queda de tu lado: pedir autorización a cada cliente para operar con su
clave, y no correr esto en un equipo compartido.

---

## Desarrollo

```bash
pip install -e ".[dev]"
pytest              # 233 pruebas
pytest -k documentos   # sólo el armado del PDF y la imagen
```

Las pruebas que generan PDF o PNG se saltan solas si no hay Chromium disponible.
Ninguna prueba toca el SII: el acceso se verifica con respuestas JSON de ejemplo
y con dobles de prueba.

### Estructura

```
src/bringmef29/
├── cli.py             Interfaz de línea de comandos
├── web.py             Pantalla local de RUT y clave tributaria
├── flujo.py           Orquestador: del SII al aviso enviado
├── resumen.py         Arma la tabla: IVA, Retenciones, PPM y total
├── cuadratura.py      Catálogo de códigos y verificación de identidades
├── calendario.py      Feriados chilenos y vencimiento del F29
├── config.py          Configuración, clientes y resolución de secretos
├── modelos.py         Período, declaración F29, aviso de pago
├── rut.py             RUT chileno: validación y formatos
├── seguridad.py       Cifrado de claves y redacción de logs
├── sii/
│   ├── sesion.py        Autenticación con RUT y clave tributaria
│   ├── procedencia.py   Distingue propuesta / guardada / presentada
│   ├── f29_api.py       Consulta por los servicios JSON internos
│   └── f29_navegador.py Consulta manejando el sitio con Chromium
├── documentos/
│   ├── constructor.py   HTML → PDF y HTML → PNG
│   └── formato.py       Pesos y fechas en convención chilena
├── envio/
│   ├── correo.py        SMTP con adjuntos
│   └── whatsapp.py      enlace wa.me · Twilio · Meta Cloud API
└── recursos/
    ├── aviso.html.j2    Plantilla del PDF y de la imagen
    ├── aviso.css        Estilos del aviso
    ├── codigos_f29.yml  Los 215 códigos del formulario, su línea y su efecto
    └── resumen_f29.yml  Qué líneas lleva el resumen y de qué código sale cada una
```

Para cambiar el diseño del aviso: `aviso.html.j2` y `aviso.css`. Genera con
`--html` y ábrelo en el navegador para iterar rápido.
