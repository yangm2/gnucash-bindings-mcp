import Foundation

// MARK: - JSONValue

indirect enum JSONValue {
    case null
    case bool(Bool)
    case int(Int)
    case double(Double)
    case string(String)
    case array([JSONValue])
    case object([String: JSONValue])
}

extension JSONValue: Codable {
    init(from decoder: any Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null; return }
        if let v = try? c.decode(Bool.self) { self = .bool(v); return }
        if let v = try? c.decode(Int.self) { self = .int(v); return }
        if let v = try? c.decode(Double.self) { self = .double(v); return }
        if let v = try? c.decode(String.self) { self = .string(v); return }
        if let v = try? c.decode([JSONValue].self) { self = .array(v); return }
        if let v = try? c.decode([String: JSONValue].self) { self = .object(v); return }
        throw DecodingError.dataCorrupted(
            .init(codingPath: decoder.codingPath, debugDescription: "Unknown JSON type"),
        )
    }

    func encode(to encoder: any Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .null: try c.encodeNil()
        case let .bool(v): try c.encode(v)
        case let .int(v): try c.encode(v)
        case let .double(v): try c.encode(v)
        case let .string(v): try c.encode(v)
        case let .array(v): try c.encode(v)
        case let .object(v): try c.encode(v)
        }
    }
}

extension JSONValue: Equatable {}

extension JSONValue {
    var stringValue: String? {
        if case let .string(s) = self { return s }
        return nil
    }

    var intValue: Int? {
        if case let .int(i) = self { return i }
        return nil
    }

    var arrayValue: [JSONValue]? {
        if case let .array(a) = self { return a }
        return nil
    }

    var objectValue: [String: JSONValue]? {
        if case let .object(d) = self { return d }
        return nil
    }
}

// MARK: - JSON-RPC 2.0

struct JSONRPCRequest: Codable {
    let jsonrpc: String
    let method: String
    let params: JSONValue?
    let id: JSONValue?

    var isNotification: Bool {
        id == nil
    }
}

struct JSONRPCResponse: Codable {
    let jsonrpc: String
    let result: JSONValue?
    let error: JSONRPCError?
    let id: JSONValue?

    static func success(id: JSONValue?, result: JSONValue) -> Self {
        Self(jsonrpc: "2.0", result: result, error: nil, id: id)
    }

    static func failure(id: JSONValue?, code: Int, message: String) -> Self {
        Self(jsonrpc: "2.0", result: nil, error: .init(code: code, message: message), id: id)
    }
}

struct JSONRPCError: Codable {
    let code: Int
    let message: String
}
