from __future__ import annotations

import asyncio
import json
import sys
import threading
import traceback
from dataclasses import asdict

from teleapp.context import MessageContext
from teleapp.protocol import AppEvent
from teleapp.response import coerce_response

from robot.agents import AgentCoordinator
from robot.config import load_settings
from robot.routing import handle_request
from robot.state import ChatStateStore


class _StdoutEventQueue:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    def put_nowait(self, event: AppEvent) -> None:
        payload = _sanitize_surrogates(asdict(event))
        line = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()


class _SupervisorProxy:
    def __init__(self) -> None:
        self._event_queue = _StdoutEventQueue()


def _emit(type_: str, text: str, *, chat_id: int | None, request_id: str | None) -> None:
    event = AppEvent(type=type_, text=text, chat_id=chat_id, request_id=request_id, stream="stdout")
    line = json.dumps(_sanitize_surrogates(asdict(event)), ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _emit_event(event: AppEvent) -> None:
    line = json.dumps(_sanitize_surrogates(asdict(event)), ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _sanitize_surrogates(value):
    if isinstance(value, str):
        return value.encode("utf-8", errors="replace").decode("utf-8")
    if isinstance(value, dict):
        return {key: _sanitize_surrogates(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_surrogates(item) for item in value]
    return value


async def _run() -> None:
    settings = load_settings()
    store = ChatStateStore(settings)
    agents = AgentCoordinator(settings, store)
    agents.attach_supervisor(_SupervisorProxy())
    agents.start()

    try:
        while True:
            line = await asyncio.to_thread(sys.stdin.readline)
            if line == "":
                break
            raw = line.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                _emit("error", f"invalid input payload: {raw}", chat_id=None, request_id=None)
                continue
            if not isinstance(payload, dict) or str(payload.get("type") or "").lower() != "input":
                continue

            chat_id = int(payload.get("chat_id") or 0)
            request_id = str(payload.get("request_id") or "").strip() or None
            text = str(payload.get("text") or "")
            command = str(payload.get("command") or "").strip() or None
            ctx = MessageContext(chat_id=chat_id, text=text, request_id=request_id, command=command)
            try:
                body = await handle_request(ctx, settings, store, agents)
                event = coerce_response(body, ctx)
                _emit_event(event)
            except Exception as exc:
                traceback.print_exc(file=sys.stderr)
                _emit("error", str(exc), chat_id=chat_id, request_id=request_id)
    finally:
        await agents.shutdown()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
