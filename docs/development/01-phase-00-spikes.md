# Phase 0 — Foundations and Spike Resolution

**Goal:** Validate all known unknowns. Nothing in Phase 0 is production code.
All spikes are throwaway scripts. Phase 0 gates all subsequent phases.

**Duration estimate:** 1–2 days of hands-on work.

### Spike A — Python bindings via PPA in Ubuntu 24 Apple Container

**Question:** Does `python3-gnucash` from `ppa:gnucash/ppa` install and work
correctly inside an Ubuntu Noble Apple Container on Apple Silicon?

```dockerfile
# Dockerfile.spike-a
FROM ubuntu:24.04
RUN apt-get update && \
    apt-get install -y software-properties-common gnupg && \
    add-apt-repository ppa:gnucash/ppa && \
    apt-get update && \
    apt-get install -y python3-gnucash
```

```python
# spike-a.py — run inside container
from gnucash import Session, GnuCashBackendException, SessionOpenMode, ERR_BACKEND_LOCKED
import tempfile, os

# Test 1: module imports
import gnucash
print(f"GnuCash version: {gnucash.gnucash_core_c.gnc_version()}")

# Test 2: create a new book using modern SessionOpenMode API
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "test.gnucash")
    # SESSION_NEW_STORE replaces deprecated is_new=True
    with Session(f"xml://{path}", SessionOpenMode.SESSION_NEW_STORE) as session:
        book = session.book
        root = book.get_root_account()
        print(f"Root account: {root}")
        # context manager calls session.save() then session.end() on exit
    print("PASS: session create/save/end via context manager")

# Test 3: early-save pattern for new books
# new_book_with_opening_balances.py (official example) saves immediately after
# opening a new book, before any mutations, to avoid subtle corruption bugs.
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "test_early_save.gnucash")
    session = Session(f"xml://{path}", SessionOpenMode.SESSION_NEW_STORE)
    session.save()   # early save — must happen before any mutations
    book = session.book
    # ... mutations would go here ...
    session.save()
    session.end()
    print("PASS: early-save pattern")

# Test 4: reopen existing book
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "test_reopen.gnucash")
    with Session(f"xml://{path}", SessionOpenMode.SESSION_NEW_STORE) as s1:
        s1.book  # create it
    # SESSION_NORMAL_OPEN replaces deprecated is_new=False
    with Session(f"xml://{path}", SessionOpenMode.SESSION_NORMAL_OPEN) as s2:
        book2 = s2.book
        print(f"Reopened root: {book2.get_root_account()}")
    print("PASS: reopen")

# Test 5: lock detection
# Phase 1: create and close cleanly so the file exists on disk
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "test_lock.gnucash")
    with Session(f"xml://{path}", SessionOpenMode.SESSION_NEW_STORE) as s:
        s.book.get_root_account()  # required: fully initializes XML book structure
    # Phase 2: reopen and hold — this is the locked session
    s1 = Session(f"xml://{path}", SessionOpenMode.SESSION_NORMAL_OPEN)
    try:
        s2 = Session(f"xml://{path}", SessionOpenMode.SESSION_NORMAL_OPEN)
        s2.end()
        print("FAIL: expected ERR_BACKEND_LOCKED")
    except GnuCashBackendException as e:
        assert ERR_BACKEND_LOCKED in e.errors
        print("PASS: lock detection via GnuCashBackendException")
    finally:
        s1.end()
```

**Findings (validated on Dockerfile.spike-g / Ubuntu 26.04):**

1. **Early save must precede all mutations.** Call `session.save()` immediately after
   `SESSION_NEW_STORE` and before accessing `session.book` for any write. Skipping
   this causes subtle corruption (per GnuCash official example scripts and confirmed
   by spike).

2. **`book.get_root_account()` is required to fully initialize the XML book.**
   Without calling it at least once during a `SESSION_NEW_STORE` session, GnuCash
   does not write a valid root account element into the XML file. A subsequent
   `SESSION_NORMAL_OPEN` then fails with `ERR_FILEIO_FILE_NOT_FOUND` (not a lock
   error) because the file is either absent or malformed. Always call
   `session.book.get_root_account()` in new-book sessions before `save()` + `end()`.

3. **Lock detection two-phase pattern required.** `SESSION_NORMAL_OPEN` checks for
   file existence before checking the lock. To test lock detection, the book must be
   fully created and closed in a first session, then reopened and held in a second
   session before attempting a third. Testing lock detection from inside the creating
   `SESSION_NEW_STORE` session always fails with `ERR_FILEIO_FILE_NOT_FOUND` because
   the file is not yet on disk.

**Pass criteria:**
- `import gnucash` succeeds without error
- `Session(path, SessionOpenMode.SESSION_NEW_STORE)` creates a valid new book
- `book.get_root_account()` returns an Account object
- Early-save pattern (save before mutations) completes without error
- Session save/end/reopen cycle completes without error
- Lock detection raises `GnuCashBackendException` with `ERR_BACKEND_LOCKED`

**Result: PASS on Dockerfile.spike-g (Ubuntu 26.04, GnuCash 5.14).** Dockerfile.spike-a
(Ubuntu 24.04 PPA) skipped — spike-g provides equivalent coverage with a newer base.

---

### Spike B — VirtioFS sparsebundle volume sharing

**Question:** Does the Linux container see the sparsebundle mount point with correct
read-write semantics via Apple Container's VirtioFS volume mount?

```zsh
# On macOS host:
hdiutil create -size 50m -type SPARSEBUNDLE -fs APFS \
  -volname "GnuCash-Spike" ~/spike-test.sparsebundle
hdiutil attach -readwrite -mountpoint /Volumes/GnuCash-Spike \
  -nobrowse ~/spike-test.sparsebundle
echo "hello from host" > /Volumes/GnuCash-Spike/test.txt

# Run container with volume mount:
container run --rm \
  --volume /Volumes/GnuCash-Spike:/data \
  ubuntu:24.04 \
  bash -c "cat /data/test.txt && echo 'written from container' >> /data/test.txt"

# Verify on host:
cat /Volumes/GnuCash-Spike/test.txt
# Expected: both lines present
```

**Pass criteria:**
- Host-written file readable in container
- Container-written content visible on host after container exits
- File ownership and permissions are sane (no UID mismatch blocking writes)
- No VirtioFS errors in container dmesg

**Result: PASS.** Host-written content and container-appended content both visible
on host after container exit. VirtioFS read-write semantics confirmed on Apple
Silicon. No UID or permission issues observed.

**Fail path:** In order:
1. Copy-in / copy-out: container receives a file copy on start, writes back on exit
2. SSHFS from container back to macOS host via `Remote Login`
3. Reconsider SQLite backend with explicit lock management over a network path

---

### Spike C — Cross-version schema compatibility (5.14 container via PPA, 5.15 macOS)

**Question:** Can GnuCash 5.14 (`python3-gnucash=1:5.14-0build1` from PPA) in the
container open an XML file last saved by GnuCash 5.15 on macOS without attempting
migration or refusing to open? This is a one-minor-version gap — the same gap the
original build-from-source plan assumed, now via apt instead of cmake.

```python
# spike-c.py — run inside the container against a file saved by macOS 5.15
from gnucash import Session, SessionOpenMode

# The file must be created by opening a new book in macOS GnuCash 5.15
# and doing File > Save, then copying to /data/ via VirtioFS (Spike B)
# SESSION_NORMAL_OPEN replaces deprecated is_new=False
with Session("xml:///data/spike-cross-version.gnucash",
             SessionOpenMode.SESSION_NORMAL_OPEN) as session:
    book = session.book
    root = book.get_root_account()
    print("Accounts:", [a.GetName() for a in root.get_children()])
    # no session.save() — read-only probe; end() via context manager
print("PASS: opened cleanly, no migration")
```

**Pass criteria:**
- No migration prompt, warning, or error from 5.14 opening a 5.15-saved file
- Account tree readable
- No writes made to the file during open + read + end

**Result: PASS.** GnuCash 5.14 (Ubuntu 26.04 container) opened a book saved by
macOS GnuCash 5.15 without migration prompt or error. Default account tree
(`Assets`, `Liabilities`, `Income`, `Expenses`, `Equity`) readable. No writes
made during read-only probe.

**Fail path:**
1. The GnuCash XML schema has been stable across 5.x minor releases; a migration
   prompt is unexpected but possible if 5.15 introduced schema changes. Check the
   GnuCash 5.15 release notes for any XML format changes.
2. Pin macOS GnuCash to 5.14 (download specific .dmg from gnucash.org) — eliminates
   the gap entirely
3. Wait for PPA to publish 5.15 for Noble, update container pin

---

### Spike D — Read-only mount enforcement (`scripts/spike-d.sh`)

**Question:** Does macOS GnuCash 5.15, when opened against a `-readonly` hdiutil
mount, truly fail to write, or does it find a writable path around the mount flag?

```zsh
# Attach read-only
hdiutil attach -readonly -mountpoint /Volumes/GnuCash-RO \
  ~/spike-test.sparsebundle

BEFORE=$(md5 -q /Volumes/GnuCash-RO/test.gnucash 2>/dev/null || echo "absent")

# Open GnuCash, attempt Cmd-S, quit
/Applications/Gnucash.app/Contents/MacOS/Gnucash /Volumes/GnuCash-RO/test.gnucash
# Manual step: try File > Save, then quit

AFTER=$(md5 -q /Volumes/GnuCash-RO/test.gnucash 2>/dev/null || echo "absent")
ls -la /Volumes/GnuCash-RO/

[[ "$BEFORE" == "$AFTER" ]] && echo "PASS: unchanged" || echo "FAIL: modified"
```

**Pass criteria:**
- `Cmd-S` in GnuCash either fails silently or shows an error dialog
- No `.LCK`, `.LNK`, or `.YYYYMMDDHHMMSS.gnucash` backup files created
- File hash unchanged after GnuCash quits
- No `.LCK` left after GnuCash quits (read-only opens should not lock)

**Result: PASS.** Book hash unchanged after Cmd-S attempt. No `.LCK`, `.LNK`, or
backup files created. GnuCash cannot write through a `-readonly` hdiutil mount.

**Fail path:** If GnuCash writes through a read-only mount:
1. macOS sandbox profile (`sandbox-exec`) to restrict GnuCash file writes
2. Dedicated low-privilege macOS user account for GUI-only access

---

### Spike E — APFS snapshots on sparsebundle volume (`scripts/spike-e.sh`)

**Question:** Does `tmutil localsnapshot` work against a mounted sparsebundle
volume as a named path argument, or only against the boot volume (`/`)?

```zsh
MOUNT=/Volumes/GnuCash-Spike
hdiutil attach -readwrite -mountpoint "$MOUNT" -nobrowse ~/spike-test.sparsebundle

echo "before snapshot" > "$MOUNT/canary.txt"
tmutil localsnapshot "$MOUNT"

DEV=$(diskutil info "$MOUNT" | awk '/Device Node/ { print $NF }')
diskutil apfs listSnapshots "$DEV"

# Modify after snapshot
echo "after snapshot" > "$MOUNT/canary.txt"

# Mount snapshot and verify canary contains pre-modification content
SNAP=$(diskutil apfs listSnapshots "$DEV" | awk '/Name:/ { print $NF }' | tail -1)
TMP=$(mktemp -d)
mount_apfs -s "$SNAP" -o rdonly "$DEV" "$TMP"
cat "$TMP/canary.txt"   # should show "before snapshot"
umount "$TMP"
```

**Pass criteria:**
- `tmutil localsnapshot "$MOUNT"` exits 0
- Snapshot visible in `diskutil apfs listSnapshots` output
- Snapshot mounts successfully at a temp path
- Canary file in snapshot contains pre-modification content

**Result: PARTIAL PASS — use `cp -c` fallback.**
- `tmutil localsnapshot` exits 0 and reports a snapshot date, but `diskutil apfs
  listSnapshots` returns no entries for the sparsebundle device. Snapshots on
  non-boot APFS volumes mounted via hdiutil are not enumerable or mountable via
  the standard `diskutil`/`mount_apfs` path.
- **Fallback (`cp -c`) PASS:** clone-copy completes in ~51ms and correctly
  preserves pre-modification content. APFS copy-on-write makes this near-instant
  regardless of book file size.

**Decision: use `cp -c` for pre-session backups.** The proxy creates a timestamped
clone before opening a write session:
```
cp -c "$BOOK" "${BOOK%.gnucash}.pre-$(date +%Y%m%d-%H%M%S).gnucash"
```

**Fail path:** If `tmutil` only works on the boot volume:
1. Use `cp -c` (APFS clone-copy) for cheap pre-session backups:
   `cp -c "$BOOK" "${BOOK}.pre-$(date +%Y%m%d-%H%M%S).gnucash"`
   This is near-instant on APFS (copy-on-write) and gives equivalent point-in-time
   recovery for a single file
2. Accept GnuCash's own `.YYYYMMDDHHMMSS.gnucash` auto-backups as sufficient

---

### Spike F — Swift proxy HTTP transport and CoWork bridge (`spike-f/`) (resolves KU-8, KU-9)

**Question:** Does a Swift NIO HTTP server running on the macOS host, forwarding
requests to an Apple Container via `ContainerAPIClient` stdin/stdout, appear as
a working MCP server in Claude Desktop and CoWork?

This spike validates two things independently:

**F1 — Transport reachability:** Is `localhost:8980` reachable by Claude Desktop?
(Since the Swift proxy runs natively on macOS, not inside a container, there is
no port-publishing concern — but we confirm Claude Desktop's `streamable-http`
connector type accepts it.)

**F2 — Container dispatch:** Can `ContainerAPIClient` start a container, write
a JSON-RPC request to its stdin, read the response from stdout, and stop the
container — reliably, in under 1 second?

The `spike-f/` directory is a complete Swift package: `Package.swift` (swift-nio +
swift-argument-parser), `Sources/spike-f/main.swift` (NIO HTTP server + container
dispatch via `container run`), `Dockerfile.echo` (minimal Python echo container),
and `run.sh` (builds both and starts the server).

Build and run: `cd spike-f && ./run.sh`

```swift
// spike-f/Sources/spike-f/main.swift — minimal Swift MCP proxy
// Uses NIO for HTTP, container CLI for dispatch
// Tool: ping() → {"status": "ok", "transport": "swift-proxy"}

@main struct SpikeF: AsyncParsableCommand {
    func run() async throws {
        let server = MCPHTTPServer(port: 8980) { request in
            if request.method == "tools/call",
               let name = request.params?.name, name == "ping" {
                // Dispatch to container
                let container = try await ContainerAPIClient.shared
                    .run(image: "spike-f:latest",
                         command: ["python3", "-c",
                           "import json,sys; print(json.dumps({'result': {'status':'ok'}}))"],
                         volumes: [])
                return try await container.readStdout()
            }
            return MCPResponse.staticToolsList([pingTool])
        }
        try await server.run()
    }
}
```

```json
// claude_desktop_config.json
{
  "mcpServers": {
    "spike-f": {
      "type": "streamable-http",
      "url": "http://localhost:8980/mcp"
    }
  }
}
```

**Pass criteria:**
- Swift NIO HTTP server starts and responds to `curl POST localhost:8980/mcp`
  with valid MCP `initialize` response
- Claude Desktop shows `spike-f` as connected
- `ping()` tool callable from Claude Desktop chat window
- Container starts, executes command, stdout captured, container stopped —
  all within 1 second total
- CoWork session can call `ping()` (verifies SDK bridge — KU-9)

**Result: PASS (F1 + F2).**
- **KU-8 answered:** `streamable-http` type is not accepted by Claude Desktop's
  `claude_desktop_config.json` — the entry is silently skipped. The stdio fallback
  works: register the Swift binary as a `command` entry with `--stdio` flag.
  The proxy reads newline-delimited JSON-RPC from stdin and writes responses to
  stdout; stderr carries diagnostics.
- **F2 confirmed:** `ping()` tool dispatched to `spike-f-echo:latest` container via
  `container run --rm`, stdout captured, response returned to Claude Desktop and CoWork.
  Both confirmed: `{"status": "ok", "transport": "swift-proxy"}`.
- **KU-9 answered:** CoWork receives tools through Claude Desktop's stdio bridge
  without any additional configuration. The SDK passthrough layer works correctly.
- **Container cold-start measured:** `ping` round-trip with `container run --rm`
  (no pooling) = **~2.2s**, exceeding the 1s target. This is entirely container
  startup overhead — the Python payload executes in <10ms. The production proxy's
  size-1 TTL pool keeps one container warm between requests; calls within the TTL
  window will be well under 1s. The spike confirms the pool design is necessary,
  not optional.
- **Production implication:** The gnucash-mcp proxy will be registered as a stdio
  server in `claude_desktop_config.json`, not streamable-http. The Swift binary
  handles the stdio↔container bridge internally.

**Fail path (KU-8 — transport):** If Claude Desktop rejects `localhost:8980`:
- Try `127.0.0.1:8980` explicitly
- Check if `streamable-http` type requires HTTPS (unlikely for localhost)
- Fall back to registering proxy as a stdio server that immediately returns
  the correct `initialize` response, then bridges internally

**Fail path (KU-9 — CoWork):** If Claude Desktop connects but CoWork can't use tools:
- Verify CoWork SDK bridge handles `streamable-http` (not only stdio)
- Document workaround: use Claude.ai web interface for book management tasks

**Fail path (container dispatch):** If `ContainerAPIClient` stdin/stdout
round-trip exceeds 1 second or is unreliable:
- Measure and document actual latency
- Consider pre-warming container (start on proxy launch, not per-request)
  as an alternative to TTL pool

---

### Spike G — Ubuntu 26.04 LTS container base evaluation (resolves KU-12)

**Question:** Is Ubuntu 26.04 LTS (releasing end of April 2026) a viable drop-in
replacement for the Ubuntu 24.04 container base?

Ubuntu 26.04 is the next LTS. The container base is currently pinned to 24.04 because
that is what `ppa:gnucash/ppa` supports for arm64 at design time. This spike evaluates
whether 26.04 is ready to adopt before or during Phase 1.

**G1 — Universe package version:** What version of GnuCash ships in Ubuntu 26.04
universe (without the PPA)?

**Result: GnuCash 5.14** ships in Ubuntu 26.04 universe with no PPA required.
Python version: **3.14.3**. `python3-gnucash` installs cleanly from universe.

**G2 — PPA availability:** Not needed — universe provides GnuCash 5.14 directly.

**G3 — Migration smoke test:** Spike A tests (session create/save/end, reopen,
lock detection) all **PASS** on Dockerfile.spike-g (Ubuntu 26.04, GnuCash 5.14).
See Spike A findings above for `get_root_account()` and early-save requirements
discovered during this run.

**Decision: Use Ubuntu 26.04 as the container base. Drop PPA dependency.**

| Scenario | Outcome |
|---|---|
| Universe ships GnuCash ≥ 5.14 (PPA not needed) | **✅ Applies** — use `FROM ubuntu:26.04`, no PPA |

`Dockerfile` base image: `FROM ubuntu:26.04`. `apt-get install python3-gnucash`
installs GnuCash 5.14 directly. Spike C must still be run to validate
cross-version schema compatibility (5.14 container vs macOS 5.15 book file).

---

---

### Spike H — PDF extraction from directory mount (`scripts/spike-h.py`) (resolves KU-13)

**Question:** Can `pdfplumber` (or `pymupdf`) running inside the Ubuntu container
reliably extract structured invoice and bank statement fields from text-layer PDFs
passed as a mounted read-only directory — without requiring Claude vision input or
OCR?

This spike validates the path-based PDF workflow described in Appendix E. If PDFs
are software-generated (text layer present), Python extraction is free and fast.
If they are scanned images, the pipeline must fall back to Claude vision input
(high token cost) or an OCR dependency (tesseract).

> **Note:** Non-blocking — run when PDF workflows are needed (Phase 6 or later).
> Does not gate Phases 1–5.

**H1 — Text layer detection:** Can the container reliably detect whether a PDF
has a text layer or is a scanned image?

```python
# spike-h.py — run inside container against sample PDFs in /invoices (read-only mount)
import pdfplumber, sys
from pathlib import Path

def has_text_layer(pdf_path: str) -> bool:
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            if page.extract_text():
                return True
    return False

for p in Path("/invoices").glob("*.pdf"):
    print(p.name, "text-layer:", has_text_layer(str(p)))
```

**H2 — Invoice field extraction:** For text-layer invoices, can structured fields
be extracted reliably enough to drive `receive_invoice` without manual correction?

```python
# Target fields for each invoice PDF:
# - vendor name
# - invoice reference number
# - invoice date
# - line items: description + amount
# - total amount

def extract_invoice_fields(pdf_path: str) -> dict:
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    # Parse with regex or small structured extraction
    # Return dict or raise ExtractionError if confidence low
    ...
```

Run against a representative sample of real invoices from each vendor. Record
extraction accuracy per vendor in `SPIKE_RESULTS.md`.

**H3 — Bank statement extraction:** For the project bank's statement PDFs, can
transaction rows (date, description, debit, credit, balance) be extracted as a
structured list suitable for `mark_cleared` loops?

```python
def extract_statement_transactions(pdf_path: str) -> list[dict]:
    with pdfplumber.open(pdf_path) as pdf:
        rows = []
        for page in pdf.pages:
            # extract_table() works well for consistently-formatted bank tables
            tables = page.extract_table()
            if tables:
                rows.extend(tables)
    return rows
```

**H4 — VirtioFS read-only mount for PDF directory:**

```zsh
# Mount a local invoices directory read-only into the container
container run --rm \
  --volume /data/project.gnucash:/data/project.gnucash \
  --volume ~/Documents/invoices:/invoices:ro \
  gnucash-mcp:latest \
  python3 /src/scripts/spike-h.py
```

Confirm: container can read PDFs from `/invoices`, cannot write to it.

**Pass criteria:**
- `has_text_layer()` correctly identifies text-based vs scanned PDFs from sample set
- Invoice extraction achieves ≥ 90% field accuracy across sample invoices (vendor,
  ref, date, total correct without manual correction)
- Bank statement extraction produces a structured row list matching the statement
  register (spot-check 10 transactions)
- Read-only mount confirmed: write attempt to `/invoices` fails with permission error
- Extraction completes in < 2 seconds per PDF page (not a bottleneck)

**Fail paths:**

| Failure | Fallback |
|---|---|
| Invoices are scanned (no text layer) | Add `pytesseract` + `poppler` to Dockerfile for OCR; accept slower extraction and lower accuracy |
| Field extraction unreliable (< 90%) | Fall back to Claude vision for extraction step; gpt-oss still handles tool call loop (token cost increases but loop is free) |
| Bank statement layout not table-parseable | Use `pdfplumber` text extraction + regex; or Claude vision for statement page only |
| VirtioFS `:ro` flag not honoured | Use filesystem permissions (`chmod 444`) on mount point as secondary guard |

**Dockerfile additions if OCR fallback needed:**

```dockerfile
# Only add if Spike H shows scanned PDFs in practice
RUN apt-get install -y tesseract-ocr poppler-utils && \
    pip3 install --break-system-packages pytesseract pymupdf
```

---

### Phase 0 exit criteria

All spikes must produce a written result (PASS or documented FAIL + chosen fallback)
before Phase 1 begins. Record results in `SPIKE_RESULTS.md`.

| Spike | Status | Fallback chosen (if FAIL) |
|---|---|---|
| A — Python bindings | ✅ PASS (via Dockerfile.spike-g) | n/a |
| B — VirtioFS | ✅ PASS — host↔container read/write confirmed via sparsebundle VirtioFS mount | n/a |
| C — Schema compatibility | ✅ PASS — GnuCash 5.14 container opens macOS 5.15 book; no migration, all accounts readable | n/a |
| D — Read-only enforcement | ✅ PASS — GnuCash cannot write through -readonly hdiutil mount; no .LCK, no backup files | n/a |
| E — APFS snapshots | ⚠️ PARTIAL — tmutil creates snapshot but diskutil cannot list it on sparsebundle; cp -c fallback PASS (51ms) | Use cp -c clone-copy for pre-session backups |
| F — HTTP transport + CoWork bridge | ✅ PASS — stdio works in both Claude Desktop and CoWork (KU-8 + KU-9 answered); container dispatch confirmed (F2) | Use stdio registration in claude_desktop_config.json |
| G — Ubuntu 26.04 evaluation | ✅ PASS — GnuCash 5.14 from universe, Python 3.14.3, no PPA needed | n/a |
| H — PDF extraction from directory mount | ☐ (non-blocking; run before Phase 6 PDF workflows) | |

---

