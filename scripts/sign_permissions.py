#!/usr/bin/env python3
"""Sign a permissions.json file with HMAC-SHA256.

Usage:
    ROBOT_PERMISSION_KEY=your_key python scripts/sign_permissions.py ~/.config/robot/permissions.json
"""
from __future__ import annotations

import hmac
import hashlib
import json
import os
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: ROBOT_PERMISSION_KEY=<key> python sign_permissions.py <permissions.json>")
        sys.exit(1)

    key = os.environ.get("ROBOT_PERMISSION_KEY", "")
    if not key:
        print("Error: ROBOT_PERMISSION_KEY environment variable is not set.")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Error: file not found: {path}")
        sys.exit(1)

    data = json.loads(path.read_text())
    payload = json.dumps(data["rules"], sort_keys=True, ensure_ascii=False)
    sig = hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    data["signature"] = sig
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"Signed: {path}")
    print(f"Signature: {sig}")


if __name__ == "__main__":
    main()
