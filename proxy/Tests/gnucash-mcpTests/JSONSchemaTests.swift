import Foundation
@testable import gnucash_mcp
import Testing

// Helper: encode a JSONSchema to a JSON dict so tests can inspect keys.
private func encodeSchema(_ schema: JSONSchema) throws -> [String: Any] {
    let data = try JSONEncoder().encode(schema)
    return try JSONSerialization.jsonObject(with: data) as! [String: Any]
}

@Suite("JSONSchema — encoding")
struct JSONSchemaTests {
    // ── Scalar types (property-style: every type keyword emitted correctly) ────

    @Test(
        arguments: [
            (JSONSchema.string(), "string"),
            (.bool(), "boolean"),
            (.number(), "number"),
            (.integer(), "integer"),
        ],
    )
    func `type field for every scalar case`(schema: JSONSchema, expected: String) throws {
        let obj = try encodeSchema(schema)
        #expect(obj["type"] as? String == expected)
    }

    @Test
    func `string with description and default`() throws {
        let obj = try encodeSchema(.string(description: "A label", default: "none"))
        #expect(obj["type"] as? String == "string")
        #expect(obj["description"] as? String == "A label")
        #expect(obj["default"] as? String == "none")
    }

    @Test
    func `string without default omits the default key`() throws {
        let obj = try encodeSchema(.string(description: "desc"))
        #expect(obj["default"] == nil)
    }

    @Test
    func `bool with description`() throws {
        let obj = try encodeSchema(.bool(description: "A flag"))
        #expect(obj["type"] as? String == "boolean")
        #expect(obj["description"] as? String == "A flag")
    }

    @Test
    func `number with description`() throws {
        let obj = try encodeSchema(.number(description: "An amount"))
        #expect(obj["type"] as? String == "number")
        #expect(obj["description"] as? String == "An amount")
    }

    @Test
    func `integer with description`() throws {
        let obj = try encodeSchema(.integer(description: "A count"))
        #expect(obj["type"] as? String == "integer")
        #expect(obj["description"] as? String == "A count")
    }

    // ── enum ──────────────────────────────────────────────────────────────────

    @Test
    func `enum emits values array, no type key`() throws {
        let obj = try encodeSchema(.enum(["a", "b", "c"], description: "pick one"))
        #expect(obj["type"] == nil)
        #expect((obj["enum"] as? [String]) == ["a", "b", "c"])
        #expect(obj["description"] as? String == "pick one")
    }

    // ── object ────────────────────────────────────────────────────────────────

    @Test
    func `object with required fields`() throws {
        let obj = try encodeSchema(.object(["name": .string(), "age": .integer()], required: ["name"]))
        #expect(obj["type"] as? String == "object")
        #expect((obj["additionalProperties"] as? Bool) == false)
        let required = obj["required"] as? [String]
        #expect(required == ["name"])
        let props = obj["properties"] as? [String: Any]
        #expect(props?["name"] != nil)
        #expect(props?["age"] != nil)
    }

    @Test
    func `object without required omits required key`() throws {
        let obj = try encodeSchema(.object(["x": .bool()]))
        #expect(obj["required"] == nil)
    }

    // ── array ─────────────────────────────────────────────────────────────────

    @Test
    func `array with description`() throws {
        let obj = try encodeSchema(.array(items: .string(), description: "list of names"))
        #expect(obj["type"] as? String == "array")
        #expect(obj["description"] as? String == "list of names")
        let items = obj["items"] as? [String: Any]
        #expect(items?["type"] as? String == "string")
    }

    @Test
    func `array without description omits description key`() throws {
        let obj = try encodeSchema(.array(items: .integer()))
        #expect(obj["description"] == nil)
    }

    // ── empty ─────────────────────────────────────────────────────────────────

    @Test
    func `empty emits object with empty properties`() throws {
        let obj = try encodeSchema(.empty)
        #expect(obj["type"] as? String == "object")
        let props = obj["properties"] as? [String: Any]
        #expect(props?.isEmpty == true)
    }

    // ── nesting ───────────────────────────────────────────────────────────────

    @Test
    func `nested object-in-array roundtrips type hierarchy`() throws {
        let schema = JSONSchema.array(items: .object(["id": .integer(), "tag": .string()], required: ["id"]))
        let obj = try encodeSchema(schema)
        #expect(obj["type"] as? String == "array")
        let items = obj["items"] as? [String: Any]
        #expect(items?["type"] as? String == "object")
        let props = items?["properties"] as? [String: Any]
        let idProp = props?["id"] as? [String: Any]
        #expect(idProp?["type"] as? String == "integer")
    }
}
