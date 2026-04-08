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

from robot.agents import AgentCoordinator
from robot.config import load_settings
from robot.routing import handle_request
from robot.state import ChatStateStore

LOGGER = logging.getLogger(__name__)

SETTINGS = load_settings()
STORE = ChatStateStore(SETTINGS)
AGENTS = AgentCoordinator(SETTINGS, STORE)
app = TeleApp()


@app.on_startup
async def on_startup():
    AGENTS.attach_supervisor(app.supervisor)
    AGENTS.start()


@app.on_shutdown
async def on_shutdown():
    await AGENTS.shutdown()


@app.message
async def on_message(ctx):
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
    application = app.build_application()
    application.add_error_handler(_telegram_error_handler)
    lock_path = SETTINGS.project_root / ".robot_state" / "robot.lock"
    with _single_instance_lock(lock_path):
        application.run_polling(drop_pending_updates=False)
