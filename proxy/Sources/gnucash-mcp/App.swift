import ArgumentParser
import Foundation

struct GnuCashMCP: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "gnucash-mcp",
        abstract: "GnuCash MCP proxy — stdio transport for Claude Desktop",
        subcommands: [Start.self, Stop.self, Status.self, Install.self, Snapshot.self],
        defaultSubcommand: Start.self,
    )
}

// MARK: - start (default)

extension GnuCashMCP {
    struct Start: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            abstract: "Start MCP server — reads JSON-RPC from stdin, writes to stdout",
        )

        mutating func run() async throws {
            // 1. Container system check
            try ContainerSystem.ensureRunning()
            guard try ContainerSystem.imageExists("gnucash-mcp:latest") else {
                fputs(
                    "error: container image 'gnucash-mcp:latest' not found\n"
                        + "       Build it first: mise build\n",
                    stderr,
                )
                Darwin.exit(1)
            }

            // 2. Sparsebundle and container pool
            let sparsebundle = SparsebundleManager()
            let pool = ContainerPool()
            setupSignalHandlers(pool: pool, sparsebundle: sparsebundle)

            // 3. Run stdio transport
            let transport = MCPStdioTransport(pool: pool, sparsebundle: sparsebundle)
            await transport.run()
        }

        private func setupSignalHandlers(pool: ContainerPool, sparsebundle: SparsebundleManager) {
            // Block default signal handling so DispatchSource takes over.
            signal(SIGTERM, SIG_IGN)
            signal(SIGINT, SIG_IGN)
            let termSource = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
            termSource.setEventHandler {
                Task {
                    await pool.drain()
                    try? sparsebundle.detach()
                    Darwin.exit(0)
                }
            }
            termSource.resume()
            let intSource = DispatchSource.makeSignalSource(signal: SIGINT, queue: .main)
            intSource.setEventHandler {
                Task {
                    await pool.drain()
                    try? sparsebundle.detach()
                    Darwin.exit(0)
                }
            }
            intSource.resume()
            _ = (termSource, intSource)
        }
    }
}

// MARK: - stop

extension GnuCashMCP {
    struct Stop: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            abstract: "Send SIGTERM to running gnucash-mcp process",
        )

        mutating func run() async throws {
            let result = shellOutput("pgrep", "-x", "gnucash-mcp")
            guard let pid = Int32(result.trimmingCharacters(in: .whitespacesAndNewlines)) else {
                print("gnucash-mcp is not running")
                return
            }
            kill(pid, SIGTERM)
            print("Sent SIGTERM to pid \(pid)")
        }
    }
}

// MARK: - status

extension GnuCashMCP {
    struct Status: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            abstract: "Show sparsebundle mount status",
        )

        mutating func run() async throws {
            let sparsebundle = SparsebundleManager()
            print(
                "Sparsebundle : \(sparsebundle.isMounted ? "mounted at \(sparsebundle.mountPoint)" : "not mounted")",
            )
        }
    }
}

// MARK: - install

extension GnuCashMCP {
    struct Install: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            abstract: "Write claude_desktop_config.json command entry and LaunchAgent plist",
        )

        @Option(name: .long, help: "Path to gnucash-mcp binary (defaults to this executable)")
        var binaryPath: String?

        mutating func run() async throws {
            let binary = binaryPath ?? CommandLine.arguments[0]
            let resolvedBinary = (binary as NSString).standardizingPath

            // claude_desktop_config.json
            let configDir =
                "\(NSHomeDirectory())/Library/Application Support/Claude"
            let configPath = "\(configDir)/claude_desktop_config.json"
            try FileManager.default.createDirectory(
                atPath: configDir, withIntermediateDirectories: true,
            )

            var config: [String: Any] = [:]
            if let data = FileManager.default.contents(atPath: configPath),
               let existing = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                config = existing
            }
            var mcpServers = config["mcpServers"] as? [String: Any] ?? [:]
            mcpServers["gnucash-myproject"] = [
                "command": resolvedBinary,
                "args": ["--stdio"]
            ]
            config["mcpServers"] = mcpServers
            let configData = try JSONSerialization.data(
                withJSONObject: config, options: [.prettyPrinted, .sortedKeys],
            )
            try configData.write(to: URL(fileURLWithPath: configPath))
            print("Wrote: \(configPath)")

            // LaunchAgent plist
            let agentDir = "\(NSHomeDirectory())/Library/LaunchAgents"
            let agentPath = "\(agentDir)/com.gnucash-mcp.myproject.plist"
            try FileManager.default.createDirectory(
                atPath: agentDir, withIntermediateDirectories: true,
            )
            let plist: [String: Any] = [
                "Label": "com.gnucash-mcp.myproject",
                "ProgramArguments": [resolvedBinary, "start"],
                "RunAtLoad": false,
                "StandardOutPath": "/tmp/gnucash-mcp.log",
                "StandardErrorPath": "/tmp/gnucash-mcp.err"
            ]
            let plistData = try PropertyListSerialization.data(
                fromPropertyList: plist, format: .xml, options: 0,
            )
            try plistData.write(to: URL(fileURLWithPath: agentPath))
            print("Wrote: \(agentPath)")
            print("Restart Claude Desktop to pick up the new server.")
        }
    }
}

// MARK: - snapshot

extension GnuCashMCP {
    struct Snapshot: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            abstract: "Create a manual cp -c backup of the live book",
        )

        mutating func run() async throws {
            let sparsebundle = SparsebundleManager()
            guard sparsebundle.isMounted else {
                fputs("error: sparsebundle not mounted at \(sparsebundle.mountPoint)\n", stderr)
                Darwin.exit(1)
            }
            let backup = try BackupManager.createBackup(bookURL: sparsebundle.bookURL)
            print("Backup created: \(backup.path)")
            try BackupManager.pruneBackups(bookURL: sparsebundle.bookURL, keepCount: 10)
        }
    }
}

// MARK: - helpers

private func shellOutput(_ args: String...) -> String {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
    process.arguments = args
    let pipe = Pipe()
    process.standardOutput = pipe
    process.standardError = FileHandle.nullDevice
    try? process.run()
    process.waitUntilExit()
    return String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
}
