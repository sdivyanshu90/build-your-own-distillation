# syntax=docker/dockerfile:1.7
# =============================================================================
# Distillery — multi-stage image used for BOTH the API and the worker.
# The runtime command is selected by the entrypoint (api | worker | migrate).
# CPU PyTorch is installed to keep the image lean; for GPU, base off an
# nvidia/cuda image and install the matching torch wheel.
# =============================================================================

# ---- Builder ----------------------------------------------------------------
FROM python:3.14-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Install the CPU-only PyTorch wheels.
    PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create an isolated virtualenv we can copy wholesale into the runtime stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /build
# Copy only what is needed to resolve and install dependencies first (cache layer).
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip wheel \
    && pip install ".[all]"

# ---- Runtime ----------------------------------------------------------------
FROM python:3.14-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:${PATH}" \
    HF_HOME=/home/distillery/.cache/huggingface \
    DISTILLERY_ENV=production

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system distillery \
    && useradd --system --gid distillery --create-home --home-dir /home/distillery distillery

COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=distillery:distillery src ./src
COPY --chown=distillery:distillery alembic.ini ./alembic.ini
COPY --chown=distillery:distillery migrations ./migrations
COPY --chown=distillery:distillery deploy/docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh \
    && mkdir -p /app/artifacts && chown distillery:distillery /app/artifacts

ENV PYTHONPATH=/app/src
USER distillery
EXPOSE 8000 9100

# Liveness check used by orchestrators and `docker run`.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# tini reaps zombies and forwards signals cleanly to the app.
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["api"]
