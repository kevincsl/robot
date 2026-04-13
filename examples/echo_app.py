from __future__ import annotations

import json
import sys


def main() -> int:
    for line in sys.stdin:
        payload = json.loads(line)
        chat_id = payload.get("chat_id")
        request_id = payload.get("request_id")
        text = str(payload.get("text") or "")
        response = {
            "type": "output",
            "chat_id": chat_id,
            "request_id": request_id,
            "text": f"echo: {text}",
        }
        print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
