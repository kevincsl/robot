from __future__ import annotations

from teleapp import TeleApp

from robot.config import load_settings
from robot.routing import handle_request
from robot.state import ChatStateStore

SETTINGS = load_settings()
STORE = ChatStateStore(SETTINGS)
app = TeleApp()


@app.message
async def on_message(ctx):
    return await handle_request(ctx, SETTINGS, STORE)


def main() -> None:
    app.run()
