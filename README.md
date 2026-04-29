# gnucash-mcp

GnuCash-backed MCP server for a construction project ledger. Claude is the
primary read-write interface; the macOS GnuCash GUI is read-only.

## Prerequisites

| Requirement | Notes |
|---|---|
| macOS 26+ | Apple Container requires macOS 26 |
| [Apple Container](https://github.com/apple/container) | Install via released binary |
| GnuCash 5.x | `/Applications/GnuCash.app` |
| [mise](https://mise.jdx.dev) | Task runner; `brew install mise` |
| Swift 6 toolchain | Included with Xcode 26+ |
| Claude Desktop | For MCP registration |

---

## One-time setup

**First-time only:**

```zsh
mise install-all
```

Runs in order: build container image → init book → create sparsebundle →
build and install Swift proxy → register with Claude Desktop.
Aborts if the sparsebundle already exists.

**To upgrade the proxy** (sparsebundle already in place):

```zsh
mise install-app
```

Rebuilds and reinstalls the Swift binary and refreshes the Claude Desktop
registration. Safe to re-run at any time. Restart Claude Desktop after the
first install or after any registration change.

**To uninstall:**

```zsh
mise uninstall-app
```

Removes the binary, LaunchAgent plist, and `gnucash-myproject` entry from
`claude_desktop_config.json`. Restart Claude Desktop afterwards. The
sparsebundle and book data are left untouched.

**Individual tasks:**

| Task | What it does | Re-runnable? |
|---|---|---|
| `mise build` | Build container image `gnucash-mcp:latest` | Yes |
| `mise init-book` | Create `.test-data/project.gnucash` | Yes |
| `mise create-book-volume` | Create `~/books/project.sparsebundle`, migrate book | No — aborts if bundle exists |
| `mise build-proxy` | Build Swift binary (release) | Yes |
| `mise install-app` | Install binary to `~/.local/bin`, register with Claude Desktop | Yes |
| `mise uninstall-app` | Remove binary, plist, and Claude Desktop registration | Yes |

---

## Daily-use workflow

### Start the MCP server (automatic via Claude Desktop)

Claude Desktop launches `gnucash-mcp start` on connection. The proxy:

1. Starts the container system if not running
2. Attaches `~/books/project.sparsebundle` read-write at `/Volumes/GnuCash-Project`
3. Creates a pre-session backup (`cp -c` APFS clone, ~50ms)
4. Pre-starts a warm container (blocks on stdin, ready for first tool call)

### Stop the MCP server

```zsh
gnucash-mcp stop      # sends SIGTERM; proxy drains pool, detaches volume, exits
```

Or quit Claude Desktop.

### Check status

```zsh
gnucash-mcp status    # shows mount state and container pool state
```

### Browse the book in GnuCash (read-only)

The MCP server must be stopped first (or not running).

```zsh
bin/gnucash-browse                          # uses ~/books/project.sparsebundle
bin/gnucash-browse /path/to/other.sparsebundle
```

The script:
- Guards against a live MCP mount or a running GnuCash process
- Attaches the sparsebundle read-only (`-readonly -nobrowse`)
- Detaches on quit, Ctrl-C, or force-kill (EXIT trap)
- Waits on the GnuCash PID directly (`wait $PID`) — not `open --wait-apps` —
  so the detach happens only after GnuCash fully releases all file handles

### Manual snapshot

```zsh
gnucash-mcp snapshot    # cp -c clone; prunes to 10 most recent
```

Backups are named `project.pre-YYYYMMDD-HHMMSS.gnucash` alongside the live
book inside the volume.

---

## Development

```zsh
mise build          # prod image: gnucash-mcp:latest
mise build-dev      # dev image: gnucash-mcp:dev (uv, ruff, pyright)
mise test           # pytest in dev container
mise lint           # ruff check + pyright in dev container
mise fmt            # ruff format in dev container
mise run            # one-shot dispatch, stdin→stdout, .test-data mounted
mise shell          # interactive shell, prod container
mise shell-dev      # interactive shell, dev container, source rw-mounted
mise clean          # remove .test-data/*.gnucash* and *.jsonl
```

Swift proxy tests:

```zsh
mise swift-test
```

---

## Recovery

### Restore from pre-session backup

1. Stop the MCP server: `gnucash-mcp stop`
2. Attach the volume read-write: `hdiutil attach ~/books/project.sparsebundle`
3. Identify the backup: `ls /Volumes/GnuCash-Project/project.pre-*.gnucash`
4. Open the backup directly in GnuCash to verify the state you want
5. Replace the live book:
   ```zsh
   cp /Volumes/GnuCash-Project/project.pre-YYYYMMDD-HHMMSS.gnucash \
      /Volumes/GnuCash-Project/project.gnucash
   ```
6. Detach: `hdiutil detach /Volumes/GnuCash-Project`
7. Restart the MCP server

### Stale mount after crash

If `gnucash-mcp start` reports the volume already mounted after a crash:

```zsh
hdiutil detach /Volumes/GnuCash-Project
gnucash-mcp start
```

### Missing or corrupt container image

```zsh
mise build
```

### Container system not running

```zsh
container system start
```

The proxy also starts the container system automatically on `gnucash-mcp start`.
