#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import os

import requests
from dotenv import load_dotenv


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a file to Telegram using bot token/chat id from .env")
    parser.add_argument("--file", required=True, help="Path to file to send")
    parser.add_argument("--caption", default="", help="Caption text")
    parser.add_argument("--env", default="", help="Optional .env path")
    args = parser.parse_args()

    if args.env:
        load_dotenv(dotenv_path=Path(args.env))
    else:
        load_dotenv()

    token = os.getenv("TELEAPP_TOKEN")
    chat_id = os.getenv("TELEAPP_ALLOWED_USER_ID")
    if not token:
        raise SystemExit("Missing TELEAPP_TOKEN")
    if not chat_id:
        raise SystemExit("Missing TELEAPP_ALLOWED_USER_ID")

    file_path = Path(args.file).expanduser().resolve()
    if not file_path.exists():
        raise SystemExit(f"File not found: {file_path}")

    suffix = file_path.suffix.lower()
    endpoint = "sendPhoto" if suffix in {".png", ".jpg", ".jpeg", ".webp"} else "sendDocument"
    key = "photo" if endpoint == "sendPhoto" else "document"
    url = f"https://api.telegram.org/bot{token}/{endpoint}"

    with file_path.open("rb") as fh:
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "caption": args.caption},
            files={key: fh},
            timeout=30,
        )
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("ok"):
        raise SystemExit(f"Telegram API error: {payload}")
    msg_id = payload.get("result", {}).get("message_id")
    print(f"sent message_id={msg_id}")


if __name__ == "__main__":
    main()
