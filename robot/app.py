from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from telegram import Update
from telegram.error import Conflict
from telegram.ext import ContextTypes
from teleapp import TeleApp
from teleapp.protocol import AppEvent

from robot.agents import AgentCoordinator
from robot.config import load_settings
from robot.routing import AGENT_REQUEST, classify_request, handle_request
from robot.state import ChatStateStore
from robot.text import configure_stdio_utf8

LOGGER = logging.getLogger(__name__)

SETTINGS = load_settings()
STORE = ChatStateStore(SETTINGS)
AGENTS = AgentCoordinator(SETTINGS, STORE)
app = TeleApp()
UI_BUILD_TAG = "ui-build:2026-04-10-b"


@app.on_startup
async def on_startup():
    AGENTS.attach_supervisor(app.supervisor)
    AGENTS.start()
    risk_enabled = bool(
        SETTINGS.codex_bypass_approvals_and_sandbox or SETTINGS.codex_skip_git_repo_check
    )
    queue = getattr(app.supervisor, "_event_queue", None)
    if queue is not None:
        chat_ids = STORE.list_chat_ids()
        target_chat_id = chat_ids[0] if chat_ids else app.config.allowed_user_id
        if target_chat_id:
            lines = [f"robot booted\n{UI_BUILD_TAG}"]
            if risk_enabled:
                lines.extend(
                    [
                        "",
                        "SECURITY WARNING",
                        f"- codex_bypass_approvals_and_sandbox={SETTINGS.codex_bypass_approvals_and_sandbox}",
                        f"- codex_skip_git_repo_check={SETTINGS.codex_skip_git_repo_check}",
                    ]
                )
            queue.put_nowait(
                AppEvent(
                    type="status",
                    text="\n".join(lines),
                    chat_id=target_chat_id,
                    request_id=None,
                    stream="inprocess",
                    raw={"status_key": "boot", "replace": True},
                )
            )


@app.on_shutdown
async def on_shutdown():
    await AGENTS.shutdown()


@app.message
async def on_message(ctx):
    request = classify_request(ctx)
    if request.kind == AGENT_REQUEST and request.payload.strip():
        queue = getattr(app.supervisor, "_event_queue", None)
        if queue is not None:
            state = STORE.get_chat_state(ctx.chat_id)
            queue_pending = len(STORE.get_agent_queue(ctx.chat_id))
            queue.put_nowait(
                AppEvent(
                    type="status",
                    text="\n".join(
                        [
                            "Request received.",
                            f"goal: {request.payload.strip()}",
                            f"project: {state['project_name']}",
                            f"path: {state['project_path']}",
                            f"queue_pending: {queue_pending}",
                            "elapsed: 00:00",
                        ]
                    ),
                    chat_id=ctx.chat_id,
                    request_id=ctx.request_id,
                    stream="inprocess",
                    raw={"status_key": "heartbeat", "replace": True},
                )
            )
    return await handle_request(ctx, SETTINGS, STORE, AGENTS)


@contextmanager
def _single_instance_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        handle.seek(0)
        if not handle.read(1):
            handle.seek(0)
            handle.write("0")
            handle.flush()

        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        handle.seek(0)
        handle.truncate(0)
        handle.write(str(os.getpid()))
        handle.flush()
        yield
    except OSError as exc:
        raise RuntimeError(
            f"Another robot instance is already running (lock: {lock_path})."
        ) from exc
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


async def _telegram_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if isinstance(err, Conflict):
        LOGGER.error(
            "Telegram polling conflict detected. Another process is using this bot token. "
            "Stop other bot instances and restart this process."
        )
        context.application.stop_running()
        return

    if isinstance(update, Update):
        LOGGER.exception("Unhandled Telegram update error (update_id=%s)", update.update_id, exc_info=err)
    else:
        LOGGER.exception("Unhandled Telegram polling error", exc_info=err)


def main() -> None:
    if os.getenv("ROBOT_ALLOW_DIRECT_POLLING", "").strip().lower() not in {"1", "true", "yes", "on"}:
        raise RuntimeError(
            "Direct polling mode is disabled by default. "
            "Use `teleapp robot.py` (or start_robot.bat/start_robot.sh). "
            "For explicit dev/debug direct polling, run `robot --standalone`."
        )
    configure_stdio_utf8()
    application = app.build_application()
    application.add_error_handler(_telegram_error_handler)
    lock_path = SETTINGS.project_root / ".robot_state" / "robot.lock"
    with _single_instance_lock(lock_path):
        application.run_polling(drop_pending_updates=False)
