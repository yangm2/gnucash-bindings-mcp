# Appendix A — Test Execution

## Appendix A — Test Execution

Tests are named `T{phase}.{milestone}.{number}`. Within a milestone, run in
order. Milestones within a phase run in order.

**Two test modes:**

*Unit tests* — pytest with GnuCash book fixtures. Run inside the container
against a temp directory. No HTTP server, no Claude Desktop. Cover all T1.x,
T2.x, T6.x, T7.x logic.

*Integration tests* — require the full stack (Swift proxy running, Claude Desktop
connected). These are manual tests recorded in `TEST_RESULTS.md`. Identified in
test lists as `(manual)` or by reference to Claude Desktop / CoWork behavior.

Automated test fixtures:

```python
# tests/conftest.py
import pytest
from pathlib import Path
import gnucash

@pytest.fixture
def fresh_book(tmp_path):
    path = str(tmp_path / "test.gnucash")
    from gnucash_mcp.session import open_session, close_session
    session = open_session(path, is_new=True)  # uses SESSION_NEW_STORE + early save
    book = session.book
    yield book, path
    try:
        close_session(session)
    except Exception:
        pass

@pytest.fixture
def initialized_book(tmp_path):
    """Book with full chart of accounts (MC-6)."""
    path = str(tmp_path / "project-test.gnucash")
    from scripts.init_book import initialize
    from gnucash_mcp.session import open_session, close_session
    initialize(path)
    session = open_session(path, is_new=False)  # uses SESSION_NORMAL_OPEN
    book = session.book
    yield book, path
    try:
        close_session(session)
    except Exception:
        pass

@pytest.fixture
def populated_book(tmp_path):
    """Book with chart of accounts + known historical transactions.
    Provides a stable base for budget vs actual and AP aging tests."""
    path = str(tmp_path / "project-populated.gnucash")
    from scripts.init_book import initialize
    from scripts.load_fixtures import load_known_invoices
    from gnucash_mcp.session import open_session, close_session
    initialize(path)
    load_known_invoices(path)   # AAI-101, AAI-102, PSE-101, PSE-102, MMEP series
    session = open_session(path, is_new=False)
    book = session.book
    yield book, path
    try:
        close_session(session)
    except Exception:
        pass
```

Tests marked `(manual)` require human verification; record outcomes in
`TEST_RESULTS.md` with date, tester, and pass/fail.

Run automated unit suite inside container:
```zsh
cd gnucash-mcp
container run --rm \
  --volume $(pwd):/src \
  --volume /tmp/test-books:/data \
  gnucash-mcp:latest \
  bash -c "cd /src && uv run pytest tests/ -v --ignore=tests/test_integration.py"
```

Run HTTP integration smoke tests (requires Swift proxy running):
```zsh
# Verify proxy responds to initialize without starting a container
curl -s -X POST http://localhost:8980/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"0.1"}}}' \
  | python3 -m json.tool | grep '"name"'
# Expected: "gnucash-myproject"

# Verify tools/list returns full catalog without starting a container
curl -s -X POST http://localhost:8980/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | python3 -m json.tool | grep '"name"'
# Expected: list of all 21 tool names

# Verify static resource served without container
curl -s -X POST http://localhost:8980/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"resources/read","params":{"uri":"gnucash://book-setup-guide"}}' \
  | python3 -m json.tool | head -5
# Expected: resource content, no container started

# Verify tool call dispatches to container
curl -s -X POST http://localhost:8980/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"get_project_summary","arguments":{}}}' \
  | python3 -m json.tool
# Expected: project summary JSON, container started and stopped
```

---

