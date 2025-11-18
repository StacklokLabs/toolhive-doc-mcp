# SQLite-vec builder stage - separate stage for better caching
FROM python:3.13-slim AS sqlite-vec-builder

# Install build dependencies for compiling sqlite-vec
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    make \
    git \
    gettext \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# Build sqlite-vec extension with cache mount for git and build artifacts
RUN --mount=type=cache,target=/var/cache/git \
    --mount=type=cache,target=/tmp/sqlite-vec-build \
    cd /tmp \
    && git clone --depth 1 --branch v0.1.6 https://github.com/asg017/sqlite-vec.git \
    && cd sqlite-vec \
    && make loadable \
    && mkdir -p /sqlite-vec-dist \
    && cp dist/vec0.* /sqlite-vec-dist/

# Main builder stage
FROM python:3.13-slim AS builder

# Create non-root user
RUN groupadd --gid 1000 app && \
    useradd --uid 1000 --gid app --shell /bin/bash --create-home app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory and change ownership
WORKDIR /app
RUN chown app:app /app

# Switch to non-root user
USER app

# Copy project files
COPY --chown=app:app pyproject.toml uv.lock README.md ./
COPY --chown=app:app src/ ./src/

# Set link mode to copy to avoid hardlink warnings across filesystems
ENV UV_LINK_MODE=copy

RUN --mount=type=cache,target=/home/app/.cache/uv,uid=1000,gid=1000 \
    uv sync --package toolhive-doc-mcp --no-dev --locked --no-editable

# Copy pre-built sqlite-vec extension
COPY --from=sqlite-vec-builder /sqlite-vec-dist/vec0.so /app/.venv/lib/python3.13/site-packages/sqlite_vec/vec0.so
USER root
RUN chown app:app /app/.venv/lib/python3.13/site-packages/sqlite_vec/vec0.so
USER app

# Pre-download fastembed models
FROM builder AS model-downloader

# Switch to root to create cache directory, then switch back to app user
USER root
RUN mkdir -p /app/.cache/fastembed && chown -R app:app /app/.cache
USER app

# Set cache directory for fastembed models
ENV FASTEMBED_CACHE_PATH=/app/.cache/fastembed

# Pre-download the embedding model by instantiating TextEmbedding
RUN --mount=type=cache,target=/app/.cache/uv,uid=1000,gid=1000 \
    /app/.venv/bin/python -c "\
import os; \
print(f'FASTEMBED_CACHE_PATH: {os.environ.get(\"FASTEMBED_CACHE_PATH\")}'); \
from fastembed import TextEmbedding; \
print('Downloading embedding model...'); \
model = TextEmbedding(model_name='BAAI/bge-small-en-v1.5'); \
print('Model downloaded successfully')"

# Build documentation database stage (optional - can be skipped if pre-built data provided)
FROM model-downloader AS db-builder

# Switch to root to create data directory, then switch back to app user
USER root
RUN mkdir -p /app/data/website_cache && chown -R app:app /app/data
USER app

# Copy sources configuration
COPY --chown=app:app sources.yaml /app/sources.yaml

# Set environment variables for build process
ENV FASTEMBED_CACHE_PATH=/app/.cache/fastembed
ENV DOCS_WEBSITE_CACHE_PATH=/app/data/website_cache
ENV VECTOR_DB_PATH=/app/data/docs.db

# Run the build process to generate and embed documentation
# Use --mount=type=secret for GITHUB_TOKEN to avoid exposing it in the image
# This stage can be skipped if pre-built data is provided via build context
RUN --mount=type=cache,target=/app/.cache/uv,uid=1000,gid=1000 \
    --mount=type=secret,id=github_token,uid=1000,gid=1000 \
    GITHUB_TOKEN=$(cat /run/secrets/github_token 2>/dev/null || echo "") \
    uv run --package toolhive-doc-mcp src/build.py

# Base runner stage - common setup for both build variants
FROM python:3.13-slim AS runner-base

# Create non-root user (same as builder stage)
RUN groupadd --gid 1000 app && \
    useradd --uid 1000 --gid app --shell /bin/bash --create-home app

# Create app directory and set ownership
WORKDIR /app
RUN chown app:app /app

# Copy the environment
COPY --from=builder --chown=app:app /app/.venv /app/.venv

# Copy pre-downloaded fastembed models
COPY --from=model-downloader --chown=app:app /app/.cache/fastembed /app/.cache/fastembed

# Switch to non-root user
USER app

# Set default environment variables for container deployment
ENV FASTEMBED_CACHE_PATH=/app/.cache/fastembed
ENV DOCS_WEBSITE_URL=https://docs.stacklok.com/toolhive
ENV DOCS_WEBSITE_CACHE_PATH=/app/data/website_cache
ENV DOCS_WEBSITE_PATH_PREFIX=/toolhive
ENV VECTOR_DB_PATH=/app/data/docs.db

# Run the MCP server using the console script entry point
CMD ["/app/.venv/bin/toolhive-doc-mcp"]

# Default runner - builds database during image build (slower for multi-platform)
FROM runner-base AS runner
COPY --from=db-builder --chown=app:app /app/data /app/data

# Pre-built runner - uses external pre-built database (faster for multi-platform)
# Usage: --build-context prebuilt-data=./path/to/data --target runner-prebuilt
FROM scratch AS prebuilt-data
FROM runner-base AS runner-prebuilt
COPY --from=prebuilt-data --chown=app:app / /app/data/
