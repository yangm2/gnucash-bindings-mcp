# Docker/Dockerfile — multi-stage build
# Build from repo root:
#
#   prod (default):
#     container build -f Docker/Dockerfile -t gnucash-mcp:latest .
#
#   dev:
#     container build -f Docker/Dockerfile --target dev -t gnucash-mcp:dev .
#
# Ubuntu 26.04 with GnuCash 5.14 from universe (no PPA required)

# ── base ─────────────────────────────────────────────────────────────────────
# GnuCash + Python bindings + gnucash_mcp package. No scripts, no dev tools.
FROM ubuntu:26.04 AS base

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      gnucash \
      python3-gnucash \
      python3-pip \
      python3-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /src/pyproject.toml
COPY gnucash_mcp/ /src/gnucash_mcp/
RUN pip3 install --break-system-packages -e /src

WORKDIR /data
ENV GNUCASH_BOOK_PATH=/data/project.gnucash

ENTRYPOINT ["python3", "-m", "gnucash_mcp"]

# ── prod ─────────────────────────────────────────────────────────────────────
# Adds scripts (init_book.py etc.) to the base image.
FROM base AS prod

COPY scripts/ /src/scripts/

# ── dev ──────────────────────────────────────────────────────────────────────
# Adds uv, ruff, and ty for local development and linting.
FROM base AS dev

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/root/.local/bin:${PATH}"

RUN uv tool install ruff && \
    uv tool install ty

# ── default ───────────────────────────────────────────────────────────────────
# `container build` with no --target produces the prod image.
FROM prod
