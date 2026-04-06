"""Simple WAL JSONL helper (skeleton) extracted from DEVELOPMENT.md"""
import json
import uuid
from datetime import datetime

WAL_PATH = "mcp-wal.jsonl"

def append(entry: dict) -> str:
    entry_id = str(uuid.uuid4())
    entry["id"] = entry_id
    entry["logged_at"] = datetime.utcnow().isoformat()
    entry["committed_at"] = None
    with open(WAL_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry_id

def mark_committed(entry_id: str) -> None:
    # naive implementation: rewrite file
    lines = []
    with open(WAL_PATH, "r", encoding="utf-8") as f:
        for l in f:
            obj = json.loads(l)
            if obj.get("id") == entry_id:
                obj["committed_at"] = datetime.utcnow().isoformat()
            lines.append(obj)
    with open(WAL_PATH, "w", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj) + "\n")

def pending() -> list:
    out = []
    with open(WAL_PATH, "r", encoding="utf-8") as f:
        for l in f:
            obj = json.loads(l)
            if obj.get("committed_at") is None:
                out.append(obj)
    return out
