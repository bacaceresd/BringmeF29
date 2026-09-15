#!/usr/bin/env bash
# Publica BringmeF29 en tu propio proyecto de Firebase / Google Cloud.
#
# Se corre desde TU computador, con TU sesión: las credenciales no salen de ahí.
#   bash desplegar.sh
#
# Lo que deja andando:
#   · un proyecto de Firebase llamado "Trae F29"
#   · la aplicación en Cloud Run, en Santiago, apagada mientras nadie la use
#   · Firebase Hosting delante, con el dominio bonito
#   · la contraseña de acceso guardada en Secret Manager, no en el código
set -euo pipefail

PROYECTO="${PROYECTO:-trae-f29}"
NOMBRE="${NOMBRE:-Trae F29}"
REGION="${REGION:-southamerica-west1}"     # Santiago: cerca del SII y de ti
SERVICIO="trae-f29"
SECRETO="bringmef29-acceso"

cd "$(dirname "$0")"
echo
echo "  Publicando «$NOMBRE» ($PROYECTO) en $REGION"
echo

# --- Herramientas ---------------------------------------------------------
for programa in gcloud firebase; do
  if ! command -v "$programa" >/dev/null; then
    echo "  ✗ Falta «$programa»."
    [ "$programa" = "gcloud" ] && echo "    Instálalo desde https://cloud.google.com/sdk/docs/install"
    [ "$programa" = "firebase" ] && echo "    Instálalo con: npm install -g firebase-tools"
    exit 1
  fi
done
echo "  ✓ gcloud y firebase instalados"

# --- Sesión ---------------------------------------------------------------
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
  echo "  → Abriendo el navegador para que entres a Google…"
  gcloud auth login
fi
firebase login --no-localhost >/dev/null 2>&1 || firebase login
echo "  ✓ Sesión iniciada"

# --- Proyecto -------------------------------------------------------------
if gcloud projects describe "$PROYECTO" >/dev/null 2>&1; then
  echo "  ✓ El proyecto $PROYECTO ya existe"
else
  echo "  → Creando el proyecto $PROYECTO"
  gcloud projects create "$PROYECTO" --name="$NOMBRE"
  firebase projects:addfirebase "$PROYECTO"
fi
gcloud config set project "$PROYECTO" >/dev/null

# Cloud Run y Secret Manager necesitan una cuenta de facturación asociada.
# Con el uso de un contador el costo es prácticamente cero: el servicio se
# apaga solo cuando nadie lo está usando.
if ! gcloud beta billing projects describe "$PROYECTO" \
     --format="value(billingEnabled)" 2>/dev/null | grep -q True; then
  echo
  echo "  ✗ Al proyecto le falta la cuenta de facturación (plan Blaze)."
  echo "    Actívala aquí y vuelve a correr este script:"
  echo "    https://console.firebase.google.com/project/$PROYECTO/usage/details"
  exit 1
fi
echo "  ✓ Facturación activa"

echo "  → Habilitando los servicios que hacen falta"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  firebasehosting.googleapis.com --quiet
echo "  ✓ Servicios habilitados"

# --- Contraseña de acceso -------------------------------------------------
# Sin esto la aplicación no arranca: ver src/bringmef29/web/nube.py.
if ! gcloud secrets describe "$SECRETO" >/dev/null 2>&1; then
  echo
  echo "  La aplicación publicada va detrás de una contraseña. No es la clave"
  echo "  tributaria de nadie: es la llave de la aplicación. Mínimo 12 caracteres."
  read -rsp "  Contraseña de acceso: " acceso; echo
  read -rsp "  Repítela: " otra; echo
  [ "$acceso" = "$otra" ] || { echo "  ✗ No coinciden."; exit 1; }
  [ "${#acceso}" -ge 12 ] || { echo "  ✗ Muy corta: mínimo 12 caracteres."; exit 1; }
  printf '%s' "$acceso" | gcloud secrets create "$SECRETO" --data-file=- --quiet
  unset acceso otra
  echo "  ✓ Contraseña guardada en Secret Manager"
else
  echo "  ✓ La contraseña ya está guardada (para cambiarla: gcloud secrets versions add $SECRETO --data-file=-)"
fi

cuenta="$(gcloud projects describe "$PROYECTO" --format='value(projectNumber)')-compute@developer.gserviceaccount.com"
gcloud secrets add-iam-policy-binding "$SECRETO" \
  --member="serviceAccount:$cuenta" --role=roles/secretmanager.secretAccessor --quiet >/dev/null

# --- La aplicación --------------------------------------------------------
echo "  → Construyendo y subiendo la imagen (la primera vez tarda unos minutos)"
gcloud run deploy "$SERVICIO" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 900 \
  --concurrency 4 \
  --max-instances 3 \
  --set-secrets "BRINGMEF29_ACCESO=$SECRETO:latest" \
  --set-env-vars "BRINGMEF29_SALIDA=/tmp/salida" \
  --quiet

url="$(gcloud run services describe "$SERVICIO" --region "$REGION" --format='value(status.url)')"
echo "  ✓ Aplicación desplegada"

echo "  → Poniendo Firebase Hosting por delante"
firebase deploy --only hosting --project "$PROYECTO" --non-interactive

echo
echo "  Listo."
echo
echo "    Cloud Run          $url"
echo "    Firebase Hosting   https://$PROYECTO.web.app"
echo
echo "  Usa la dirección de Cloud Run para las consultas: Hosting corta a los"
echo "  60 segundos y entrar al SII y armar los PDF puede pasarse de ahí."
echo
