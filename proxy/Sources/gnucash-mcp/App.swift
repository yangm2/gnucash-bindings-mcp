import ArgumentParser
import Foundation

@main
struct GnuCashMCP: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "gnucash-mcp",
        abstract: "GnuCash MCP proxy — stdio transport for Claude Desktop",
        version: "\(buildCommit) (\(buildDate))",
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
            fputs("gnucash-mcp \(buildCommit) (\(buildDate)): start\n", stderr)

            let lock: SingletonLock
            do {
                lock = try SingletonLock.acquire()
            } catch SingletonLockError.alreadyRunning {
                fputs("error: gnucash-mcp is already running\n", stderr)
                Darwin.exit(1)
            } catch {
                fputs("error: could not acquire lock: \(error)\n", stderr)
                Darwin.exit(1)
            }
            _ = lock // held for process lifetime

            fputs("gnucash-mcp: checking container system\n", stderr)
            do {
                try ContainerSystem.ensureRunning()
            } catch {
                fputs("error: could not start container system: \(error)\n", stderr)
                Darwin.exit(1)
            }

            fputs("gnucash-mcp: checking image\n", stderr)
            let containerBackend = LiveManagedContainerBackend()
            do {
                guard try await containerBackend.imageExists("gnucash-mcp:latest") else {
                    fputs(
                        "error: container image 'gnucash-mcp:latest' not found\n"
                            + "       Build it first: mise build\n",
                        stderr,
                    )
                    Darwin.exit(1)
                }
            } catch {
                fputs("error: could not check container image: \(error)\n", stderr)
                Darwin.exit(1)
            }

            fputs("gnucash-mcp: attaching sparsebundle\n", stderr)
            let sparsebundle = SparsebundleManager()
            do {
                try sparsebundle.attachIfNeeded()
            } catch {
                fputs("error: could not attach sparsebundle: \(error)\n", stderr)
                Darwin.exit(1)
            }
            let pool = ContainerPool { try await GnuCashContainerClient(backend: containerBackend) }
            setupSignalHandlers(pool: pool, sparsebundle: sparsebundle)

            fputs("gnucash-mcp: entering stdio transport\n", stderr)
            let transport = MCPStdioTransport(pool: pool, sparsebundle: sparsebundle)
            await transport.run()
            fputs("gnucash-mcp: transport exited\n", stderr)
        }

        private func setupSignalHandlers(pool: ContainerPool, sparsebundle: SparsebundleManager) {
            // Block default signal handling so DispatchSource takes over.
            signal(SIGTERM, SIG_IGN)
            signal(SIGINT, SIG_IGN)
            let termSource = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
            termSource.setEventHandler {
                Task {
                    fputs("gnucash-mcp: received SIGTERM — draining pool\n", stderr)
                    await pool.drain()
                    fputs("gnucash-mcp: detaching sparsebundle\n", stderr)
                    try? sparsebundle.detach()
                    Darwin.exit(0)
                }
            }
            termSource.resume()
            let intSource = DispatchSource.makeSignalSource(signal: SIGINT, queue: .main)
            intSource.setEventHandler {
                Task {
                    fputs("gnucash-mcp: received SIGINT — draining pool\n", stderr)
                    await pool.drain()
                    fputs("gnucash-mcp: detaching sparsebundle\n", stderr)
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
            guard let pid = SingletonLock.readPID() else {
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
            let configDir = URL.applicationSupportDirectory.appending(component: "Claude")
            let configPath = configDir.appending(component: "claude_desktop_config.json")
            try FileManager.default.createDirectory(at: configDir, withIntermediateDirectories: true)

            var config: [String: Any] = [:]
            if let data = try? Data(contentsOf: configPath),
               let existing = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            {
                config = existing
            }
            var mcpServers = config["mcpServers"] as? [String: Any] ?? [:]
            mcpServers["gnucash-myproject"] = [
                "command": resolvedBinary,
                "args": ["start"],
            ]
            config["mcpServers"] = mcpServers
            let configData = try JSONSerialization.data(
                withJSONObject: config, options: [.prettyPrinted, .sortedKeys],
            )
            try configData.write(to: configPath)
            print("Wrote: \(configPath.path)")

            // LaunchAgent plist
            let agentDir = URL.libraryDirectory.appending(component: "LaunchAgents")
            let agentPath = agentDir.appending(component: "com.gnucash-mcp.myproject.plist")
            try FileManager.default.createDirectory(at: agentDir, withIntermediateDirectories: true)
            let logDir = URL.libraryDirectory.appending(components: "Logs", "gnucash-mcp")
            try FileManager.default.createDirectory(at: logDir, withIntermediateDirectories: true)
            let plist: [String: Any] = [
                "Label": "com.gnucash-mcp.myproject",
                "ProgramArguments": [resolvedBinary, "start"],
                "RunAtLoad": false,
                "StandardOutPath": logDir.appending(component: "gnucash-mcp.log").path,
                "StandardErrorPath": logDir.appending(component: "gnucash-mcp.err").path,
            ]
            let plistData = try PropertyListSerialization.data(
                fromPropertyList: plist, format: .xml, options: 0,
            )
            try plistData.write(to: agentPath)
            print("Wrote: \(agentPath.path)")
            print("Restart Claude Desktop to pick up the new server.")
        }
    }
}

// MARK: - snapshot

extension GnuCashMCP {
    struct Snapshot: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            abstract: "Create a manual APFS clone-copy backup of the live book",
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
