#!/usr/bin/env bash
# Spike E — APFS snapshots on sparsebundle volume
#
# Tests whether tmutil localsnapshot works against a mounted sparsebundle,
# and if not, validates the cp -c clone-copy fallback.
#
# Requires: ~/spike-test.sparsebundle exists (run spike-b.sh first).
# Run as a user with sudo rights (mount_apfs requires root).

set -x -euo pipefail

SPARSE="${HOME}/spike-test.sparsebundle"
MOUNT="/Volumes/GnuCash-Spike"

# Detach any existing mount at this path
if mount | grep -q "$MOUNT"; then
    echo "Detaching existing mount at $MOUNT..."
    hdiutil detach "$MOUNT" -force
fi

echo "Attaching $SPARSE read-write at $MOUNT..."
hdiutil attach -readwrite -mountpoint "$MOUNT" -nobrowse "$SPARSE"

DEV=$(diskutil info "$MOUNT" | awk '/Device Node/ { print $NF }')
echo "Device node: $DEV"

# ── Test 1: tmutil localsnapshot ──────────────────────────────────────────────
echo ""
echo "=== Test 1: tmutil localsnapshot ==="

echo "before snapshot" > "$MOUNT/canary.txt"
echo "Wrote canary: $(cat "$MOUNT/canary.txt")"

echo "Taking snapshot..."
if tmutil localsnapshot "$MOUNT" 2>&1; then
    SNAP_NAME=$(diskutil apfs listSnapshots "$DEV" 2>/dev/null \
        | awk '/Name:/ { print $NF }' | tail -1)

    if [[ -z "$SNAP_NAME" ]]; then
        echo "FAIL (tmutil): snapshot taken but not visible in diskutil output"
    else
        echo "Snapshot: $SNAP_NAME"

        # Modify canary after snapshot
        echo "after snapshot" > "$MOUNT/canary.txt"
        echo "Modified canary: $(cat "$MOUNT/canary.txt")"

        # Mount snapshot and verify pre-modification content
        TMP=$(mktemp -d)
        echo "Mounting snapshot at $TMP..."
        if sudo mount_apfs -s "$SNAP_NAME" -o rdonly "$DEV" "$TMP" 2>&1; then
            SNAP_CANARY=$(cat "$TMP/canary.txt" 2>/dev/null || echo "missing")
            sudo umount "$TMP"
            rmdir "$TMP"

            if [[ "$SNAP_CANARY" == "before snapshot" ]]; then
                echo "PASS (tmutil): snapshot contains pre-modification content"
            else
                echo "FAIL (tmutil): snapshot canary = '$SNAP_CANARY' (expected 'before snapshot')"
            fi

            # Clean up snapshot
            echo "Deleting snapshot $SNAP_NAME..."
            sudo tmutil deletelocalsnapshots "$SNAP_NAME" 2>/dev/null || true
        else
            rmdir "$TMP" 2>/dev/null || true
            echo "FAIL (tmutil): snapshot exists but could not be mounted"
        fi
    fi
else
    echo "FAIL (tmutil): tmutil localsnapshot returned non-zero — tmutil may only work on boot volume"
    echo "Falling through to Test 2 (cp -c fallback)..."
fi

# ── Test 2: cp -c clone-copy fallback ────────────────────────────────────────
echo ""
echo "=== Test 2: cp -c clone-copy fallback ==="

BOOK="$MOUNT/canary.txt"
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="${BOOK%.txt}.pre-${STAMP}.txt"

echo "before clone" > "$BOOK"
echo "Original: $(cat "$BOOK")"

echo "Cloning with cp -c..."
START=$(python3 -c "import time; print(int(time.time()*1000))")
cp -c "$BOOK" "$BACKUP"
END=$(python3 -c "import time; print(int(time.time()*1000))")
ELAPSED=$(( END - START ))

echo "after clone" > "$BOOK"

BACKUP_CONTENT=$(cat "$BACKUP")
if [[ "$BACKUP_CONTENT" == "before clone" ]]; then
    echo "PASS (cp -c): backup contains pre-modification content (${ELAPSED}ms)"
else
    echo "FAIL (cp -c): backup content = '$BACKUP_CONTENT'"
fi

ls -lh "$MOUNT/"*.txt 2>/dev/null | sed 's/^/  /'

# ── Cleanup ───────────────────────────────────────────────────────────────────
echo ""
echo "Detaching $MOUNT..."
hdiutil detach "$MOUNT"
echo "Done."
