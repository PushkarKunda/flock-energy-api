# Production image for the Urja Meter Ops REST API + dashboard.
# Secrets (URJA_USER / URJA_PASSWORD / URJA_PORTAL_BASE_URL) are injected at
# runtime via environment — never baked into the image.
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Runtime payload only: the application package and the exported OpenAPI spec.
# Tests, fixtures, docs and local config are excluded via .dockerignore.
COPY app ./app
COPY openapi.json .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
