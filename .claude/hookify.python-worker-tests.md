---
name: python-worker-tests
enabled: true
event: stop
pattern: .*
---

Before finishing, if you edited any files in `worker/`, run the test suite:

```
mise run test    # pytest in dev container (depends build-dev)
```

If `gnucash-mcp:dev` is not built, `mise run test` will build it first automatically.
