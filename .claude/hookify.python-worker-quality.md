---
name: python-worker-quality
enabled: true
event: file
conditions:
  - field: file_path
    operator: regex_match
    pattern: worker/.*\.py$
---

You just edited a Python file in `worker/`. Run quality checks before finishing:

```
mise run fmt     # ruff format — fix formatting first
mise run lint    # ruff check + pyright — check after formatting
```

Both commands run inside the Ubuntu container via Apple's `container` tool — do not run ruff or pyright natively. If `gnucash-mcp:dev` image is not built, run `mise run build-dev` first.
