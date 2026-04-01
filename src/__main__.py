import json, sys
from gnucash_mcp.dispatch import dispatch

def main():
    raw = sys.stdin.buffer.read()
    request = json.loads(raw)
    response = dispatch(request)
    sys.stdout.write(json.dumps(response))
    sys.stdout.flush()

if __name__ == "__main__":
    main()
