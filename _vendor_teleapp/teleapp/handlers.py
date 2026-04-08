from __future__ import annotations

import inspect
from typing import Awaitable, Callable, Protocol

from teleapp.context import MessageContext


class SupportsOnText(Protocol):
    async def on_text(self, ctx: MessageContext) -> str | None: ...


HandlerCallable = Callable[[MessageContext], Awaitable[str | None] | str | None]


async def invoke_handler(handler: HandlerCallable, ctx: MessageContext) -> str | None:
    result = handler(ctx)
    if inspect.isawaitable(result):
        result = await result
    if result is None:
        return None
    return str(result)
