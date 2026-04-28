#!/usr/bin/env zsh
# create-book-volume.zsh — one-time sparsebundle setup (M5.1)
# Runs on macOS host. Do NOT run inside the container.
#
# Usage: bin/create-book-volume.zsh [source-book-path]
#   source-book-path  Path to existing project.gnucash to migrate into the volume.
#                     Defaults to <project-root>/.test-data/project.gnucash

set -euo pipefail

SCRIPT_DIR=${0:A:h}
PROJECT_ROOT=${SCRIPT_DIR:h}

BUNDLE="$HOME/books/project.sparsebundle"
MOUNT="/Volumes/GnuCash-Project"
SOURCE_BOOK=${1:-"$PROJECT_ROOT/.test-data/project.gnucash"}

# ── guards ────────────────────────────────────────────────────────────────────

if mount | grep -qF "$MOUNT"; then
  print -u2 "ERROR: $MOUNT is already mounted."
  print -u2 "       Unmount first: hdiutil detach '$MOUNT'"
  exit 1
fi

if [[ -e "$BUNDLE" ]]; then
  print -u2 "ERROR: $BUNDLE already exists."
  print -u2 "       Delete it manually first if you want to start over."
  exit 1
fi

if [[ ! -f "$SOURCE_BOOK" ]]; then
  print -u2 "ERROR: Source book not found: $SOURCE_BOOK"
  print -u2 "       Run 'mise init-book' first, or pass the book path as argument."
  exit 1
fi

# ── create and mount sparsebundle ─────────────────────────────────────────────

print "Creating $HOME/books/ ..."
mkdir -p "$HOME/books"

print "Creating sparsebundle ..."
hdiutil create -size 100m -fs APFS -volname "GnuCash-Project" "$BUNDLE"

print "Attaching sparsebundle ..."
hdiutil attach -readwrite -nobrowse "$BUNDLE"

# ── migrate book ──────────────────────────────────────────────────────────────

print "Moving $SOURCE_BOOK → $MOUNT/project.gnucash ..."
mv "$SOURCE_BOOK" "$MOUNT/project.gnucash"

# ── verify via container ──────────────────────────────────────────────────────

print "Verifying GnuCash Python bindings can open the book ..."
container run --rm \
  -v "$MOUNT:/data:ro" \
  -e GNUCASH_BOOK_PATH=/data/project.gnucash \
  --entrypoint python3 \
  gnucash-mcp:latest \
  -c "
import gnucash, sys
try:
    s = gnucash.Session('/data/project.gnucash', gnucash.SessionOpenMode.SESSION_READ_ONLY)
    n = len(list(s.get_book().get_root_account().get_children()))
    s.end()
    print(f'OK: root account has {n} top-level children')
except Exception as e:
    print(f'FAIL: {e}', file=sys.stderr)
    sys.exit(1)
"

# ── summary ───────────────────────────────────────────────────────────────────

print ""
print "Done."
print "  Sparsebundle : $BUNDLE"
print "  Mounted at   : $MOUNT"
print "  Book         : $MOUNT/project.gnucash"
print ""
print "The volume is mounted read-write. The MCP proxy manages mount/unmount."
print "To inspect with the GnuCash GUI (read-only), use: bin/gnucash-browse"
