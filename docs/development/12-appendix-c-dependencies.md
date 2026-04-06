# Appendix C — Dependency Versions

### Swift proxy (`Sources/gnucash-mcp/`)

| Component | Version | Source |
|---|---|---|
| macOS | 26 Tahoe | System |
| Swift toolchain | 6.2 (Xcode-bundled) | Xcode 26+ — must NOT use swift.org toolchain |
| `apple/container` | 0.10.0+ | github.com/apple/container |
| `apple/swift-argument-parser` | 1.5.0+ | github.com/apple/swift-argument-parser |
| `apple/swift-nio` | 2.x | github.com/apple/swift-nio |

**Swift toolchain note:** macOS 26 system frameworks (Virtualization.framework,
`ContainerAPIClient`) require the Xcode-bundled Swift 6.2 toolchain. Do not use
the swift.org standalone toolchain — it will fail to link against system frameworks.
This matches the requirement in `buck2-macos-local-reapi`.

### Python container (`Docker/Dockerfile`, `src/`)

| Component | Version | Source |
|---|---|---|
| Ubuntu base | 26.04 LTS | Docker Hub `ubuntu:26.04` |
| GnuCash | 5.14 | Ubuntu 26.04 universe → `apt-get install python3-gnucash` |
| Python | 3.14.3 | Ubuntu 26.04 system default |
| mcp SDK | latest stable at build time | PyPI via uv |

**GnuCash version note:** Ubuntu 26.04 universe ships GnuCash 5.14 directly — no
PPA required. Spike C confirmed 5.14 opens files saved by macOS GnuCash 5.15
without migration prompt.

**Python dependency note:** The Python container does not depend on FastMCP or
uvicorn. The only MCP dependency is the base `mcp` SDK (for JSON-RPC type
definitions if desired, or omit entirely and use plain `json`). Pin the version
used at Phase 1 build time in `pyproject.toml`.

### macOS GUI

| Component | Version | Source |
|---|---|---|
| macOS GnuCash | 5.15 | gnucash.org .dmg |
| Apple Container runtime | 0.4.x+ | github.com/apple/container |

**GnuCash version policy:** When macOS GnuCash updates, check whether the PPA
has a matching version and update the container's pinned apt package. If the
minor version gap exceeds 1 (e.g. macOS at 5.17, container PPA at 5.14), treat
as blocking — rebuild container before next MCP write session.
The schema version guard (M8.2) enforces this automatically.
