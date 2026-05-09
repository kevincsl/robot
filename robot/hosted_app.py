from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
import traceback
from contextlib import suppress
from dataclasses import asdict

from telegram import Bot
from telegram.error import RetryAfter
from teleapp.context import DocumentInput, MessageContext
from teleapp.protocol import AppEvent
from teleapp.response import coerce_response

from robot.agents import AgentCoordinator
from robot.config import load_settings
from robot.routing import AGENT_REQUEST, classify_request, handle_request
from robot.state import ChatStateStore
from robot.display_mode import wrap_text_for_code_display
from robot.text import configure_stdio_utf8, normalize_text


_TYPING_ERROR_INTERVAL_SECONDS = 10.0
_TYPING_BACKOFF_SECONDS = 30.0


def _typing_min_interval_seconds() -> float:
    raw = os.getenv("ROBOT_TYPING_INTERVAL_SECONDS", "4").strip()
    try:
        value = float(raw)
    except ValueError:
        return 4.0
    return min(60.0, max(3.0, value))


def _event_typing_state(event: AppEvent) -> bool | None:
    if str(getattr(event, "type", "") or "").strip().lower() != "status":
        return None
    raw = event.raw if isinstance(event.raw, dict) else {}
    typing = str(raw.get("typing") or "").strip().lower()
    if typing in {"active", "start", "on", "true", "1"}:
        return True
    if typing in {"stop", "done", "off", "false", "0"}:
        return False
    return None


def _should_send_typing(event: AppEvent) -> bool:
    return _event_typing_state(event) is True


def _should_stop_typing(event: AppEvent) -> bool:
    event_type = str(getattr(event, "type", "") or "").strip().lower()
    if event_type == "noop":
        return False
    typing_state = _event_typing_state(event)
    if typing_state is not None:
        return typing_state is False
    if event_type == "status":
        return False
    return True


class _TelegramTypingClient:
    def __init__(self, token: str) -> None:
        clean = str(token or "").strip()
        self._bot = Bot(clean) if clean else None
        self._initialized = False

    @property
    def enabled(self) -> bool:
        return self._bot is not None

    async def send(self, chat_id: int) -> None:
        if self._bot is None:
            return
        if not self._initialized:
            await self._bot.initialize()
            self._initialized = True
        await self._bot.send_chat_action(chat_id=chat_id, action="typing")

    async def close(self) -> None:
        if self._bot is None or not self._initialized:
            return
        await self._bot.shutdown()
        self._initialized = False


class _TypingController:
    def __init__(self, client: _TelegramTypingClient | None) -> None:
        self._client = client if client is not None and client.enabled else None
        self._last_sent_at: dict[int, float] = {}
        self._backoff_until: dict[int, float] = {}
        self._tasks: dict[int, asyncio.Task[None]] = {}

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def observe(self, event: AppEvent) -> None:
        if not self.enabled:
            return
        chat_id = event.chat_id
        if not isinstance(chat_id, int):
            return
        if _should_send_typing(event):
            self.start(chat_id)
            return
        if _should_stop_typing(event):
            self.stop(chat_id)

    def start(self, chat_id: int) -> None:
        if not self.enabled:
            return
        task = self._tasks.get(chat_id)
        if task is not None and not task.done():
            return
        self._tasks[chat_id] = asyncio.create_task(self._typing_loop(chat_id))

    def stop(self, chat_id: int) -> None:
        task = self._tasks.pop(chat_id, None)
        if task is None:
            return
        task.cancel()

    async def maybe_send(self, chat_id: int, *, now: float | None = None) -> None:
        if self._client is None:
            return
        current = time.monotonic() if now is None else float(now)
        backoff_until = self._backoff_until.get(chat_id, 0.0)
        if current < backoff_until:
            return
        last = self._last_sent_at.get(chat_id, 0.0)
        if current - last < _typing_min_interval_seconds():
            return
        try:
            await self._client.send(chat_id)
        except RetryAfter as exc:
            retry_after_raw = getattr(exc, "retry_after", 0) or 0
            if hasattr(retry_after_raw, "total_seconds"):
                retry_after = float(retry_after_raw.total_seconds())
            else:
                retry_after = float(retry_after_raw)
            wait_seconds = max(_TYPING_BACKOFF_SECONDS, retry_after)
            self._backoff_until[chat_id] = current + wait_seconds
            self._last_sent_at[chat_id] = current
            return
        except Exception:
            self._backoff_until[chat_id] = current + _TYPING_ERROR_INTERVAL_SECONDS
            self._last_sent_at[chat_id] = current
            return
        self._last_sent_at[chat_id] = current

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for chat_id in list(self._tasks.keys()):
            self.stop(chat_id)
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        if self._client is not None:
            with suppress(Exception):
                await self._client.close()

    async def _typing_loop(self, chat_id: int) -> None:
        while True:
            await self.maybe_send(chat_id)
            await asyncio.sleep(_typing_min_interval_seconds())


def _apply_code_display_mode(event: AppEvent, store: ChatStateStore | None) -> AppEvent:
    if store is None or event.type not in {"output", "error"}:
        return event
    chat_id = event.chat_id
    if not isinstance(chat_id, int):
        return event
    mode = store.get_code_display_mode(chat_id)
    text = wrap_text_for_code_display(event.text, mode)
    if text == event.text:
        return event
    return AppEvent(
        type=event.type,
        text=text,
        chat_id=event.chat_id,
        request_id=event.request_id,
        process_pid=event.process_pid,
        stream=event.stream,
        raw=event.raw,
    )


class _StdoutEventQueue:
    def __init__(self, typing_controller: _TypingController | None = None, store: ChatStateStore | None = None) -> None:
        self._lock = threading.Lock()
        self._typing_controller = typing_controller
        self._store = store

    def put_nowait(self, event: AppEvent) -> None:
        if self._typing_controller is not None:
            self._typing_controller.observe(event)
        event = _apply_code_display_mode(event, self._store)
        if _should_suppress_event(event):
            return
        payload = _sanitize_surrogates(asdict(event))
        line = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()


class _SupervisorProxy:
    def __init__(self, typing_controller: _TypingController | None = None, store: ChatStateStore | None = None) -> None:
        self._event_queue = _StdoutEventQueue(typing_controller, store)


def _emit(type_: str, text: str, *, chat_id: int | None, request_id: str | None) -> None:
    event = AppEvent(type=type_, text=text, chat_id=chat_id, request_id=request_id, stream="stdout")
    line = json.dumps(_sanitize_surrogates(asdict(event)), ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _should_suppress_event(event: AppEvent) -> bool:
    return str(getattr(event, "type", "") or "").strip().lower() == "noop"


def _emit_event(
    event: AppEvent,
    typing_controller: _TypingController | None = None,
    store: ChatStateStore | None = None,
) -> None:
    if typing_controller is not None:
        typing_controller.observe(event)
    event = _apply_code_display_mode(event, store)
    if _should_suppress_event(event):
        return
    line = json.dumps(_sanitize_surrogates(asdict(event)), ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _sanitize_surrogates(value):
    if isinstance(value, str):
        return normalize_text(value)
    if isinstance(value, dict):
        return {key: _sanitize_surrogates(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_surrogates(item) for item in value]
    return value


async def _run() -> None:
    configure_stdio_utf8()
    settings = load_settings()
    store = ChatStateStore(settings)
    agents = AgentCoordinator(settings, store)
    typing_controller = _TypingController(_TelegramTypingClient(os.getenv("TELEAPP_TOKEN", "")))
    agents.attach_supervisor(_SupervisorProxy(typing_controller, store))
    agents.start()

    from robot.coordinator import RobotCoordinator
    coordinator = RobotCoordinator(settings.state_home, settings.robot_id)
    coordinator.update_status(status="starting")

    async def heartbeat_loop():
        while True:
            await asyncio.sleep(15)
            try:
                state = store.get_chat_state(0) if store.list_chat_ids() else {}
                coordinator.update_status(
                    status="running",
                    current_provider=state.get("provider"),
                    current_model=state.get("model"),
                    active_chats=len(store.list_chat_ids()),
                    queue_size=len(store.get_agent_queue(0)) if store.list_chat_ids() else 0,
                )
            except Exception:
                pass

    heartbeat_task = asyncio.create_task(heartbeat_loop())

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
            raw = payload.get("raw")
            document = None
            caption = None
            if isinstance(raw, dict):
                caption_raw = raw.get("caption")
                if isinstance(caption_raw, str):
                    caption = caption_raw
                doc = raw.get("document")
                if isinstance(doc, dict):
                    file_id = str(doc.get("file_id") or "").strip()
                    file_unique_id = str(doc.get("file_unique_id") or "").strip()
                    if file_id and file_unique_id:
                        document = DocumentInput(
                            file_id=file_id,
                            file_unique_id=file_unique_id,
                            file_name=str(doc.get("file_name") or "").strip() or None,
                            mime_type=str(doc.get("mime_type") or "").strip() or None,
                            local_path=str(doc.get("local_path") or "").strip() or None,
                        )
            ctx = MessageContext(
                chat_id=chat_id,
                text=text,
                request_id=request_id,
                command=command,
                caption=caption,
                document=document,
            )
            try:
                request = classify_request(ctx)
                if request.kind == AGENT_REQUEST and request.payload.strip():
                    typing_controller.start(chat_id)
                    asyncio.create_task(typing_controller.maybe_send(chat_id))
                body = await handle_request(ctx, settings, store, agents)
                event = coerce_response(body, ctx)
                _emit_event(event, typing_controller, store)
            except Exception as exc:
                typing_controller.stop(chat_id)
                traceback.print_exc(file=sys.stderr)
                _emit("error", str(exc), chat_id=chat_id, request_id=request_id)
    finally:
        heartbeat_task.cancel()
        coordinator.update_status(status="stopped")
        await typing_controller.shutdown()
        await agents.shutdown()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
