import json
import os
import sys
from pathlib import Path

from gnucash_mcp.dispatch import dispatch
from gnucash_mcp.session import clear_stale_lock


def main():
    book_path = Path(os.environ.get("GNUCASH_BOOK_PATH", "/data/project.gnucash"))
    clear_stale_lock(book_path)
    raw = sys.stdin.buffer.read()
    request = json.loads(raw)
    response = dispatch(request)
    sys.stdout.write(json.dumps(response))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
