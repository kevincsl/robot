from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime
import inspect
import sys

from teleapp.config import TeleappConfig
from teleapp.context import MessageContext
from teleapp.handlers import HandlerCallable, SupportsOnText
from teleapp.hot_reload import PollingHotReload
from teleapp.protocol import AppEvent
from teleapp.response import coerce_response
from teleapp.runner import ProcessRunner
from teleapp.state import ChatSessionState, RuntimeState


@dataclass(slots=True)
class QueuedRequest:
    chat_id: int
    text: str
    request_id: str
    queued_at: datetime
    command: str | None = None
    raw: dict | None = None
    dispatched_at: datetime | None = None
    first_event_at: datetime | None = None


def _console(message: str) -> None:
    sys.stderr.write(f"[teleapp] {message}\n")
    sys.stderr.flush()


def _safe_text(text: str | None) -> str:
    return (text or "").encode("utf-8", errors="replace").decode("utf-8")


class AppSupervisor:
    def __init__(self, config: TeleappConfig) -> None:
        self._config = config
        self._state = RuntimeState(watched_paths=[str(path) for path in config.watch_paths])
        self._runner: ProcessRunner | None = None
        self._watcher_task: asyncio.Task[None] | None = None
        self._reload_lock = asyncio.Lock()
        self._next_request_number = 0
        self._pending_reload_reason: str | None = None
        self._chat_queues: dict[int, deque[QueuedRequest]] = {}
        self._ready_chat_ids: deque[int] = deque()
        self._active_request: QueuedRequest | None = None
        self._callable_handler: HandlerCallable | None = None
        self._object_handler: SupportsOnText | None = None
        self._event_queue: asyncio.Queue[AppEvent] = asyncio.Queue()
        self._expected_exit_pids: set[int] = set()

    @property
    def state(self) -> RuntimeState:
        return self._state

    def attach_callable(self, handler: HandlerCallable) -> None:
        self._callable_handler = handler
        self._object_handler = None

    def attach_handler(self, handler: SupportsOnText) -> None:
        self._object_handler = handler
        self._callable_handler = None

    async def start(self) -> None:
        if self._state.running:
            return
        if self._uses_inprocess_handler():
            self._state.running = True
            self._state.pid = None
            self._state.started_at = datetime.now()
            _console("supervisor started in-process mode")
            return

        loop = asyncio.get_running_loop()
        if self._runner is None:
            self._runner = ProcessRunner(
                loop=loop,
                python_executable=self._config.python_executable,
                app_path=self._require_app_path(),
            )

        self._runner.start()
        self._state.running = True
        self._state.pid = self._runner.process.pid if self._runner.process else None
        self._state.started_at = datetime.now()
        _console(f"hosted app started pid={self._state.pid or '-'}")

        if self._config.hot_reload and self._watcher_task is None:
            watcher = PollingHotReload(
                paths=self._config.watch_paths,
                quiet_seconds=self._config.reload_quiet_seconds,
                poll_seconds=self._config.reload_poll_seconds,
                on_reload=self.restart,
            )
            self._watcher_task = asyncio.create_task(watcher.run())
            self._watcher = watcher
            _console("hot reload watcher started")

    async def stop(self) -> None:
        if self._watcher_task is not None:
            self._watcher.stop()
            self._watcher_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watcher_task
            self._watcher_task = None

        if self._runner is not None:
            pid = await asyncio.to_thread(self._runner.stop)
            if pid is not None:
                self._expected_exit_pids.add(pid)
                _console(f"hosted app stop requested pid={pid}")

        self._state.running = False
        self._state.pid = None

    async def restart(self, reason: str = "manual restart") -> None:
        _console(f"restart requested reason={reason}")
        async with self._reload_lock:
            if self._state.busy:
                self._pending_reload_reason = reason
                self._state.last_restart_reason = f"queued: {reason}"
                _console("restart queued because supervisor is busy")
                return
            if self._uses_inprocess_handler():
                self._state.running = True
                self._state.pid = None
                self._state.last_restart_at = datetime.now()
                self._state.last_restart_reason = reason
                self._state.restart_count += 1
                _console("in-process restart applied")
                return
            if self._runner is not None:
                current_pid = self._runner.process.pid if self._runner.process is not None else None
                pid = await asyncio.to_thread(self._runner.stop)
                if pid is not None:
                    self._expected_exit_pids.add(pid)
                self._runner.start()
                self._state.running = True
                self._state.pid = self._runner.process.pid if self._runner.process else None
                self._state.last_restart_at = datetime.now()
                self._state.last_restart_reason = reason
                self._state.restart_count += 1
                _console(f"hosted app restarted old_pid={current_pid or '-'} new_pid={self._state.pid or '-'}")
                await self._dispatch_next_request()

    async def send_text(self, *, chat_id: int, text: str, command: str | None = None, raw: dict | None = None) -> None:
        await self.start()
        self._next_request_number += 1
        request_id = f"{chat_id}-{self._next_request_number}"
        session = self._get_session(chat_id)
        queued = QueuedRequest(
            chat_id=chat_id,
            text=_safe_text(text),
            request_id=request_id,
            queued_at=datetime.now(),
            command=_safe_text(command) if command else None,
            raw=raw,
        )
        queue = self._chat_queues.setdefault(chat_id, deque())
        was_empty = not queue
        queue.append(queued)
        if was_empty and chat_id not in self._ready_chat_ids:
            self._ready_chat_ids.append(chat_id)
        session.queued_requests = len(queue)
        session.last_request_id = request_id
        session.last_activity_at = queued.queued_at
        self._state.last_chat_id = chat_id
        self._refresh_busy_state()
        await self._dispatch_next_request()

    async def next_event(self) -> AppEvent:
        await self.start()
        while True:
            event = await self._read_next_event()
            current_pid = self._runner.process.pid if self._runner is not None and self._runner.process is not None else None
            if event.process_pid is not None and current_pid is not None and event.process_pid != current_pid:
                continue

            if event.type == "error":
                self._state.last_error = event.text
            if event.stream == "stderr" and event.text:
                _console(f"hosted stderr: {event.text}")
            if event.chat_id is None:
                event.chat_id = self._active_request.chat_id if self._active_request is not None else self._state.last_chat_id
            if event.text.startswith("Hosted app exited with code"):
                return_code = None
                if isinstance(event.raw, dict):
                    raw_code = event.raw.get("return_code")
                    if isinstance(raw_code, int):
                        return_code = raw_code
                self._state.last_exit_code = return_code
                self._state.running = False
                self._state.pid = None
                if event.process_pid in self._expected_exit_pids:
                    self._expected_exit_pids.discard(event.process_pid)
                elif return_code not in (None, 0) and self._config.auto_restart_on_crash:
                    await self._restart_after_crash(return_code)

            await self._complete_request(event)
            await self._flush_pending_reload()
            return event

    async def _read_next_event(self) -> AppEvent:
        if self._runner is not None and not self._uses_inprocess_handler():
            return await self._runner.queue.get()
        return await self._event_queue.get()

    def _get_session(self, chat_id: int) -> ChatSessionState:
        session = self._state.chat_sessions.get(chat_id)
        if session is None:
            session = ChatSessionState(chat_id=chat_id)
            self._state.chat_sessions[chat_id] = session
        return session

    async def _dispatch_next_request(self) -> None:
        if self._active_request is not None:
            return

        while self._ready_chat_ids:
            chat_id = self._ready_chat_ids.popleft()
            queue = self._chat_queues.get(chat_id)
            if not queue:
                continue

            request = queue.popleft()
            session = self._get_session(chat_id)
            session.queued_requests = len(queue)
            session.active_request_id = request.request_id
            session.last_activity_at = datetime.now()
            self._active_request = request
            self._state.active_chat_id = chat_id
            self._state.active_request_id = request.request_id
            self._refresh_busy_state()

            if self._uses_inprocess_handler():
                await self._dispatch_inprocess_request(request)
                if queue:
                    self._ready_chat_ids.append(chat_id)
                return

            assert self._runner is not None

            try:
                request.dispatched_at = datetime.now()
                await asyncio.to_thread(
                    self._runner.send_input,
                    chat_id=request.chat_id,
                    text=request.text,
                    request_id=request.request_id,
                    command=request.command,
                    raw=request.raw,
                )
            except Exception:
                self._clear_active_request()
                raise

            if queue:
                self._ready_chat_ids.append(chat_id)
            return

        self._clear_active_request()

    async def _complete_request(self, event: AppEvent) -> None:
        active = self._active_request
        if active is None:
            self._refresh_busy_state()
            return

        if event.request_id and event.request_id != active.request_id:
            self._refresh_busy_state()
            return

        if event.type not in {
            "output",
            "error",
            "status",
            "buttons",
            "photo",
            "animation",
            "document",
            "sticker",
            "location",
            "venue",
            "audio",
            "voice",
            "video",
            "contact",
            "poll",
        }:
            self._refresh_busy_state()
            return

        now = datetime.now()
        if active.first_event_at is None:
            active.first_event_at = now

        session = self._get_session(active.chat_id)
        session.active_request_id = None
        session.last_activity_at = now
        queued_ms = int((active.dispatched_at - active.queued_at).total_seconds() * 1000) if active.dispatched_at else 0
        first_event_ms = int((active.first_event_at - active.dispatched_at).total_seconds() * 1000) if active.dispatched_at and active.first_event_at else 0
        total_ms = int((now - active.queued_at).total_seconds() * 1000)
        session.last_timing = {
            "request_id": active.request_id,
            "chat_id": active.chat_id,
            "command": active.command or "",
            "queued_ms": queued_ms,
            "first_event_ms": first_event_ms,
            "total_ms": total_ms,
            "event_type": event.type,
        }
        _console(
            "request timing "
            f"chat={active.chat_id} "
            f"request_id={active.request_id} "
            f"queued_ms={queued_ms} "
            f"first_event_ms={first_event_ms} "
            f"total_ms={total_ms} "
            f"event_type={event.type}"
        )
        self._clear_active_request()
        await self._dispatch_next_request()

    async def _flush_pending_reload(self) -> None:
        if self._state.busy or not self._pending_reload_reason:
            return
        reason = self._pending_reload_reason
        self._pending_reload_reason = None
        await self.restart(reason)

    async def _restart_after_crash(self, return_code: int) -> None:
        _console(f"hosted app crashed return_code={return_code}; scheduling auto-restart")
        if self._config.restart_backoff_seconds > 0:
            await asyncio.sleep(self._config.restart_backoff_seconds)
        await self.restart(f"crash auto-restart (code {return_code})")

    def _clear_active_request(self) -> None:
        self._active_request = None
        self._state.active_chat_id = None
        self._state.active_request_id = None
        self._refresh_busy_state()

    def _refresh_busy_state(self) -> None:
        total_queued = sum(len(queue) for queue in self._chat_queues.values())
        self._state.total_queued_requests = total_queued
        self._state.busy = self._active_request is not None or total_queued > 0

    def _uses_inprocess_handler(self) -> bool:
        return self._callable_handler is not None or self._object_handler is not None

    def _require_app_path(self):
        if self._config.app_path is None:
            raise RuntimeError("Hosted app path is required for subprocess mode.")
        return self._config.app_path

    async def _dispatch_inprocess_request(self, request: QueuedRequest) -> None:
        handler = self._resolve_handler()
        if handler is None:
            raise RuntimeError("No in-process handler is attached.")

        ctx = MessageContext(
            chat_id=request.chat_id,
            text=request.text,
            request_id=request.request_id,
            command=request.command,
        )
        try:
            result = handler(ctx)
            if inspect.isawaitable(result):
                result = await result
            self._event_queue.put_nowait(coerce_response(result, ctx))
        except Exception as exc:
            self._state.last_error = str(exc)
            self._event_queue.put_nowait(
                AppEvent(
                    type="error",
                    text=str(exc),
                    chat_id=request.chat_id,
                    request_id=request.request_id,
                    stream="inprocess",
                )
            )

    def _resolve_handler(self):
        if self._callable_handler is not None:
            return self._callable_handler
        if self._object_handler is not None:
            return self._object_handler.on_text
        return None


import contextlib
