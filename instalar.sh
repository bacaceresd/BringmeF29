#!/usr/bin/env bash
# Deja BringmeF29 listo para consultar el SII desde este computador.
# Uso:  bash instalar.sh
set -euo pipefail

cd "$(dirname "$0")"
echo
echo "  Instalando BringmeF29"
echo

# --- Python ---------------------------------------------------------------
if ! command -v python3 >/dev/null; then
  echo "  ✗ No hay python3 en este equipo. Instálalo desde python.org y repite."
  exit 1
fi
version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)'; then
  echo "  ✗ Python $version es muy antiguo. Hace falta 3.10 o superior."
  exit 1
fi
echo "  ✓ Python $version"

# --- Entorno y dependencias ----------------------------------------------
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -e .
echo "  ✓ Dependencias instaladas"

python -m playwright install chromium >/dev/null 2>&1 || \
  python -m playwright install chromium
echo "  ✓ Chromium listo"

# --- Configuración --------------------------------------------------------
if [ ! -f config/clientes.yml ]; then
  cp config/clientes.example.yml config/clientes.yml
  echo "  ✓ config/clientes.yml creado — falta completarlo"
else
  echo "  ✓ config/clientes.yml ya existe"
fi

# --- Clave maestra --------------------------------------------------------
if [ ! -f .env ]; then
  cp .env.example .env
  clave=$(python -c 'from bringmef29.seguridad import generar_clave_maestra; print(generar_clave_maestra())')
  # Sólo se escribe una vez: si se pierde, hay que volver a guardar las claves.
  python - "$clave" <<'PY'
import sys, pathlib
clave = sys.argv[1]
archivo = pathlib.Path(".env")
texto = archivo.read_text(encoding="utf-8")
archivo.write_text(texto.replace("BRINGMEF29_MASTER_KEY=", f"BRINGMEF29_MASTER_KEY={clave}"), encoding="utf-8")
PY
  chmod 600 .env
  echo "  ✓ Clave maestra generada y guardada en .env"
else
  echo "  ✓ .env ya existe, no se toca"
fi

echo
echo "  Listo. Los siguientes pasos:"
echo
echo "    source .venv/bin/activate"
echo "    nano config/clientes.yml          # tus datos y los de tus clientes"
echo "    bringmef29 clave guardar <alias>  # la clave tributaria del cliente"
echo "    bringmef29 diagnostico            # comprueba que todo esté en su lugar"
echo
echo "  Y la primera consulta real, con el navegador a la vista:"
echo
echo "    bringmef29 traer <alias> -p 2026-08 --modo navegador --sin-headless -v"
echo
