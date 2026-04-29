"""Property-based tests for the dispatch layer.

Covers the JSON-RPC envelope contract: for any input to dispatch(), the
response is always a valid JSON-RPC object — never a crash, never a
structurally malformed response.

No GnuCash book is needed: unknown tool names and wrong argument types all
short-circuit before any session opens.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from gnucash_mcp.dispatch import dispatch, HANDLERS

# ── Strategies ────────────────────────────────────────────────────────────────

# Arbitrary JSON-serialisable scalars and shallow structures.
json_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=64),
)

json_values = st.one_of(
    json_scalars,
    st.lists(json_scalars, max_size=4),
    st.dictionaries(st.text(max_size=16), json_scalars, max_size=4),
)

# A "request id" as MCP clients produce: int, string, or null.
req_ids = st.one_of(st.integers(), st.text(max_size=16), st.none())

known_tool_names = st.sampled_from(sorted(HANDLERS.keys()))

unknown_tool_names = st.text(min_size=1, max_size=32).filter(
    lambda n: n not in HANDLERS
)

arbitrary_arguments = st.dictionaries(
    st.text(max_size=16), json_values, max_size=6
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _is_valid_jsonrpc_response(resp: dict, req_id) -> bool:
    """Assert structural JSON-RPC 2.0 invariants."""
    if resp.get("jsonrpc") != "2.0":
        return False
    if resp.get("id") != req_id:
        return False
    has_result = "result" in resp
    has_error = "error" in resp
    # Exactly one of result/error must be present.
    if has_result == has_error:
        return False
    if has_error:
        err = resp["error"]
        if not isinstance(err.get("code"), int):
            return False
        if not isinstance(err.get("message"), str):
            return False
    return True


# ── P-D1: Any tools/call produces a valid JSON-RPC envelope ──────────────────


@settings(max_examples=200)
@given(
    req_id=req_ids,
    tool_name=st.text(max_size=32),
    arguments=arbitrary_arguments,
)
def test_dispatch_always_returns_valid_jsonrpc(req_id, tool_name, arguments):
    """For any tool name and arguments, dispatch() never raises and always
    returns a structurally valid JSON-RPC 2.0 response."""
    request = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    resp = dispatch(request)
    assert isinstance(resp, dict), "dispatch() must return a dict"
    assert _is_valid_jsonrpc_response(resp, req_id), f"Invalid JSON-RPC shape: {resp}"


# ── P-D2: Unknown tool name always returns -32601 ─────────────────────────────


@settings(max_examples=100)
@given(req_id=req_ids, tool_name=unknown_tool_names)
def test_unknown_tool_returns_32601(req_id, tool_name):
    """Any tool name not in HANDLERS produces error code -32601."""
    request = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": {}},
    }
    resp = dispatch(request)
    assert "error" in resp
    assert resp["error"]["code"] == -32601


# ── P-D3: Known tool with wrong args returns -32603, not a crash ──────────────


@settings(max_examples=100)
@given(req_id=req_ids, tool_name=known_tool_names, arguments=arbitrary_arguments)
def test_known_tool_wrong_args_returns_32603_or_success(req_id, tool_name, arguments):
    """Known tool names with arbitrary wrong arguments produce either a
    success (if args happen to be valid) or error code -32603 (handler raised).
    The response is always a valid JSON-RPC envelope — never a raw exception."""
    request = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    resp = dispatch(request)
    assert isinstance(resp, dict)
    assert _is_valid_jsonrpc_response(resp, req_id)
    if "error" in resp:
        # Wrong args may produce -32603 (handler exception) or -32601 (not found).
        assert resp["error"]["code"] in (-32601, -32603)


# ── P-D4: resources/read with unknown URI returns -32601 ─────────────────────


@settings(max_examples=100)
@given(
    req_id=req_ids,
    uri=st.text(min_size=1, max_size=64).filter(lambda u: u not in HANDLERS),
)
def test_unknown_resource_uri_returns_32601(req_id, uri):
    """Any resource URI not in HANDLERS produces error code -32601."""
    request = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "resources/read",
        "params": {"uri": uri},
    }
    resp = dispatch(request)
    assert "error" in resp
    assert resp["error"]["code"] == -32601


# ── P-D5: Unsupported method always returns -32601 ────────────────────────────


@settings(max_examples=100)
@given(
    req_id=req_ids,
    method=st.text(min_size=1, max_size=32).filter(
        lambda m: m not in ("tools/call", "resources/read")
    ),
)
def test_unsupported_method_returns_32601(req_id, method):
    """Any method other than tools/call and resources/read returns -32601."""
    request = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": {}}
    resp = dispatch(request)
    assert "error" in resp
    assert resp["error"]["code"] == -32601
