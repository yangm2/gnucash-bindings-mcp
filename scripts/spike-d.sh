#!/usr/bin/env bash
# Spike D — Read-only mount enforcement
#
# Tests whether macOS GnuCash 5.15, opened against a -readonly hdiutil mount,
# truly cannot write to the book file.
#
# MANUAL STEP REQUIRED: when GnuCash opens, try Cmd-S (File > Save), then quit.
# The script pauses and waits for you to do this.
#
# Usage: ./spike-d.sh [path/to/book.gnucash]
#   If no book is given, uses ~/spike-test.sparsebundle which must already exist
#   and contain a test.gnucash (run spike-b.sh first, or create one manually).

set -euo pipefail

SPARSE="${HOME}/spike-test.sparsebundle"
MOUNT="/Volumes/GnuCash-RO"
BOOK="${1:-$MOUNT/spike-cross-version.gnucash}"

# Detach any existing read-only mount at this path
if mount | grep -q "$MOUNT"; then
    echo "Detaching existing mount at $MOUNT..."
    hdiutil detach "$MOUNT" -force
fi

echo "Attaching $SPARSE read-only at $MOUNT..."
hdiutil attach -readonly -mountpoint "$MOUNT" -nobrowse "$SPARSE"

if [[ ! -f "$BOOK" ]]; then
    echo "ERROR: $BOOK not found — run spike-b.sh first to create a test book,"
    echo "or specify a path to an existing .gnucash file as \$1."
    hdiutil detach "$MOUNT" -force
    exit 1
fi

# Record pre-open state
BEFORE_HASH=$(md5 -q "$BOOK")
BEFORE_FILES=$(ls -la "$MOUNT/")
echo ""
echo "Pre-open state:"
echo "  Book hash: $BEFORE_HASH"
echo "  Directory:"
echo "$BEFORE_FILES" | sed 's/^/    /'

echo ""
echo "Opening GnuCash..."
echo ">>> MANUAL STEP: try File > Save (Cmd-S) in GnuCash, then quit GnuCash <<<"
open -a GnuCash "$BOOK"

echo ""
read -r -p "Press ENTER after GnuCash has quit..."

# Record post-close state
AFTER_HASH=$(md5 -q "$BOOK" 2>/dev/null || echo "absent")
AFTER_FILES=$(ls -la "$MOUNT/")

echo ""
echo "Post-close state:"
echo "  Book hash: $AFTER_HASH"
echo "  Directory:"
echo "$AFTER_FILES" | sed 's/^/    /'

echo ""
# Check for lock or backup files
LCK_COUNT=$({ ls "$MOUNT/"*.LCK "$MOUNT/"*.LNK 2>/dev/null || true; } | wc -l | tr -d ' ')
BACKUP_COUNT=$({ ls "$MOUNT/"*.gnucash.* 2>/dev/null | grep -v "^$BOOK$" || true; } | wc -l | tr -d ' ')

if [[ "$BEFORE_HASH" == "$AFTER_HASH" ]]; then
    echo "PASS: book file unchanged (hash match)"
else
    echo "FAIL: book file was modified (hash mismatch)"
fi

if [[ "$LCK_COUNT" -eq 0 ]]; then
    echo "PASS: no .LCK or .LNK files left"
else
    echo "FAIL: lock files found: $(ls "$MOUNT/"*.LCK "$MOUNT/"*.LNK 2>/dev/null)"
fi

if [[ "$BACKUP_COUNT" -eq 0 ]]; then
    echo "PASS: no backup .gnucash.* files created"
else
    echo "FAIL: backup files found: $(ls "$MOUNT/"*.gnucash.* 2>/dev/null | grep -v "^$BOOK$")"
fi

echo ""
echo "Detaching read-only mount..."
hdiutil detach "$MOUNT"
