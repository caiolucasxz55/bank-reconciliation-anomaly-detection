# API image: serves the FastAPI app (which applies database migrations on startup). With
# LOAD_DEMO_DATA=true it first loads synthetic demo data into an empty database.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    BANKRECON_DATA_DIR=/app/data \
    LOAD_DEMO_DATA=false

WORKDIR /app

# Pinned dependencies change less often than the code: install them in their own layer.
COPY requirements.lock ./
RUN pip install -r requirements.lock

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-deps .
COPY docker/start.sh /usr/local/bin/start-api
RUN chmod 755 /usr/local/bin/start-api

RUN useradd --create-home --uid 10001 app && mkdir -p /app/data && chown app /app/data
USER app
# Generated data and pipeline results; a named volume keeps them next to the database.
VOLUME ["/app/data"]

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=60s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=2)"

CMD ["start-api"]
