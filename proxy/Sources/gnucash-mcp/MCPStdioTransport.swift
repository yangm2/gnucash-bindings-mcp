import Foundation

/// Reads newline-delimited JSON-RPC from stdin, dispatches each message, writes
/// responses to stdout. Static methods (initialize, tools/list, resources/*) are
/// answered without touching the container. All other methods go to the pool.
actor MCPStdioTransport {
    private let pool: ContainerPool
    private let sparsebundle: SparsebundleManager
    private var backupDone = false

    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.outputFormatting = []
        return e
    }()

    private let decoder = JSONDecoder()

    init(pool: ContainerPool, sparsebundle: SparsebundleManager) {
        self.pool = pool
        self.sparsebundle = sparsebundle
    }

    func run() async {
        do {
            for try await line in FileHandle.standardInput.bytes.lines {
                let trimmed = line.trimmingCharacters(in: .whitespaces)
                guard !trimmed.isEmpty else { continue }
                guard let data = trimmed.data(using: .utf8) else { continue }

                let response: JSONRPCResponse?
                do {
                    let request = try decoder.decode(JSONRPCRequest.self, from: data)
                    response = try await dispatch(request)
                } catch {
                    response = .failure(id: nil, code: -32700, message: "Parse error: \(error)")
                }

                guard let response else { continue } // notifications produce no response
                if let out = try? encoder.encode(response),
                   let str = String(data: out, encoding: .utf8)
                {
                    print(str)
                    fflush(stdout)
                }
            }
        } catch {
            // stdin read error — fall through to cleanup
        }
        // stdin closed — drain pool and detach
        await pool.drain()
        try? sparsebundle.detach()
    }

    // MARK: - Dispatch

    private func dispatch(_ request: JSONRPCRequest) async throws -> JSONRPCResponse? {
        // Notifications (no id, or method starting with "notifications/") never get a response.
        if request.method.hasPrefix("notifications/") {
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
            if let uri, let text = StaticResources.content(for: uri) {
                return try .success(
                    id: request.id,
                    result: resourceReadResult(uri: uri, text: text),
                )
            }
            // Fall through to container for dynamic resources (e.g. gnucash://vendors)
            return try await containerDispatch(request)

        default:
            return try await containerDispatch(request)
        }
    }

    // MARK: - Container dispatch

    private func containerDispatch(_ request: JSONRPCRequest) async throws -> JSONRPCResponse {
        // Create backup before the first write call in this session.
        if !backupDone, isWriteMethod(request.method) {
            if let backup = try? BackupManager.createBackup(bookURL: sparsebundle.bookURL) {
                try? BackupManager.pruneBackups(bookURL: sparsebundle.bookURL, keepCount: 10)
                _ = backup
            }
            backupDone = true
        }

        let client = try await pool.acquire()
        defer { Task { await pool.release() } }

        let requestData = try encoder.encode(request)
        let responseData = try client.roundTrip(request: requestData)
        return try decoder.decode(JSONRPCResponse.self, from: responseData)
    }

    private func isWriteMethod(_ method: String) -> Bool {
        method == "tools/call"
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

    private func resourceReadResult(uri: String, text: String) throws -> JSONValue {
        .object([
            "contents": .array([
                .object([
                    "uri": .string(uri),
                    "mimeType": .string("text/markdown"),
                    "text": .string(text),
                ]),
            ]),
        ])
    }
}
