# Docker/Dockerfile — Phase 1 main container
# Build from repo root: container build -f Docker/Dockerfile -t gnucash-mcp:latest .
# Ubuntu 26.04 with GnuCash 5.14 from universe (no PPA required)

FROM ubuntu:26.04

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      gnucash \
      python3-gnucash \
      python3-pip \
      python3-dev && \
    rm -rf /var/lib/apt/lists/*

# Python project installed into container image
COPY pyproject.toml /src/pyproject.toml
COPY gnucash_mcp/ /src/gnucash_mcp/
COPY scripts/ /src/scripts/
RUN pip3 install --break-system-packages -e /src

WORKDIR /data
ENV GNUCASH_BOOK_PATH=/data/project.gnucash

ENTRYPOINT ["python3", "-m", "gnucash_mcp"]
