import Foundation

/// Builder enum for JSON Schema — used to define tool inputSchema in ToolCatalog.
indirect enum JSONSchema: Sendable {
    case string(description: String? = nil, default: String? = nil)
    case bool(description: String? = nil)
    case number(description: String? = nil)
    case integer(description: String? = nil)
    case `enum`([String], description: String? = nil)
    case object([String: JSONSchema], required: [String] = [])
    case array(items: JSONSchema, description: String? = nil)
    case empty // no-parameter tools: {"type": "object", "properties": {}}
}

extension JSONSchema: Encodable {
    private enum CodingKeys: String, CodingKey {
        case type, description, `default`, `enum`, properties, required, items,
             additionalProperties
    }

    func encode(to encoder: any Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case let .string(desc, def):
            try c.encode("string", forKey: .type)
            if let d = desc { try c.encode(d, forKey: .description) }
            if let d = def { try c.encode(d, forKey: .default) }

        case let .bool(desc):
            try c.encode("boolean", forKey: .type)
            if let d = desc { try c.encode(d, forKey: .description) }

        case let .number(desc):
            try c.encode("number", forKey: .type)
            if let d = desc { try c.encode(d, forKey: .description) }

        case let .integer(desc):
            try c.encode("integer", forKey: .type)
            if let d = desc { try c.encode(d, forKey: .description) }

        case let .enum(values, desc):
            try c.encode(values, forKey: .enum)
            if let d = desc { try c.encode(d, forKey: .description) }

        case let .object(props, required):
            try c.encode("object", forKey: .type)
            let encoded = props.mapValues(Wrapped.init)
            try c.encode(encoded, forKey: .properties)
            if !required.isEmpty { try c.encode(required, forKey: .required) }
            try c.encode(false, forKey: .additionalProperties)

        case let .array(items, desc):
            try c.encode("array", forKey: .type)
            try c.encode(Wrapped(items), forKey: .items)
            if let d = desc { try c.encode(d, forKey: .description) }

        case .empty:
            try c.encode("object", forKey: .type)
            try c.encode([String: String](), forKey: .properties)
        }
    }
}

private struct Wrapped: Encodable {
    let schema: JSONSchema
    init(_ schema: JSONSchema) {
        self.schema = schema
    }

    func encode(to encoder: any Encoder) throws {
        try schema.encode(to: encoder)
    }
}
