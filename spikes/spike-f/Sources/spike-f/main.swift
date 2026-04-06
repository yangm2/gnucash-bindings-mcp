/// spike-f — minimal Swift MCP proxy
///
/// Validates:
///   F1 — Claude Desktop can connect via stdio (streamable-http rejected by Desktop config)
///   F2 — Swift can dispatch to an Apple Container via `container run` and
///         capture stdout, round-trip within 1 second
///
/// Build:  swift build -c release
///
/// Stdio mode (Claude Desktop):
///   .build/release/spike-f --stdio --image spike-f-echo:latest
///   Register in claude_desktop_config.json as command/args entry.
///
/// HTTP mode (curl / web testing):
///   .build/release/spike-f --port 8980 --image spike-f-echo:latest
///   curl -s -X POST http://localhost:8980/mcp \
///     -H 'Content-Type: application/json' \
///     -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}'

import ArgumentParser
import Foundation
import NIO
import NIOHTTP1

// MARK: - Entry point

@main
struct SpikeF: AsyncParsableCommand {
    @Option(name: .long, help: "Port to listen on (HTTP mode)")
    var port: Int = 8980

    @Option(name: .long, help: "Container image for dispatch (F2)")
    var image: String = "spike-f-echo:latest"

    @Flag(name: .long, help: "Stdio mode: read JSON-RPC from stdin, write to stdout (for Claude Desktop)")
    var stdio: Bool = false

    func run() async throws {
        let handler = MCPHandler(echoImage: image)
        if stdio {
            try await StdioServer(handler: handler).run()
        } else {
            try await MCPServer(port: port, echoImage: image).run()
        }
    }
}

// MARK: - Container dispatch (F2)

/// Runs `container run --rm <image> <command...>` and returns trimmed stdout.
/// Throws if the process exits non-zero.
func containerDispatch(image: String, command: [String]) throws -> String {
    let proc = Process()
    proc.executableURL = URL(fileURLWithPath: "/usr/bin/env")
    proc.arguments = ["container", "run", "--rm", image] + command
    let outPipe = Pipe()
    let errPipe = Pipe()
    proc.standardOutput = outPipe
    proc.standardError = errPipe
    try proc.run()
    proc.waitUntilExit()
    let out = String(data: outPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
        .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    guard proc.terminationStatus == 0 else {
        let err = String(data: errPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        throw DispatchError.nonZeroExit(Int(proc.terminationStatus), err)
    }
    return out
}

enum DispatchError: Error {
    case nonZeroExit(Int, String)
}

// MARK: - MCP JSON-RPC helpers

typealias JSON = [String: Any]

func parseRequest(_ body: Data) -> JSON? {
    (try? JSONSerialization.jsonObject(with: body)) as? JSON
}

func jsonData(_ value: Any) -> Data {
    (try? JSONSerialization.data(withJSONObject: value)) ?? Data()
}

/// Build a JSON-RPC success response preserving the request id.
func rpcResult(id: Any?, result: Any) -> JSON {
    var r: JSON = ["jsonrpc": "2.0", "result": result]
    if let id { r["id"] = id }
    return r
}

/// Build a JSON-RPC error response.
func rpcError(id: Any?, code: Int, message: String) -> JSON {
    var r: JSON = ["jsonrpc": "2.0", "error": ["code": code, "message": message]]
    if let id { r["id"] = id }
    return r
}

// MARK: - MCP request handler

struct MCPHandler {
    let echoImage: String

    /// Handle one JSON-RPC request body, return (responseJSON, httpStatus).
    func handle(body: Data) -> (JSON?, Int) {
        guard let req = parseRequest(body),
              let method = req["method"] as? String else {
            return (rpcError(id: nil, code: -32600, message: "Invalid request"), 400)
        }

        let id = req["id"]

        switch method {

        case "initialize":
            let result: JSON = [
                "protocolVersion": "2024-11-05",
                "capabilities": ["tools": [:]],
                "serverInfo": ["name": "spike-f", "version": "0.1.0"],
            ]
            return (rpcResult(id: id, result: result), 200)

        case "notifications/initialized":
            // Notification — no id, no response body.
            return (nil, 204)

        case "tools/list":
            let tools: [[String: Any]] = [[
                "name": "ping",
                "description": "Dispatch to container and return status. Validates F1 + F2.",
                "inputSchema": ["type": "object", "properties": [:] as JSON],
            ]]
            return (rpcResult(id: id, result: ["tools": tools]), 200)

        case "tools/call":
            guard let params = req["params"] as? JSON,
                  let name = params["name"] as? String else {
                return (rpcError(id: id, code: -32602, message: "Missing params.name"), 400)
            }
            guard name == "ping" else {
                return (rpcError(id: id, code: -32601, message: "Unknown tool: \(name)"), 404)
            }

            // F2: dispatch to container, measure round-trip
            let start = Date()
            let rawOutput: String
            do {
                rawOutput = try containerDispatch(
                    image: echoImage,
                    command: ["python3", "-c",
                              "import json,sys; print(json.dumps({'status':'ok','transport':'swift-proxy'}))"]
                )
            } catch {
                return (rpcError(id: id, code: -32000, message: "Container dispatch failed: \(error)"), 500)
            }
            let elapsedMs = Int(Date().timeIntervalSince(start) * 1000)
            let withinTarget = elapsedMs <= 1000

            // Merge timing into the response so Claude can report it
            var payload = (try? JSONSerialization.jsonObject(with: Data(rawOutput.utf8))) as? JSON ?? [:]
            payload["dispatch_ms"] = elapsedMs
            payload["within_1s_target"] = withinTarget

            let stderr = FileHandle.standardError
            let tag = withinTarget ? "OK" : "SLOW"
            stderr.write(Data("  dispatch round-trip: \(elapsedMs)ms [\(tag)]\n".utf8))

            let text = String(data: jsonData(payload), encoding: .utf8) ?? rawOutput
            let content: [[String: Any]] = [["type": "text", "text": text]]
            return (rpcResult(id: id, result: ["content": content]), 200)

        default:
            return (rpcError(id: id, code: -32601, message: "Method not found: \(method)"), 404)
        }
    }
}

// MARK: - Stdio server (Claude Desktop)

/// Reads newline-delimited JSON-RPC from stdin, writes responses to stdout.
/// Notifications (no id) receive no response. Stderr used for diagnostics.
struct StdioServer {
    let handler: MCPHandler

    func run() async throws {
        let stderr = FileHandle.standardError
        func log(_ msg: String) {
            stderr.write(Data((msg + "\n").utf8))
        }

        log("spike-f stdio mode started (image: \(handler.echoImage))")

        while let line = readLine(strippingNewline: true) {
            guard !line.isEmpty else { continue }
            log("← \(line)")
            guard let data = line.data(using: .utf8) else { continue }

            let (responseJSON, _) = handler.handle(body: data)
            guard let responseJSON else { continue }  // notification — no response

            let responseData = jsonData(responseJSON)
            if let text = String(data: responseData, encoding: .utf8) {
                log("→ \(text)")
                print(text)  // stdout — Claude Desktop reads this
                fflush(stdout)
            }
        }
    }
}

// MARK: - NIO HTTP server

final class HTTPHandler: ChannelInboundHandler {
    typealias InboundIn = HTTPServerRequestPart
    typealias OutboundOut = HTTPServerResponsePart

    private let mcp: MCPHandler
    private var buffer = Data()
    private var requestHead: HTTPRequestHead?

    init(mcp: MCPHandler) { self.mcp = mcp }

    func channelRead(context: ChannelHandlerContext, data: NIOAny) {
        let part = unwrapInboundIn(data)
        switch part {
        case .head(let head):
            requestHead = head
            buffer = Data()

        case .body(var buf):
            if let bytes = buf.readBytes(length: buf.readableBytes) {
                buffer.append(contentsOf: bytes)
            }

        case .end:
            guard let head = requestHead else { return }
            handleRequest(context: context, head: head, body: buffer)
            requestHead = nil
            buffer = Data()
        }
    }

    private func handleRequest(context: ChannelHandlerContext, head: HTTPRequestHead, body: Data) {
        // Only handle POST /mcp
        guard head.method == .POST, head.uri == "/mcp" else {
            respond(context: context, status: .notFound, body: Data())
            return
        }

        print("→ POST /mcp (\(body.count)B)")
        if let text = String(data: body, encoding: .utf8) { print("  \(text)") }

        let (responseJSON, httpStatus) = mcp.handle(body: body)

        if let responseJSON {
            let responseData = jsonData(responseJSON)
            if let text = String(data: responseData, encoding: .utf8) { print("← \(text)") }
            respond(context: context, status: HTTPResponseStatus(statusCode: httpStatus),
                    body: responseData, contentType: "application/json")
        } else {
            respond(context: context, status: HTTPResponseStatus(statusCode: httpStatus), body: Data())
        }
    }

    private func respond(context: ChannelHandlerContext,
                         status: HTTPResponseStatus,
                         body: Data,
                         contentType: String = "application/json") {
        var headers = HTTPHeaders()
        headers.add(name: "Content-Type", value: contentType)
        headers.add(name: "Content-Length", value: "\(body.count)")

        let head = HTTPResponseHead(version: .http1_1, status: status, headers: headers)
        context.write(wrapOutboundOut(.head(head)), promise: nil)

        if !body.isEmpty {
            var buf = context.channel.allocator.buffer(capacity: body.count)
            buf.writeBytes(body)
            context.write(wrapOutboundOut(.body(.byteBuffer(buf))), promise: nil)
        }

        context.writeAndFlush(wrapOutboundOut(.end(nil)), promise: nil)
    }

    func errorCaught(context: ChannelHandlerContext, error: Error) {
        print("Channel error: \(error)")
        context.close(promise: nil)
    }
}

// MARK: - Server bootstrap

struct MCPServer {
    let port: Int
    let echoImage: String

    func run() async throws {
        let mcp = MCPHandler(echoImage: echoImage)
        let group = MultiThreadedEventLoopGroup(numberOfThreads: 1)
        defer { try? group.syncShutdownGracefully() }

        let bootstrap = ServerBootstrap(group: group)
            .serverChannelOption(ChannelOptions.backlog, value: 256)
            .serverChannelOption(ChannelOptions.socketOption(.so_reuseaddr), value: 1)
            .childChannelInitializer { channel in
                channel.pipeline.configureHTTPServerPipeline().flatMap {
                    channel.pipeline.addHandler(HTTPHandler(mcp: mcp))
                }
            }

        let channel = try await bootstrap.bind(host: "127.0.0.1", port: port).get()
        print("spike-f listening on http://127.0.0.1:\(port)/mcp")
        print("Container image for dispatch: \(echoImage)")
        print("")
        print("Add to claude_desktop_config.json:")
        print("""
        {
          "mcpServers": {
            "spike-f": {
              "type": "streamable-http",
              "url": "http://localhost:\(port)/mcp"
            }
          }
        }
        """)
        print("Press Ctrl-C to stop.")
        try await channel.closeFuture.get()
    }
}
