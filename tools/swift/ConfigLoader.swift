import Foundation

// Example Swift snippet showing TOML decode + validation for gnucash-mcp-budgets
// Note: Requires a TOML decoding library that supports Codable, e.g. 'TOMLDecoder'
// This file is an illustrative snippet; integrate into the proxy target and add
// the dependency in Package.swift.

struct Meta: Codable {
    let title: String?
    let version: String?
    let currency: String?
    let effective_date: String?
}

struct ProfessionalFee: Codable {
    let account: String
    let contract_type: String
    let contract_total: Double?
    let contract_low: Double?
    let contract_high: Double?
    let notes: String?
}

struct ExternalBudget: Codable {
    let account: String
    let amount: Double
    let notes: String?
}

struct RatesMaterial: Codable {
    let overage_pct: Double?
}

struct Rates: Codable {
    let overtime_multiplier: Double?
    let material: RatesMaterial?
}

struct ProxyConfig: Codable {
    let expose_resource: String?
    let validate_on_start: Bool?
    let hot_reload_sighup: Bool?
}

struct BudgetsConfig: Codable {
    let meta: Meta?
    let professional_fees: [ProfessionalFee]?
    let external_budgets: [ExternalBudget]?
    let rates: Rates?
    let proxy: ProxyConfig?
}

enum ConfigError: Error {
    case notFound(String)
    case decodeError(Error)
    case validationFailed(String)
}

// Load TOML from path (or env override) and decode into BudgetsConfig
func loadBudgetsConfig(from path: String?) throws -> BudgetsConfig {
    let fm = FileManager.default
    let configPath: String
    if let explicit = path, fm.fileExists(atPath: explicit) {
        configPath = explicit
    } else if let env = ProcessInfo.processInfo.environment["GNUCASH_MCP_CONFIG"], fm.fileExists(atPath: env) {
        configPath = env
    } else {
        // default: $BOOK_DIR/gnucash-mcp-budgets.toml must be passed down by proxy
        throw ConfigError.notFound("No budgets config found; set GNUCASH_MCP_CONFIG or pass path")
    }

    let data = try Data(contentsOf: URL(fileURLWithPath: configPath))

    // Replace `TOMLDecoder()` with whichever TOML library the project uses.
    do {
        let decoder = TOMLDecoder() // placeholder — add package dependency
        let cfg = try decoder.decode(BudgetsConfig.self, from: data)
        // Basic validation: professional_fees account required when present
        if let fees = cfg.professional_fees {
            for f in fees where f.account.trimmingCharacters(in: .whitespaces).isEmpty {
                throw ConfigError.validationFailed("professional_fees entry missing account")
            }
        }
        if let ext = cfg.external_budgets {
            for e in ext where e.account.trimmingCharacters(in: .whitespaces).isEmpty {
                throw ConfigError.validationFailed("external_budgets entry missing account")
            }
        }
        return cfg
    } catch {
        throw ConfigError.decodeError(error)
    }
}

// Example usage (for development/test)
if CommandLine.arguments.contains("--example-load") {
    do {
        let path = CommandLine.arguments.dropFirst().first
        let cfg = try loadBudgetsConfig(from: path)
        print("Loaded budgets config: \(cfg)")
    } catch {
        fputs("Config load error: \(error)\n", stderr)
        exit(1)
    }
}
