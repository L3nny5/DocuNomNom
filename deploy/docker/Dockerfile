# syntax=docker/dockerfile:1.7
#
# DocuNomNom v1 production image.
#
# Multi-stage layout:
#   - frontend-build: builds the Vite/React static bundle.
#   - backend:        runs the FastAPI app and the worker process from the
#                     same image (different commands).
#
# Image contents:
#   - Python 3.12 (slim Debian trixie)
#   - OCRmyPDF + Tesseract (eng + deu language packs)
#   - Ghostscript / unpaper / qpdf / pngquant (OCRmyPDF runtime deps)
#   - tini as PID 1 (clean signal handling for the worker)
#   - gosu for the entrypoint's PUID/PGID drop
#   - The backend wheel + the prebuilt frontend assets
#
# Base image is pinned to Debian trixie (stable as of 2025+) because
# bookworm ships Ghostscript 10.0.0 which contains the upstream
# regressions that corrupt PDFs when combined with ocrmypdf's
# --skip-text / --redo-ocr (the error message OCRmyPDF raises names
# the 10.0.0..10.02.0 range explicitly). Trixie ships Ghostscript
# 10.05.1 which is well past that broken window.
#
# Runtime model (v1 invariant):
#   - Two services share this image: `api` (uvicorn) and `worker`
#     (single replica). The single-worker invariant is also enforced
#     by an advisory PID-file lock under work_dir at startup.

ARG NODE_VERSION=20-trixie-slim
ARG PYTHON_VERSION=3.12-slim-trixie

# ---------- frontend build ----------
FROM node:${NODE_VERSION} AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- backend runtime ----------
FROM python:${PYTHON_VERSION} AS backend
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DOCUNOMNOM_LOG_FORMAT=json

# OCRmyPDF shells out to Tesseract, Ghostscript, unpaper, qpdf and
# (optionally) pngquant. We install those as system packages. The
# ocrmypdf Python library itself comes from PyPI a few layers below —
# the Debian ``ocrmypdf`` apt package installs it for the system's
# Python, which is NOT on the import path of the Python 3.12
# interpreter shipped by the slim base image, so ``import ocrmypdf``
# would fail at runtime with ``ocr_config_error``. tini is used as
# PID 1 so SIGTERM reaches the worker cleanly; gosu drops to the
# unprivileged ``app`` user.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        tini \
        gosu \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-deu \
        ghostscript \
        unpaper \
        qpdf \
        pngquant \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g 1000 app && useradd -m -u 1000 -g 1000 app

WORKDIR /app

COPY backend/pyproject.toml backend/README.md /app/backend/
COPY backend/src /app/backend/src
# Install the backend + the ``ocr`` extra so the OCRmyPDF backend is
# actually importable from Python 3.12 at runtime.
RUN pip install --no-cache-dir "/app/backend[ocr]"

COPY --from=frontend-build /build/frontend/dist /app/frontend-dist

COPY deploy/scripts/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Default mount points; overridable via DOCUNOMNOM__PATHS__* env vars.
VOLUME ["/data/input", "/data/output", "/data/work", "/data/archive", "/config"]

EXPOSE 8080

LABEL org.opencontainers.image.title="DocuNomNom" \
      org.opencontainers.image.description="PDF auto-splitting service for paperless-ngx" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.source="https://github.com/" \
      org.opencontainers.image.licenses="Proprietary"

# Image-level healthcheck for the API. Compose overrides this for the
# worker because the worker has no HTTP surface.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8080/api/v1/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "docunomnom.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
