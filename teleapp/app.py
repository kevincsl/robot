from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable

from telegram.error import Conflict

from teleapp.config import TeleappConfig, build_parser, build_runtime_config, load_config
from teleapp.context import MessageContext
from teleapp.protocol import AppEvent
from teleapp.response import ButtonResponse, ErrorResponse, Response, coerce_response
from teleapp.response import Button
from teleapp.telegram_gateway import TelegramGateway


class TeleApp:
    """High-level runtime facade for teleapp."""

    def __init__(self, config: TeleappConfig | None = None) -> None:
        self.config = config or build_runtime_config()
        if self.config.watch_paths is None:
            self.config.watch_paths = []
        self._gateway = TelegramGateway(self.config)
        self._message_handler = None
        self._routes: list[tuple[Callable[[MessageContext], bool], Callable[[MessageContext], object]]] = []
        self._command_handlers: dict[str, Callable[[MessageContext], object]] = {}
        self._before_message_hooks: list[Callable[..., object]] = []
        self._after_message_hooks: list[Callable[..., object]] = []
        self._error_hooks: list[Callable[..., object]] = []
        self._startup_hooks: list[Callable[..., object]] = []
        self._shutdown_hooks: list[Callable[..., object]] = []
        self._gateway.set_lifecycle_hooks(self._run_startup_hooks, self._run_shutdown_hooks)

    @classmethod
    def from_config(cls, config: TeleappConfig) -> "TeleApp":
        return cls(config)

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "TeleApp":
        return cls(load_config(args))

    @classmethod
    def from_cli(cls) -> "TeleApp":
        parser = build_parser()
        args = parser.parse_args()
        return cls.from_args(args)

    @property
    def gateway(self) -> TelegramGateway:
        return self._gateway

    @property
    def supervisor(self):
        return self._gateway.supervisor

    def message(self, func: Callable[[MessageContext], str | None]) -> Callable[[MessageContext], str | None]:
        self.attach_callable(func)
        return func

    def attach_callable(self, func) -> None:
        self._message_handler = func
        self._attach_dispatcher()

    def attach_handler(self, handler) -> None:
        self._message_handler = handler
        self._attach_dispatcher()

    def command(self, name: str):
        normalized = self._normalize_command_name(name)

        def decorator(func):
            self._command_handlers[normalized] = func
            self._gateway.set_custom_commands(set(self._command_handlers))
            self._attach_dispatcher()
            return func

        return decorator

    def route(self, predicate: Callable[[MessageContext], bool]):
        def decorator(func):
            self._routes.append((predicate, func))
            self._attach_dispatcher()
            return func

        return decorator

    def before_message(self, func):
        self._before_message_hooks.append(func)
        self._attach_dispatcher()
        return func

    def after_message(self, func):
        self._after_message_hooks.append(func)
        self._attach_dispatcher()
        return func

    def on_error(self, func):
        self._error_hooks.append(func)
        self._attach_dispatcher()
        return func

    def on_startup(self, func):
        self._startup_hooks.append(func)
        return func

    def on_shutdown(self, func):
        self._shutdown_hooks.append(func)
        return func

    def build_application(self):
        return self._gateway.build()

    def run(
        self,
        *,
        token: str | None = None,
        allowed_user_id: int | None = None,
        chat_id: int | None = None,
        app_path: str | None = None,
    ) -> None:
        if token is not None:
            self.config.telegram_token = token
        if allowed_user_id is not None:
            self.config.allowed_user_id = allowed_user_id
        if chat_id is not None:
            self.config.telegram_chat_id = chat_id
        if app_path is not None:
            self.config.app_path = build_runtime_config(app_path=app_path).app_path
        self.run_polling()

    def run_polling(self) -> None:
        delay_seconds = 5
        max_delay_seconds = 60
        while True:
            app = self.build_application()
            try:
                app.run_polling(drop_pending_updates=False)
            except Conflict as exc:
                self._gateway.mark_conflict(str(exc))

            conflict_detected, detail = self._gateway.consume_conflict_state()
            if not conflict_detected:
                return

            message = detail or "another process is using this bot token"
            sys.stderr.write(
                f"[teleapp] polling conflict backoff={delay_seconds}s reason={message}\n"
            )
            sys.stderr.flush()
            time.sleep(delay_seconds)
            delay_seconds = min(delay_seconds * 2, max_delay_seconds)

    def _attach_dispatcher(self) -> None:
        self._gateway.supervisor.attach_callable(self._dispatch_context)

    async def _dispatch_context(self, ctx: MessageContext):
        try:
            for hook in self._before_message_hooks:
                await self._invoke(hook, ctx)

            handler = self._resolve_handler(ctx)
            if handler is None:
                response = Response("handler completed", event_type="status")
            else:
                raw_result = await self._invoke(handler, ctx)
                response = self._event_to_response(coerce_response(raw_result, ctx))

            for hook in self._after_message_hooks:
                await self._invoke(hook, ctx, response)

            return response
        except Exception as exc:
            for hook in self._error_hooks:
                await self._invoke(hook, ctx, exc)
            return ErrorResponse(str(exc))

    async def _invoke(self, handler, *args):
        result = handler(*args)
        if hasattr(result, "__await__"):
            result = await result
        return result

    def _resolve_handler(self, ctx: MessageContext):
        if ctx.callback_query and ctx.callback_query.data:
            command_handler = self._command_handlers.get(ctx.callback_query.data)
            if command_handler is not None:
                return command_handler

        if ctx.command:
            command_handler = self._command_handlers.get(ctx.command)
            if command_handler is not None:
                return command_handler

        for predicate, handler in self._routes:
            if predicate(ctx):
                return handler

        handler = self._message_handler
        if handler is None:
            return None
        if hasattr(handler, "on_text"):
            return handler.on_text
        return handler

    @staticmethod
    def _event_to_response(event: AppEvent) -> Response:
        if event.type == "buttons":
            raw_buttons = event.raw.get("buttons") if isinstance(event.raw, dict) else None
            buttons = []
            if isinstance(raw_buttons, list):
                for item in raw_buttons:
                    if not isinstance(item, dict):
                        continue
                    text = str(item.get("text") or "").strip()
                    data = str(item.get("data") or "").strip()
                    if text and data:
                        buttons.append(Button(text=text, data=data))
            return ButtonResponse(text=event.text, buttons=buttons)
        return Response(text=event.text, event_type=event.type)

    async def _run_startup_hooks(self) -> None:
        for hook in self._startup_hooks:
            await self._invoke(hook)

    async def _run_shutdown_hooks(self) -> None:
        for hook in self._shutdown_hooks:
            await self._invoke(hook)

    @staticmethod
    def _normalize_command_name(name: str) -> str:
        return name.strip().lstrip("/").split("@", 1)[0].strip().lower()
