# =========================
# Builder stage
# =========================
FROM python:3.11-slim AS builder

# Environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System build deps (only for build stage)
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list && \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry (pinned)
RUN pip install poetry==1.8.3

# Configure Poetry to use a local venv
ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

# Install Python deps
COPY pyproject.toml poetry.lock* ./
RUN poetry install --only=main --no-root && rm -rf "$POETRY_CACHE_DIR"

# Copy application source (for things like Alembic env, etc.)
COPY . .

# =========================
# Runtime stage
# =========================
FROM python:3.11-slim AS runtime

# Build-time metadata (injected via Docker build args)
ARG APP_VERSION=dev
ARG GIT_COMMIT=unknown
ARG BUILD_TIME=unknown

# Environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_VERSION=${APP_VERSION} \
    GIT_COMMIT=${GIT_COMMIT} \
    BUILD_TIME=${BUILD_TIME}

WORKDIR /app

# Minimal runtime deps (no compilers)
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list && \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtualenv from builder (keep same path to preserve shebang)
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy application code
COPY . .

# Create logs directory (as before)
RUN mkdir -p logs

# Install CLI commands (resetadmin, etc.)
RUN chmod +x /app/scripts/resetadmin \
    && ln -s /app/scripts/resetadmin /usr/local/bin/resetadmin

# Expose ports (main + internal)
EXPOSE 8000
EXPOSE 8001

# Health check (both services)
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health && curl -f http://localhost:8001/health || exit 1

# Run the application via uvicorn directly (no Poetry at runtime)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 & uvicorn app.internal:internal_app --host 0.0.0.0 --port 8001 & wait"]
