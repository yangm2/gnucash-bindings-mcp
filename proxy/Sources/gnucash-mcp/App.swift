import ArgumentParser
import Foundation

@main
struct GnuCashMCP: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "gnucash-mcp",
        abstract: "GnuCash MCP proxy — stdio transport for Claude Desktop",
        version: "\(buildCommit) (\(buildDate))",
        subcommands: [Start.self, Stop.self, Status.self, Register.self, Unregister.self, Snapshot.self],
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

            let pool = ContainerPool { try await GnuCashContainerClient(backend: containerBackend) }
            let transport = MCPStdioTransport(pool: pool)
            setupSignalHandlers(transport: transport)

            fputs("gnucash-mcp: entering stdio transport\n", stderr)
            await transport.run()
            fputs("gnucash-mcp: transport exited\n", stderr)
        }

        private func setupSignalHandlers(transport: MCPStdioTransport) {
            // Block default signal handling so DispatchSource takes over.
            signal(SIGTERM, SIG_IGN)
            signal(SIGINT, SIG_IGN)
            let handler: @Sendable (String) -> Void = { name in
                Task {
                    fputs("gnucash-mcp: received \(name) — shutting down\n", stderr)
                    await transport.shutdown()
                    Darwin.exit(0)
                }
            }
            let termSource = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
            termSource.setEventHandler { handler("SIGTERM") }
            termSource.resume()
            let intSource = DispatchSource.makeSignalSource(signal: SIGINT, queue: .main)
            intSource.setEventHandler { handler("SIGINT") }
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
            let sparsebundle = SparsebundleManager(bundlePath: SparsebundleManager.defaultBundlePath)
            print(
                "Sparsebundle : \(sparsebundle.isMounted ? "mounted at \(sparsebundle.mountPoint)" : "not mounted")",
            )
        }
    }
}

// MARK: - register

extension GnuCashMCP {
    struct Register: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            abstract: "Register with Claude Desktop: write claude_desktop_config.json entry and LaunchAgent plist",
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

// MARK: - unregister

extension GnuCashMCP {
    struct Unregister: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            abstract: "Unregister from Claude Desktop: remove claude_desktop_config.json entry and LaunchAgent plist",
        )

        mutating func run() async throws {
            let fm = FileManager.default

            // claude_desktop_config.json
            let configPath = URL.applicationSupportDirectory
                .appending(component: "Claude")
                .appending(component: "claude_desktop_config.json")
            if let data = try? Data(contentsOf: configPath),
               var config = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               var mcpServers = config["mcpServers"] as? [String: Any]
            {
                mcpServers.removeValue(forKey: "gnucash-myproject")
                config["mcpServers"] = mcpServers
                let updated = try JSONSerialization.data(
                    withJSONObject: config, options: [.prettyPrinted, .sortedKeys],
                )
                try updated.write(to: configPath)
                print("Removed entry from: \(configPath.path)")
            } else {
                print("No entry found in: \(configPath.path)")
            }

            // LaunchAgent plist
            let agentPath = URL.libraryDirectory
                .appending(component: "LaunchAgents")
                .appending(component: "com.gnucash-mcp.myproject.plist")
            if fm.fileExists(atPath: agentPath.path) {
                try fm.removeItem(at: agentPath)
                print("Removed: \(agentPath.path)")
            } else {
                print("Not found: \(agentPath.path)")
            }

            print("Restart Claude Desktop to apply changes.")
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
            let sparsebundle = SparsebundleManager(bundlePath: SparsebundleManager.defaultBundlePath)
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
