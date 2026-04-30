import Foundation

struct MCPResource: Encodable {
    let uri: String
    let name: String
    let description: String
    let mimeType: String
}

enum StaticResources {
    static let all: [MCPResource] = [
        MCPResource(
            uri: "gnucash://session-context",
            name: "Session Context",
            description: "How to use this MCP server: tool tiers, workflow, and conventions",
            mimeType: "text/markdown",
        ),
        MCPResource(
            uri: "gnucash://book-setup-guide",
            name: "Book Setup Guide",
            description: "Account creation conventions and chart of accounts rules (MC-6)",
            mimeType: "text/markdown",
        ),
        MCPResource(
            uri: "gnucash://vendor-guide",
            name: "Vendor Guide",
            description: "How to add and manage trade and professional vendors",
            mimeType: "text/markdown",
        ),
        MCPResource(
            uri: "gnucash://expected-chart",
            name: "Expected Chart of Accounts",
            description: "The MC-6 chart structure this book should match",
            mimeType: "text/markdown",
        ),
    ]

    /// Returns (mimeType, text) for known static URIs, nil for dynamic ones.
    static func content(for uri: String) -> (String, String)? {
        switch uri {
        case "gnucash://session-context":
            markdown("session-context").map { ("text/markdown", $0) }
        case "gnucash://book-setup-guide":
            markdown("book-setup-guide").map { ("text/markdown", $0) }
        case "gnucash://vendor-guide":
            markdown("vendor-guide").map { ("text/markdown", $0) }
        case "gnucash://expected-chart":
            markdown("expected-chart").map { ("text/markdown", $0) }
        default:
            nil
        }
    }

    private static func markdown(_ name: String) -> String? {
        guard let url = Bundle.module.url(forResource: name, withExtension: "md"),
              let text = try? String(contentsOf: url, encoding: .utf8)
        else { return nil }
        return text
    }
}
