# gnucash-mcp

GnuCash-backed MCP server for a construction project ledger. Claude is the
primary read-write interface; the macOS GnuCash GUI is read-only.

## Supported Claude surfaces

| Surface | Works? | Notes |
|---|---|---|
| **Claude Desktop** | ✅ | Primary target. Registered as a local stdio `command` entry. |
| **Claude Code** | ✅ | Add to `.claude/settings.json` `mcpServers`. |
| CoWork / Claude.ai web | ❌ | CoWork only connects to remote HTTPS MCP servers; local stdio is not bridged. |

## Prerequisites

| Requirement | Minimum version | Notes |
|---|---|---|
| macOS | 26.0 | Required by Apple Container and the Swift proxy |
| [Apple Container](https://github.com/apple/container) | 0.12.1 | Install via released binary; proxy links against the `container` SDK at this version |
| GnuCash | 5.x | `/Applications/GnuCash.app`; container image uses GnuCash 5.14 from Ubuntu 26.04 universe |
| [mise](https://mise.jdx.dev) | any recent | Task runner; `brew install mise` |
| Swift toolchain | 6.x | Included with Xcode 26+ |
| Claude Desktop | any recent | For MCP registration |

---

## One-time setup

**First-time only:**

```zsh
mise install-all
```

Runs in order: build container image → init book → create sparsebundle →
build and install Swift proxy → register with Claude Desktop.
Aborts if the sparsebundle already exists.

**To upgrade** (sparsebundle already in place):

```zsh
mise install-app
```

Rebuilds the container image and Swift binary, installs the binary to
`~/.local/bin`, and refreshes the Claude Desktop registration. Safe to re-run
at any time. Restart Claude Desktop after any upgrade.

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
2. Verifies `gnucash-mcp:latest` container image exists
3. Attaches `~/books/project.sparsebundle` read-write at `/Volumes/GnuCash-Project`
4. Pre-starts a warm container (blocks on stdin, ready for first tool call)
5. Creates a `cp -c` APFS clone backup (~50ms) before the first write call in the session

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

### Debugging proxy startup

The proxy logs each startup step to stderr, which Claude Desktop captures in:

```
~/Library/Logs/Claude/mcp-server-gnucash-myproject.log
```

Expected lines on a clean start:

```
gnucash-mcp <commit> (<date>): start
gnucash-mcp: checking container system
gnucash-mcp: checking image
gnucash-mcp: attaching sparsebundle
sparsebundle: attaching ~/books/project.sparsebundle
sparsebundle: mounted at /Volumes/GnuCash-Project
gnucash-mcp: entering stdio transport
```

To validate the proxy without Claude Desktop, drive it with JSON-RPC over stdin:

```zsh
~/.local/bin/gnucash-mcp start <<'EOF'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"cli","version":"0"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"list_accounts","arguments":{}}}
EOF
```

A successful `tools/call` response looks like:
```json
{"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"[...]"}]}}
```
