# API image: installs the bankrecon package, loads the demo data on first start and serves
# the FastAPI app.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    BANKRECON_DATA_DIR=/app/data

WORKDIR /app

# Dependencies change less often than the code: install them in their own layer.
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > requirements.txt \
    && pip install -r requirements.txt

COPY src ./src
RUN pip install --no-deps .

RUN useradd --create-home --uid 10001 app && mkdir -p /app/data && chown app /app/data
USER app

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=60s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=2)"

# demo is idempotent: it only generates and loads data when the database is empty.
CMD ["sh", "-c", "bankrecon demo --data /app/data && exec uvicorn --factory bankrecon.api.app:create_app --host 0.0.0.0 --port 8000"]
