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
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "test_lock.gnucash")
    with Session(f"xml://{path}", SessionOpenMode.SESSION_NEW_STORE) as s1:
        try:
            s2 = Session(f"xml://{path}", SessionOpenMode.SESSION_NORMAL_OPEN)
            print("FAIL: expected ERR_BACKEND_LOCKED")
        except GnuCashBackendException as e:
            assert ERR_BACKEND_LOCKED in e.errors
            print("PASS: lock detection via GnuCashBackendException")
```

**Pass criteria:**
- `add-apt-repository ppa:gnucash/ppa` succeeds in container (network + GPG key)
- `apt-get install python3-gnucash` installs without errors
- `import gnucash` succeeds without error
- `Session(path, SessionOpenMode.SESSION_NEW_STORE)` creates a valid new book
- `book.get_root_account()` returns an Account object
- Early-save pattern (save before mutations) completes without error
- Session save/end/reopen cycle completes without error
- Lock detection raises `GnuCashBackendException` with `ERR_BACKEND_LOCKED`
- Record installed GnuCash version in `SPIKE_RESULTS.md` for Spike C planning

**Fail path:** If PPA installation fails in container:
1. Install from Noble universe directly (no PPA): `apt-get install python3-gnucash`
   gives GnuCash 5.5 — functional but further behind macOS 5.15; Spike C becomes
   more important
2. Fall back to build from source at 5.14 or 5.15 (~30 min build, original plan)

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

**Fail path:**
1. The GnuCash XML schema has been stable across 5.x minor releases; a migration
   prompt is unexpected but possible if 5.15 introduced schema changes. Check the
   GnuCash 5.15 release notes for any XML format changes.
2. Pin macOS GnuCash to 5.14 (download specific .dmg from gnucash.org) — eliminates
   the gap entirely
3. Wait for PPA to publish 5.15 for Noble, update container pin

---

### Spike D — Read-only mount enforcement

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

**Fail path:** If GnuCash writes through a read-only mount:
1. macOS sandbox profile (`sandbox-exec`) to restrict GnuCash file writes
2. Dedicated low-privilege macOS user account for GUI-only access

---

### Spike E — APFS snapshots on sparsebundle volume

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

**Fail path:** If `tmutil` only works on the boot volume:
1. Use `cp -c` (APFS clone-copy) for cheap pre-session backups:
   `cp -c "$BOOK" "${BOOK}.pre-$(date +%Y%m%d-%H%M%S).gnucash"`
   This is near-instant on APFS (copy-on-write) and gives equivalent point-in-time
   recovery for a single file
2. Accept GnuCash's own `.YYYYMMDDHHMMSS.gnucash` auto-backups as sufficient

---

### Spike F — Swift proxy HTTP transport and CoWork bridge (resolves KU-8, KU-9)

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

```swift
// spike-f/Sources/spike-f/main.swift — minimal Swift MCP proxy
// Uses NIO for HTTP, ContainerAPIClient for dispatch
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

```bash
# Run against a 26.04 container once released
apt-cache show gnucash | grep Version
```

**G2 — PPA availability:** Has `ppa:gnucash/ppa` published arm64 packages for
Ubuntu 26.04 (codename "oracular" or next LTS)?

```bash
# Check Launchpad PPA build status
curl -s "https://launchpad.net/~gnucash/+archive/ubuntu/ppa/+packages" \
  | grep -i "26\.\|oracular\|next-lts-codename"
```

> **Note:** As of April 2026, no PPAs for 26.04 exist yet. Do not block Phase 1 on
> this spike — run it in parallel once 26.04 is released.

**G3 — Migration smoke test:** If a 26.04 image with a working GnuCash package is
available, re-run Spike A and Spike C tests against it:
- `import gnucash` succeeds inside a 26.04 Apple Container
- Cross-version schema compatibility (container GnuCash version vs macOS 5.15)

**Decision matrix:**

| Scenario | Action |
|---|---|
| PPA publishes for 26.04, version ≥ 5.14 | Update `Dockerfile` to `FROM ubuntu:26.04`, re-run Spike A/C |
| Universe ships GnuCash ≥ 5.14 (PPA not needed) | Drop PPA dependency, update `Dockerfile` |
| Neither available at Phase 1 start | Stay on 24.04; revisit after 26.04 PPA publishes |
| GnuCash version < 5.14 on 26.04 | Stay on 24.04 indefinitely; document in `SPIKE_RESULTS.md` |

**Note:** If the base image changes to 26.04, Spike C must be re-validated against
the new container GnuCash version and the macOS 5.15 book file.

---

### Phase 0 exit criteria

All spikes must produce a written result (PASS or documented FAIL + chosen fallback)
before Phase 1 begins. Record results in `SPIKE_RESULTS.md`.

| Spike | Status | Fallback chosen (if FAIL) |
|---|---|---|
| A — Python bindings | ☐ | |
| B — VirtioFS | ☐ | |
| C — Schema compatibility | ☐ | |
| D — Read-only enforcement | ☐ | |
| E — APFS snapshots | ☐ | |
| F — HTTP transport + CoWork bridge | ☐ | |
| G — Ubuntu 26.04 evaluation | ☐ (non-blocking; run after 26.04 release) | |

---

