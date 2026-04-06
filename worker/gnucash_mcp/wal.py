"""Write-ahead log (WAL) for MCP tool operations.

JSONL file; one entry per line.  Schema:
  {
    "id": "uuid4",
    "logged_at": "ISO-8601",
    "type": "fund_project | receive_invoice | pay_invoice | post_transaction | interest",
    "payload": {},
    "committed_at": null | "ISO-8601",
    "transaction_guid": null | "gnucash-guid-string"
  }

WAL_PATH is resolved from GNUCASH_WAL_PATH env var, falling back to
<book_path>.wal.jsonl (set once at import via init()).
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path


_wal_path: Path | None = None


def init(wal_path: Path) -> None:
    """Set the WAL file path. Call once at startup."""
    global _wal_path
    _wal_path = Path(wal_path)


def _path() -> Path:
    if _wal_path is not None:
        return _wal_path
    env = os.environ.get("GNUCASH_WAL_PATH")
    if env:
        return Path(env)
    book = os.environ.get("GNUCASH_BOOK_PATH", "/data/project.gnucash")
    return Path(book).with_suffix(".wal.jsonl")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append(entry_type: str, payload: dict) -> dict:
    """Append a new WAL entry. Returns the full entry dict (including id)."""
    entry = {
        "id": str(uuid.uuid4()),
        "logged_at": _now(),
        "type": entry_type,
        "payload": payload,
        "committed_at": None,
        "transaction_guid": None,
    }
    with open(_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
        f.flush()
        os.fsync(f.fileno())
    return entry


def mark_committed(entry_id: str, transaction_guid: str | None = None) -> None:
    """Set committed_at on an entry; optionally store transaction_guid."""
    wal = _path()
    if not wal.exists():
        return
    lines = []
    with open(wal, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("id") == entry_id:
                obj["committed_at"] = _now()
                if transaction_guid is not None:
                    obj["transaction_guid"] = transaction_guid
            lines.append(obj)
    # Atomic rewrite via temp file
    tmp = wal.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj) + "\n")
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(wal)


def pending() -> list[dict]:
    """Return all entries without committed_at, in logged_at order."""
    wal = _path()
    if not wal.exists():
        return []
    out = []
    with open(wal, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("committed_at") is None:
                out.append(obj)
    return sorted(out, key=lambda e: e["logged_at"])


def replay() -> list[dict]:
    """Alias for pending() — returns uncommitted entries in order for replay."""
    return pending()


def all_entries() -> list[dict]:
    """Return all WAL entries (committed + pending), in logged_at order."""
    wal = _path()
    if not wal.exists():
        return []
    out = []
    with open(wal, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            out.append(json.loads(line))
    return sorted(out, key=lambda e: e["logged_at"])
