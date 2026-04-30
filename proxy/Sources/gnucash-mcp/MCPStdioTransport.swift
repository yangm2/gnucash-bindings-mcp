import Foundation

/// Reads newline-delimited JSON-RPC from stdin, dispatches each message, writes
/// responses to stdout. Static methods (initialize, tools/list, resources/*) are
/// answered without touching the container. All other methods go to the pool.
///
/// Roots protocol: after the client sends notifications/initialized, this server
/// sends roots/list to discover the sparsebundle path configured in Claude Desktop's
/// Extensions settings. Tool calls that arrive before the sparsebundle is attached
/// wait on a continuation until it is ready.
actor MCPStdioTransport {
    private let pool: ContainerPool
    private var sparsebundle: SparsebundleManager?
    private var backupDone = false

    // Roots protocol state
    private static let rootsRequestId = 1001
    private var rootsRequested = false
    private var sparsebundleWaiters: [CheckedContinuation<SparsebundleManager, Error>] = []

    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.outputFormatting = []
        return e
    }()

    private let decoder = JSONDecoder()

    init(pool: ContainerPool) {
        self.pool = pool
    }

    func run() async {
        do {
            for try await line in FileHandle.standardInput.bytes.lines {
                let trimmed = line.trimmingCharacters(in: .whitespaces)
                guard !trimmed.isEmpty else { continue }
                guard let data = trimmed.data(using: .utf8) else { continue }

                // Incoming messages are either client requests or client responses
                // to our server-initiated roots/list request.
                if let request = try? decoder.decode(JSONRPCRequest.self, from: data) {
                    let response: JSONRPCResponse?
                    do {
                        response = try await dispatch(request)
                    } catch {
                        response = .failure(id: request.id, code: -32603, message: "\(error)")
                    }
                    if let response { write(response) }
                } else if let response = try? decoder.decode(JSONRPCResponse.self, from: data) {
                    await handleClientResponse(response)
                } else {
                    write(.failure(id: nil, code: -32700, message: "Parse error"))
                }
            }
        } catch {
            fputs("gnucash-mcp: stdin read error: \(error)\n", stderr)
        }
        fputs("gnucash-mcp: stdin EOF — draining pool\n", stderr)
        await shutdown()
    }

    /// Called by signal handlers to cleanly drain the pool and detach the sparsebundle.
    func shutdown() async {
        await pool.drain()
        fputs("gnucash-mcp: detaching sparsebundle\n", stderr)
        try? sparsebundle?.detach()
    }

    // MARK: - Dispatch

    private func dispatch(_ request: JSONRPCRequest) async throws -> JSONRPCResponse? {
        if request.method.hasPrefix("notifications/") {
            await handleNotification(request)
            return nil
        }

        switch request.method {
        case "initialize":
            return .success(id: request.id, result: initializeResult())

        case "tools/list":
            return try .success(id: request.id, result: toolsListResult())

        case "resources/list":
            return try .success(id: request.id, result: resourcesListResult())

        case "resources/read":
            let uri = request.params?.objectValue?["uri"]?.stringValue
            if let uri, let (mimeType, text) = StaticResources.content(for: uri) {
                return .success(
                    id: request.id,
                    result: resourceReadResult(uri: uri, mimeType: mimeType, text: text),
                )
            }
            return try await containerDispatch(request)

        default:
            return try await containerDispatch(request)
        }
    }

    private func handleNotification(_ request: JSONRPCRequest) async {
        // roots/list_changed before the first tool call: re-request so the
        // correct path is used when the first tool arrives.
        if request.method == "notifications/roots/list_changed" {
            if sparsebundle != nil {
                fputs("gnucash-mcp: roots changed — restart Claude Desktop to apply\n", stderr)
            } else {
                rootsRequested = false // allow re-fetch
            }
        }
    }

    // MARK: - Roots protocol

    private func sendRootsListRequest() {
        let req: JSONValue = .object([
            "jsonrpc": .string("2.0"),
            "id": .int(Self.rootsRequestId),
            "method": .string("roots/list"),
            "params": .object([:]),
        ])
        if let data = try? encoder.encode(req), let str = String(data: data, encoding: .utf8) {
            print(str)
            fflush(stdout)
        }
    }

    private func handleClientResponse(_ response: JSONRPCResponse) async {
        guard response.id?.intValue == Self.rootsRequestId else { return }
        let roots = response.result?.objectValue?["roots"]?.arrayValue ?? []
        let path: String
        if let uri = roots.first?.objectValue?["uri"]?.stringValue,
           let url = URL(string: uri), url.isFileURL
        {
            path = url.path
        } else {
            fputs("gnucash-mcp: roots/list returned no file URI — using default path\n", stderr)
            path = SparsebundleManager.defaultBundlePath
        }
        await attachSparsebundle(path: path)
    }

    private func attachSparsebundle(path: String) async {
        let sb = SparsebundleManager(bundlePath: path)
        do {
            try sb.attachIfNeeded()
            sparsebundle = sb
            let waiters = sparsebundleWaiters
            sparsebundleWaiters = []
            for cont in waiters {
                cont.resume(returning: sb)
            }
        } catch {
            fputs("error: could not attach sparsebundle: \(error)\n", stderr)
            let waiters = sparsebundleWaiters
            sparsebundleWaiters = []
            for cont in waiters {
                cont.resume(throwing: error)
            }
            Darwin.exit(1)
        }
    }

    /// Returns the sparsebundle, attaching it if necessary. On the first call,
    /// sends roots/list to the client and suspends until the response arrives.
    private func acquireSparsebundle() async throws -> SparsebundleManager {
        if let sb = sparsebundle { return sb }
        return try await withCheckedThrowingContinuation { cont in
            sparsebundleWaiters.append(cont)
            if !rootsRequested {
                rootsRequested = true
                sendRootsListRequest()
            }
        }
    }

    // MARK: - Container dispatch

    private func containerDispatch(_ request: JSONRPCRequest) async throws -> JSONRPCResponse {
        let sb = try await acquireSparsebundle()

        if !backupDone, isWriteMethod(request.method) {
            if let backup = try? BackupManager.createBackup(bookURL: sb.bookURL) {
                try? BackupManager.pruneBackups(bookURL: sb.bookURL, keepCount: 10)
                _ = backup
            }
            backupDone = true
        }

        let client = try await pool.acquire()
        defer { Task { await pool.release() } }

        let requestData = try encoder.encode(request)
        let responseData = try await client.roundTrip(request: requestData)
        return try decoder.decode(JSONRPCResponse.self, from: responseData)
    }

    private func isWriteMethod(_ method: String) -> Bool {
        method == "tools/call"
    }

    // MARK: - Output

    private func write(_ response: JSONRPCResponse) {
        if let data = try? encoder.encode(response), let str = String(data: data, encoding: .utf8) {
            print(str)
            fflush(stdout)
        }
    }

    // MARK: - Static response builders

    private func initializeResult() -> JSONValue {
        .object([
            "protocolVersion": .string("2024-11-05"),
            "capabilities": .object([
                "tools": .object([:]),
                "resources": .object([:]),
            ]),
            "serverInfo": .object([
                "name": .string("gnucash-mcp"),
                "version": .string("0.1.0"),
            ]),
        ])
    }

    private func toolsListResult() throws -> JSONValue {
        let toolsData = try encoder.encode(ToolCatalog.tools)
        let tools = try decoder.decode(JSONValue.self, from: toolsData)
        return .object(["tools": tools])
    }

    private func resourcesListResult() throws -> JSONValue {
        let resourcesData = try encoder.encode(StaticResources.all)
        let resources = try decoder.decode(JSONValue.self, from: resourcesData)
        return .object(["resources": resources])
    }

    private func resourceReadResult(uri: String, mimeType: String, text: String) -> JSONValue {
        .object([
            "contents": .array([
                .object([
                    "uri": .string(uri),
                    "mimeType": .string(mimeType),
                    "text": .string(text),
                ]),
            ]),
        ])
    }
}
