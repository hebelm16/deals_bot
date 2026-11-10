# Imagen mínima: los scrapers usan HTTP + BeautifulSoup, no un navegador.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# gosu permite preparar el volumen como root y ejecutar la app como usuario sin privilegios.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py config.py ./
COPY bot ./bot
COPY database ./database
COPY scrapers ./scrapers
COPY utils ./utils
COPY scripts ./scripts
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && mkdir -p /data /app/logs \
    && chown -R app:app /app /data

# Railway monta aquí el volumen persistente.
ENV DATABASE=/data/ofertas.db

EXPOSE 8443

HEALTHCHECK --interval=60s --timeout=10s --start-period=90s --retries=3 \
    CMD ["python", "scripts/healthcheck.py"]

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "main.py"]
