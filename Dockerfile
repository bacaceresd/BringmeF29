# Imagen para publicar BringmeF29 en Cloud Run.
#
# Parte de la imagen oficial de Playwright porque el programa necesita un
# Chromium de verdad en dos momentos: para entrar al SII y leer el F29 que
# guardaste, y para convertir el HTML en el PDF y la imagen que le mandas al
# cliente. Sin navegador dentro del contenedor no hay ni consulta ni documentos.
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    BRINGMEF29_SALIDA=/tmp/salida

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Nunca tu config/clientes.yml: los datos de tus clientes y las credenciales de
# tu correo no tienen por qué viajar dentro de la imagen. La configuración del
# despliegue no lleva ninguno de los dos.
COPY config/nube.yml ./config/nube.yml
ENV BRINGMEF29_CONFIG=/app/config/nube.yml

# Cloud Run manda el puerto por la variable PORT; 8080 es sólo el valor por
# defecto para correr la imagen a mano.
ENV PORT=8080
EXPOSE 8080

# Sin BRINGMEF29_ACCESO el arranque falla a propósito: ver web/nube.py.
CMD ["python", "-m", "bringmef29", "publicar"]
