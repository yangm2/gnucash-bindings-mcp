#!/usr/bin/env bash
# Spike B — VirtioFS sparsebundle volume sharing test (macOS host)

set -euo pipefail

SPARSE=~/spike-test.sparsebundle
MOUNT=/Volumes/GnuCash-Spike

hdiutil create -size 50m -type SPARSEBUNDLE -fs APFS \
  -volname "GnuCash-Spike" "$SPARSE"
hdiutil attach -readwrite -mountpoint "$MOUNT" \
  -nobrowse "$SPARSE"
echo "hello from host" > "$MOUNT/test.txt"

# Run container with volume mount (adjust container CLI to your runtime)
container run --rm \
  --volume "$MOUNT:/data" \
  ubuntu:24.04 \
  bash -c "cat /data/test.txt && echo 'written from container' >> /data/test.txt"

# Verify on host:
cat "$MOUNT/test.txt"
