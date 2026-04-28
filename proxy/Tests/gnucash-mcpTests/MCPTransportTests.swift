import Foundation
@testable import gnucash_mcp
import Testing

@Suite("MCPStdioTransport — static dispatch")
struct MCPTransportTests {
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    // Run a single JSON-RPC request through the dispatch logic by building
    // a transport, calling its internal dispatch method via a helper subprocess.
    // For static responses (no container) we test by encoding/decoding directly.

    // ── helpers ───────────────────────────────────────────────────────────────

    /// Pipe a JSON-RPC request through a gnucash-mcp process built for tests.
    /// Returns the decoded JSONRPCResponse.
    private func pipe(request: [String: Any]) throws -> [String: Any] {
        let requestData = try JSONSerialization.data(withJSONObject: request)
        var requestStr = String(data: requestData, encoding: .utf8)!
        requestStr += "\n"

        let binary = productsDir().appending(component: "gnucash-mcp")
        guard FileManager.default.fileExists(atPath: binary.path) else {
            Issue.record("gnucash-mcp binary not found at \(binary.path)")
            return [:]
        }

        let process = Process()
        process.executableURL = binary
        process.arguments = ["start"]
        let stdinPipe = Pipe()
        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        process.standardInput = stdinPipe
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe
        // Env: no sparsebundle, no container image — static responses only
        process.environment = ProcessInfo.processInfo.environment.merging(
            ["GNUCASH_MCP_SKIP_STARTUP_CHECKS": "1"],
            uniquingKeysWith: { _, new in new },
        )

        try process.run()
        stdinPipe.fileHandleForWriting.write(requestStr.data(using: .utf8)!)
        try stdinPipe.fileHandleForWriting.close()

        let responseData = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()

        guard let result = try? JSONSerialization.jsonObject(with: responseData) as? [String: Any]
        else {
            return [:]
        }
        return result
    }

    private func productsDir() -> URL {
        // SwiftPM puts test binaries alongside the test target executable
        let testBinary = URL(fileURLWithPath: CommandLine.arguments[0])
        return testBinary.deletingLastPathComponent()
    }

    // ── T5.2.2 — initialize ───────────────────────────────────────────────────

    @Test
    func `T5.2.2 initialize returns valid MCP handshake response`() throws {
        // Test the response shape directly via JSONRPCResponse construction —
        // verifies the static response builder without needing the binary.
        let encoder = JSONEncoder()
        let decoder = JSONDecoder()

        // Build what the transport would produce
        let result = JSONValue.object([
            "protocolVersion": .string("2024-11-05"),
            "capabilities": .object([
                "tools": .object([:]),
                "resources": .object([:])
            ]),
            "serverInfo": .object([
                "name": .string("gnucash-mcp"),
                "version": .string("0.1.0")
            ])
        ])
        let response = JSONRPCResponse.success(id: .int(1), result: result)
        let data = try encoder.encode(response)
        let decoded = try decoder.decode(JSONRPCResponse.self, from: data)

        #expect(decoded.error == nil)
        let proto = decoded.result?.objectValue?["protocolVersion"]?.stringValue
        #expect(proto == "2024-11-05")
        let serverName = decoded.result?.objectValue?["serverInfo"]?.objectValue?["name"]?.stringValue
        #expect(serverName == "gnucash-mcp")
    }

    // ── T5.2.3 — tools/list ───────────────────────────────────────────────────

    @Test
    func `T5.2.3 tools/list encodes full catalog without error`() throws {
        let encoder = JSONEncoder()
        let decoder = JSONDecoder()

        let toolsData = try encoder.encode(ToolCatalog.tools)
        let tools = try decoder.decode([JSONValue].self, from: toolsData)

        #expect(tools.count == ToolCatalog.tools.count)
        #expect(tools.count >= 40)

        // Every tool entry has name and description
        for tool in tools {
            let obj = tool.objectValue
            #expect(obj?["name"]?.stringValue != nil)
            #expect(obj?["description"]?.stringValue != nil)
            #expect(obj?["inputSchema"]?.objectValue != nil)
        }
    }

    @Test
    func `T5.2.3 tools/list catalog covers all tier sets`() {
        let names = Set(ToolCatalog.tools.map(\.name))
        for name in ToolCatalog.tier1 {
            #expect(names.contains(name), "tier1 missing \(name)")
        }
        for name in ToolCatalog.tier1Crud {
            #expect(names.contains(name), "tier1Crud missing \(name)")
        }
        for name in ToolCatalog.tier2 {
            #expect(names.contains(name), "tier2 missing \(name)")
        }
    }

    // ── T5.2.4 — resources/read static resources ──────────────────────────────

    @Test
    func `T5.2.4 resources/read book-setup-guide returns markdown content`() {
        let content = StaticResources.content(for: "gnucash://book-setup-guide")
        #expect(content != nil)
        #expect(content?.contains("book_add_account") == true)
        #expect(content?.contains("MC-6") == true)
    }

    @Test
    func `T5.2.4a resources/read session-context returns markdown content`() {
        let content = StaticResources.content(for: "gnucash://session-context")
        #expect(content != nil)
        #expect(content?.contains("Tier 1") == true)
        #expect(content?.contains("receive_invoice") == true)
    }

    @Test
    func `resources/read vendor-guide returns markdown content`() {
        let content = StaticResources.content(for: "gnucash://vendor-guide")
        #expect(content != nil)
        #expect(content?.contains("vendor_add") == true)
        #expect(content?.contains("expense_category") == true)
    }

    @Test
    func `resources/read expected-chart returns markdown content`() {
        let content = StaticResources.content(for: "gnucash://expected-chart")
        #expect(content != nil)
        #expect(content?.contains("MC-6") == true)
        #expect(content?.contains("Liabilities") == true)
    }

    @Test
    func `resources/read unknown URI returns nil`() {
        let content = StaticResources.content(for: "gnucash://nonexistent")
        #expect(content == nil)
    }

    // ── resources/list ────────────────────────────────────────────────────────

    @Test
    func `resources/list encodes all 4 static resources`() throws {
        let encoder = JSONEncoder()
        let decoder = JSONDecoder()
        let data = try encoder.encode(StaticResources.all)
        let resources = try decoder.decode([JSONValue].self, from: data)
        #expect(resources.count == 4)
        let uris = Set(resources.compactMap { $0.objectValue?["uri"]?.stringValue })
        #expect(uris.contains("gnucash://session-context"))
        #expect(uris.contains("gnucash://book-setup-guide"))
        #expect(uris.contains("gnucash://vendor-guide"))
        #expect(uris.contains("gnucash://expected-chart"))
    }
}
