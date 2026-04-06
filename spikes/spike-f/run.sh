#!/usr/bin/env bash
# Spike F — build and run the Swift MCP proxy + container echo image
#
# Usage: ./run.sh [--port 8980] [--skip-build]
# Run from the spike-f/ directory.

set -euo pipefail
cd "$(dirname "$0")"

PORT=8980
SKIP_BUILD=0

for arg in "$@"; do
    case "$arg" in
        --port=*) PORT="${arg#--port=}" ;;
        --skip-build) SKIP_BUILD=1 ;;
    esac
done

IMAGE="spike-f-echo:latest"

# ── Build echo container image ────────────────────────────────────────────────
if [[ "$SKIP_BUILD" -eq 0 ]]; then
    echo "Building echo container image ($IMAGE)..."
    container build -f Dockerfile.echo -t "$IMAGE" .
    echo ""
fi

# ── Build Swift proxy ─────────────────────────────────────────────────────────
if [[ "$SKIP_BUILD" -eq 0 ]]; then
    echo "Building Swift proxy..."
    swift build -c release 2>&1
    echo ""
fi

# ── Run ───────────────────────────────────────────────────────────────────────
echo "Starting spike-f on port $PORT..."
.build/release/spike-f --port "$PORT" --image "$IMAGE"
