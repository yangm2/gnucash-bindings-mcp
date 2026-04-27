---
name: swift-proxy-quality
enabled: true
event: file
conditions:
  - field: file_path
    operator: regex_match
    pattern: proxy/.*\.swift$
---

You just edited a Swift file in `proxy/`. Run quality checks before finishing:

```
swift-format format -i <edited-file>   # format in place first
xcrun swiftc -typecheck <edited-file>  # then typecheck
```

Once the proxy has a Package.swift, use `swift build` from the proxy directory for the typecheck step instead.
