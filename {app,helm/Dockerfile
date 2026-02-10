# ============================================================
# Multi‑stage Dockerfile for City Population API
# ============================================================

# ---------- Stage 1: build & test ----------
FROM python:3.12-slim AS builder

WORKDIR /build

COPY app/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------- Stage 2: production image ----------
FROM python:3.12-slim AS production

# Security: run as non‑root
RUN groupadd -r appuser && useradd -r -g appuser -s /sbin/nologin appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY app/ ./app/

# Metadata
LABEL maintainer="SRE Candidate"
LABEL description="City Population API — FastAPI + Elasticsearch"

# Switch to non‑root user
USER appuser

EXPOSE 8000

# Health check built into the container
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--log-level", "info"]
