import Foundation
@testable import gnucash_mcp
import SwiftCheck
import Testing
import XCTest

// MARK: - Arbitrary JSONValue for property testing

// Depth-limited generator to avoid infinite recursion on recursive cases.
private func jsonValueGen(depth: Int = 3) -> Gen<JSONValue> {
    let leaves: Gen<JSONValue> = Gen.one(of: [
        Gen.pure(.null),
        Bool.arbitrary.map { .bool($0) },
        Int.arbitrary.map { .int($0) },
        // Avoid -0.0: JSON has no negative-zero representation; it round-trips as 0.0.
        Double.arbitrary.suchThat { $0.isFinite && !($0 == 0 && $0.sign == .minus) }.map { .double($0) },
        String.arbitrary.map { .string($0) },
    ])

    guard depth > 0 else { return leaves }

    let recursive: Gen<JSONValue> = Gen.one(of: [
        // Array of up to 4 elements
        jsonValueGen(depth: depth - 1).proliferate(withSize: 4).map { JSONValue.array($0) },
        // Object with up to 4 string key-value pairs
        Gen.zip(String.arbitrary, jsonValueGen(depth: depth - 1))
            .proliferate(withSize: 4)
            .map { pairs in JSONValue.object(Dictionary(pairs, uniquingKeysWith: { a, _ in a })) },
    ])

    return Gen.one(of: [leaves, recursive])
}

extension JSONValue: Arbitrary {
    public static var arbitrary: Gen<JSONValue> { jsonValueGen() }
}

// MARK: - JSONValue roundtrip property

// Property: encode(v) |> decode == v  for any JSONValue v.
//
// Known limitation baked into the generator: NaN and ±Inf are excluded
// (JSON has no representation for them); negative zero is excluded because
// JSON serialises it as 0, which the decoder reads back as .int(0) ≠ .double(-0.0).
class JSONValueRoundtripProperty: XCTestCase {
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    func testRoundtripProperty() {
        property("encode → decode is identity for any JSONValue") <- forAll { (value: JSONValue) in
            guard let data = try? self.encoder.encode(value),
                  let decoded = try? self.decoder.decode(JSONValue.self, from: data)
            else { return false }
            return decoded == value
        }
    }
}

// MARK: - JSONValue accessors (Swift Testing parameterized)

@Suite("JSONValue — accessors")
struct JSONValueAccessorTests {
    @Test("stringValue returns string for .string, nil otherwise",
          arguments: [
              (JSONValue.string("hello"), Optional("hello")),
              (.int(1), nil),
              (.bool(true), nil),
              (.null, nil),
              (.array([]), nil),
              (.object([:]), nil),
          ])
    func stringValue(value: JSONValue, expected: String?) {
        #expect(value.stringValue == expected)
    }

    @Test("objectValue returns dict for .object, nil otherwise",
          arguments: [
              (JSONValue.object(["k": .int(1)]), true),
              (.string("x"), false),
              (.null, false),
          ])
    func objectValue(value: JSONValue, expectNonNil: Bool) {
        #expect((value.objectValue != nil) == expectNonNil)
    }
}

// MARK: - JSONRPCRequest

@Suite("JSONRPCRequest")
struct JSONRPCRequestTests {
    private let decoder = JSONDecoder()

    @Test("isNotification is true when id absent or explicit null",
          arguments: [
              // No id key at all
              #"{"jsonrpc":"2.0","method":"notifications/initialized"}"#,
              // Explicit null — decodeIfPresent returns nil, treated as notification
              #"{"jsonrpc":"2.0","method":"tools/list","id":null}"#,
          ])
    func isNotificationTrue(json: String) throws {
        let req = try decoder.decode(JSONRPCRequest.self, from: Data(json.utf8))
        #expect(req.isNotification)
    }

    @Test("isNotification is false when id is a non-null value",
          arguments: [
              #"{"jsonrpc":"2.0","method":"tools/list","id":1}"#,
              #"{"jsonrpc":"2.0","method":"tools/list","id":"abc"}"#,
              #"{"jsonrpc":"2.0","method":"tools/list","id":0}"#,
          ])
    func isNotificationFalse(json: String) throws {
        let req = try decoder.decode(JSONRPCRequest.self, from: Data(json.utf8))
        #expect(!req.isNotification)
    }

    @Test("roundtrip preserves all fields")
    func roundtrip() throws {
        let json = #"{"jsonrpc":"2.0","method":"tools/call","id":42,"params":{"name":"list_accounts","arguments":{}}}"#
        let req = try decoder.decode(JSONRPCRequest.self, from: Data(json.utf8))
        #expect(req.jsonrpc == "2.0")
        #expect(req.method == "tools/call")
        #expect(req.id == .int(42))
        #expect(req.params?.objectValue?["name"] == .string("list_accounts"))
    }
}

// MARK: - JSONRPCResponse

@Suite("JSONRPCResponse")
struct JSONRPCResponseTests {
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    @Test("success encodes result, no error field")
    func successEncoding() throws {
        let resp = JSONRPCResponse.success(id: .int(1), result: .string("ok"))
        let data = try encoder.encode(resp)
        let decoded = try decoder.decode(JSONRPCResponse.self, from: data)
        #expect(decoded.result == .string("ok"))
        #expect(decoded.error == nil)
        #expect(decoded.id == .int(1))
    }

    @Test("failure encodes error, no result field")
    func failureEncoding() throws {
        let resp = JSONRPCResponse.failure(id: .int(2), code: -32601, message: "Method not found")
        let data = try encoder.encode(resp)
        let decoded = try decoder.decode(JSONRPCResponse.self, from: data)
        #expect(decoded.result == nil)
        #expect(decoded.error?.code == -32601)
        #expect(decoded.error?.message == "Method not found")
        #expect(decoded.id == .int(2))
    }

    @Test("failure with nil id (parse error case)")
    func failureNilId() throws {
        let resp = JSONRPCResponse.failure(id: nil, code: -32700, message: "Parse error")
        let data = try encoder.encode(resp)
        let decoded = try decoder.decode(JSONRPCResponse.self, from: data)
        #expect(decoded.id == nil)
        #expect(decoded.error?.code == -32700)
    }

    @Test("success/failure roundtrip preserves jsonrpc version field",
          arguments: [
              JSONRPCResponse.success(id: .int(1), result: .null),
              JSONRPCResponse.failure(id: .int(1), code: -1, message: "err"),
          ])
    func jsonrpcField(resp: JSONRPCResponse) throws {
        let decoded = try decoder.decode(
            JSONRPCResponse.self, from: try encoder.encode(resp))
        #expect(decoded.jsonrpc == "2.0")
    }
}
