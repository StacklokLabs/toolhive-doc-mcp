# syntax=docker/dockerfile:1.4
# SQLite-vec builder stage - separate stage for better caching
FROM python:3.13-slim AS sqlite-vec-builder

# Install build dependencies for compiling sqlite-vec
# build-essential includes gcc and make, so they're not needed separately
# gettext-base provides envsubst which is required by sqlite-vec build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    gettext-base \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# Build sqlite-vec extension pinned to specific commit for reproducibility
# v0.1.6 tag points to commit 639fca5739fe056fdc98f3d539c4cd79328d7dc7
WORKDIR /tmp
RUN git clone https://github.com/asg017/sqlite-vec.git
WORKDIR /tmp/sqlite-vec
RUN git checkout 639fca5739fe056fdc98f3d539c4cd79328d7dc7 \
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

# Copy only dependency files first for better cache utilization
# This layer is cached unless pyproject.toml or uv.lock changes
COPY --chown=app:app pyproject.toml uv.lock ./

# Set link mode to copy to avoid hardlink warnings across filesystems
ENV UV_LINK_MODE=copy

# Install dependencies (cached layer unless lock file changes)
RUN --mount=type=cache,target=/home/app/.cache/uv,uid=1000,gid=1000 \
    uv sync --package toolhive-doc-mcp --no-dev --locked --no-editable

# Copy source code after dependencies (doesn't invalidate dependency cache)
COPY --chown=app:app README.md ./
COPY --chown=app:app src/ ./src/

# Reinstall the package now that source code is present
RUN --mount=type=cache,target=/home/app/.cache/uv,uid=1000,gid=1000 \
    uv sync --package toolhive-doc-mcp --no-dev --locked --no-editable

# Copy pre-built sqlite-vec extension using dynamic path resolution
# This avoids hardcoding Python version in the path
COPY --from=sqlite-vec-builder /sqlite-vec-dist/vec0.so /tmp/vec0.so
USER root
RUN PYTHON_SITE_PACKAGES=$(/app/.venv/bin/python -c "import sysconfig; print(sysconfig.get_path('purelib'))") \
    && mkdir -p "${PYTHON_SITE_PACKAGES}/sqlite_vec" \
    && cp /tmp/vec0.so "${PYTHON_SITE_PACKAGES}/sqlite_vec/vec0.so" \
    && chown app:app "${PYTHON_SITE_PACKAGES}/sqlite_vec/vec0.so" \
    && rm /tmp/vec0.so
USER app

# Pre-download fastembed models
FROM builder AS model-downloader

# Switch to root to create cache directories, then switch back to app user
# huggingface_hub needs /home/app/.cache for xet logging and downloads
USER root
RUN mkdir -p /app/.cache/fastembed /home/app/.cache && \
    chown -R app:app /app/.cache /home/app/.cache
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

# Install curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

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
