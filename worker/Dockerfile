# worker/Dockerfile — multi-stage build
# Build context: worker/  (self-contained)
#
#   prod (default):
#     container build -t gnucash-mcp:latest worker/
#
#   dev:
#     container build --target dev -t gnucash-mcp:dev worker/
#
# Ubuntu 26.04 with GnuCash 5.14 from universe (no PPA required)

# ── base ─────────────────────────────────────────────────────────────────────
# GnuCash + Python bindings + uv-managed venv + gnucash_mcp package.
FROM ubuntu:26.04 AS base

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      gnucash \
      python3-gnucash \
      python3-pip \
      python3-dev \
      curl \
      ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Create a venv that can see apt-installed system packages (python3-gnucash)
RUN uv venv --system-site-packages /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY pyproject.toml /src/pyproject.toml
COPY gnucash_mcp/ /src/gnucash_mcp/

# uv sync installs the project and its dependencies; creates uv.lock if absent
RUN uv sync --project /src --no-dev

WORKDIR /data
ENV GNUCASH_BOOK_PATH=/data/project.gnucash

ENTRYPOINT ["python3", "-m", "gnucash_mcp"]

# ── prod ─────────────────────────────────────────────────────────────────────
# Adds scripts (init_book.py etc.) to the base image.
FROM base AS prod

COPY scripts/ /src/scripts/

# ── dev ──────────────────────────────────────────────────────────────────────
# Adds ruff, pyright, and dev dependencies (pytest, hypothesis, etc.).
FROM base AS dev

RUN uv tool install ruff && \
    uv tool install pyright && \
    uv sync --project /src

# ── default ───────────────────────────────────────────────────────────────────
# `container build worker/` with no --target produces the prod image.
FROM prod
