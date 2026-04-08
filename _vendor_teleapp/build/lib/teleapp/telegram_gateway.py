from __future__ import annotations

import asyncio
import contextlib
import sys

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Conflict
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from teleapp.config import TeleappConfig
from teleapp.context import (
    AnimationInput,
    AudioInput,
    CallbackQueryInput,
    ContactInput,
    DocumentInput,
    LocationInput,
    MessageContext,
    PhotoInput,
    PollInput,
    StickerInput,
    VenueInput,
    VideoInput,
    VoiceInput,
)
from teleapp.protocol import AppEvent
from teleapp.response import ButtonResponse
from teleapp.supervisor import AppSupervisor


MESSAGE_LIMIT = 3900


def _clip(text: str) -> str:
    cleaned = _safe_text(text).strip()
    if len(cleaned) <= MESSAGE_LIMIT:
        return cleaned
    return cleaned[: MESSAGE_LIMIT - 3] + "..."


def _safe_text(text: str | None) -> str:
    return (text or "").encode("utf-8", errors="replace").decode("utf-8")


def _console(message: str) -> None:
    sys.stderr.write(f"[teleapp] {message}\n")
    sys.stderr.flush()


class TelegramGateway:
    def __init__(self, config: TeleappConfig) -> None:
        self._config = config
        self._supervisor = AppSupervisor(config)
        self._consumer_task: asyncio.Task[None] | None = None
        self._custom_commands: set[str] = set()
        self._startup_hook = None
        self._shutdown_hook = None

    def build(self):
        app = ApplicationBuilder().token(self._config.telegram_token).build()
        app.add_error_handler(self._telegram_error_handler)
        app.add_handler(CommandHandler("start", self._start_command))
        app.add_handler(CommandHandler("help", self._help_command))
        app.add_handler(CommandHandler("status", self._status_command))
        app.add_handler(CommandHandler("restart", self._restart_command))
        for name in sorted(self._custom_commands):
            app.add_handler(CommandHandler(name, self._custom_command))
        app.add_handler(MessageHandler(filters.COMMAND, self._command_input))
        app.add_handler(CallbackQueryHandler(self._callback_query))
        app.add_handler(
            MessageHandler(
                (filters.TEXT & ~filters.COMMAND)
                | filters.PHOTO
                | filters.ANIMATION
                | filters.Document.ALL
                | filters.Sticker.ALL
                | filters.LOCATION
                | filters.VENUE
                | filters.VOICE
                | filters.AUDIO
                | filters.VIDEO
                | filters.CONTACT
                | filters.POLL,
                self._message_input,
            )
        )
        app.post_init = self._post_init
        app.post_shutdown = self._post_shutdown
        return app

    async def _telegram_error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        err = context.error
        if isinstance(err, Conflict):
            _console("telegram conflict detected: another process is using this bot token; stopping")
            context.application.stop_running()
            return

    @property
    def supervisor(self) -> AppSupervisor:
        return self._supervisor

    def set_custom_commands(self, names: set[str]) -> None:
        reserved = {"start", "help", "status", "restart"}
        self._custom_commands = {name for name in names if name not in reserved}

    def set_lifecycle_hooks(self, startup_hook, shutdown_hook) -> None:
        self._startup_hook = startup_hook
        self._shutdown_hook = shutdown_hook

    async def _post_init(self, app) -> None:
        watched = ", ".join(str(path) for path in self._config.watch_paths or []) or "-"
        _console(
            "starting gateway "
            f"app={self._config.app_path or '-'} "
            f"hot_reload={'on' if self._config.hot_reload else 'off'} "
            f"watch=[{watched}]"
        )
        if self._startup_hook is not None:
            await self._startup_hook()
        await self._supervisor.start()
        self._consumer_task = asyncio.create_task(self._event_consumer(app))
        _console("gateway ready")

    async def _post_shutdown(self, app) -> None:
        _console("gateway shutting down")
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._consumer_task
            self._consumer_task = None
        await self._supervisor.stop()
        if self._shutdown_hook is not None:
            await self._shutdown_hook()
        _console("gateway stopped")

    def _is_allowed(self, update: Update) -> bool:
        user = update.effective_user
        return bool(user and user.id == self._config.allowed_user_id)

    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update):
            return
        await update.message.reply_text(
            _clip(
                "\n".join(
                    [
                        "teleapp",
                        "/status",
                        "/restart",
                        "",
                        "Send any text to forward it to the hosted app.",
                    ]
                )
            )
        )

    async def _help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._start_command(update, context)

    async def _status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update):
            return
        state = self._supervisor.state
        lines = [
            f"running: {'yes' if state.running else 'no'}",
            f"pid: {state.pid or '-'}",
            f"app: {self._config.app_path}",
            f"busy: {'yes' if state.busy else 'no'}",
            f"active_chat_id: {state.active_chat_id or '-'}",
            f"active_request_id: {state.active_request_id or '-'}",
            f"queued_requests: {state.total_queued_requests}",
            f"last_restart_reason: {state.last_restart_reason or '-'}",
            f"last_error: {state.last_error or '-'}",
        ]
        for session in sorted(state.chat_sessions.values(), key=lambda item: item.chat_id):
            lines.append(
                f"chat {session.chat_id}: queued={session.queued_requests} active={session.active_request_id or '-'}"
            )
        await update.message.reply_text(_clip("\n".join(lines)))

    async def _restart_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update):
            return
        await self._supervisor.restart("manual /restart")
        await update.message.reply_text("Hosted app restarted.")

    async def _message_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update):
            return
        message = update.message
        if message is None:
            return
        payload = self._build_message_context(update)
        await self._supervisor.send_text(chat_id=update.effective_chat.id, text=payload.text)

    async def _command_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update):
            return
        message = update.message
        if message is None or not message.text:
            return
        command_name = _safe_text(message.text.split()[0].lstrip("/").split("@", 1)[0].strip().lower())
        if not command_name:
            return
        payload = ""
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1:
            payload = _safe_text(parts[1])
        await self._supervisor.send_text(
            chat_id=update.effective_chat.id,
            text=payload,
            command=command_name,
        )

    async def _callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update):
            return
        query = update.callback_query
        if query is None:
            return
        await query.answer()
        ctx = MessageContext(
            chat_id=update.effective_chat.id,
            text="",
            callback_query=CallbackQueryInput(id=query.id, data=_safe_text(query.data) if query.data else None),
            raw_update=update,
        )
        await self._supervisor.send_text(
            chat_id=update.effective_chat.id,
            text=ctx.text,
            command=_safe_text(query.data) if query.data else "",
        )

    async def _custom_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._command_input(update, context)

    async def _event_consumer(self, app) -> None:
        while True:
            event = await self._supervisor.next_event()
            target_chat_id = event.chat_id or self._config.telegram_chat_id
            if not target_chat_id:
                continue
            try:
                await self._send_event(app, target_chat_id, event)
            except Exception as exc:
                _console(f"send event failed: {exc.__class__.__name__}: {exc}")

    async def _send_event(self, app, chat_id: int, event: AppEvent) -> None:
        raw = event.raw or {}
        event_type = event.type

        if event_type == "photo":
            if raw.get("file_path"):
                with open(raw["file_path"], "rb") as fh:
                    caption = _safe_text(raw.get("caption")) if raw.get("caption") else None
                    await app.bot.send_photo(chat_id=chat_id, photo=fh, caption=caption)
                return
            if raw.get("file_id"):
                caption = _safe_text(raw.get("caption")) if raw.get("caption") else None
                await app.bot.send_photo(chat_id=chat_id, photo=raw["file_id"], caption=caption)
                return

        if event_type == "animation":
            if raw.get("file_path"):
                with open(raw["file_path"], "rb") as fh:
                    caption = _safe_text(raw.get("caption")) if raw.get("caption") else None
                    await app.bot.send_animation(chat_id=chat_id, animation=fh, caption=caption)
                return
            if raw.get("file_id"):
                caption = _safe_text(raw.get("caption")) if raw.get("caption") else None
                await app.bot.send_animation(chat_id=chat_id, animation=raw["file_id"], caption=caption)
                return

        if event_type == "document":
            if raw.get("file_path"):
                with open(raw["file_path"], "rb") as fh:
                    caption = _safe_text(raw.get("caption")) if raw.get("caption") else None
                    await app.bot.send_document(chat_id=chat_id, document=fh, caption=caption)
                return
            if raw.get("file_id"):
                caption = _safe_text(raw.get("caption")) if raw.get("caption") else None
                await app.bot.send_document(chat_id=chat_id, document=raw["file_id"], caption=caption)
                return

        if event_type == "sticker" and raw.get("sticker"):
            await app.bot.send_sticker(chat_id=chat_id, sticker=raw["sticker"])
            return

        if event_type == "location" and raw.get("latitude") is not None and raw.get("longitude") is not None:
            await app.bot.send_location(chat_id=chat_id, latitude=raw["latitude"], longitude=raw["longitude"])
            return

        if (
            event_type == "venue"
            and raw.get("latitude") is not None
            and raw.get("longitude") is not None
            and raw.get("title")
            and raw.get("address")
        ):
            await app.bot.send_venue(
                chat_id=chat_id,
                latitude=raw["latitude"],
                longitude=raw["longitude"],
                title=raw["title"],
                address=raw["address"],
            )
            return

        if event_type == "audio":
            if raw.get("file_path"):
                with open(raw["file_path"], "rb") as fh:
                    caption = _safe_text(raw.get("caption")) if raw.get("caption") else None
                    await app.bot.send_audio(chat_id=chat_id, audio=fh, caption=caption)
                return
            if raw.get("file_id"):
                caption = _safe_text(raw.get("caption")) if raw.get("caption") else None
                await app.bot.send_audio(chat_id=chat_id, audio=raw["file_id"], caption=caption)
                return

        if event_type == "voice":
            if raw.get("file_path"):
                with open(raw["file_path"], "rb") as fh:
                    caption = _safe_text(raw.get("caption")) if raw.get("caption") else None
                    await app.bot.send_voice(chat_id=chat_id, voice=fh, caption=caption)
                return
            if raw.get("file_id"):
                caption = _safe_text(raw.get("caption")) if raw.get("caption") else None
                await app.bot.send_voice(chat_id=chat_id, voice=raw["file_id"], caption=caption)
                return

        if event_type == "video":
            if raw.get("file_path"):
                with open(raw["file_path"], "rb") as fh:
                    caption = _safe_text(raw.get("caption")) if raw.get("caption") else None
                    await app.bot.send_video(chat_id=chat_id, video=fh, caption=caption)
                return
            if raw.get("file_id"):
                caption = _safe_text(raw.get("caption")) if raw.get("caption") else None
                await app.bot.send_video(chat_id=chat_id, video=raw["file_id"], caption=caption)
                return

        if event_type == "contact" and raw.get("phone_number") and raw.get("first_name"):
            await app.bot.send_contact(
                chat_id=chat_id,
                phone_number=raw["phone_number"],
                first_name=raw["first_name"],
                last_name=raw.get("last_name") or None,
            )
            return

        if event_type == "poll" and raw.get("question") and raw.get("options"):
            await app.bot.send_poll(
                chat_id=chat_id,
                question=_safe_text(str(raw["question"])),
                options=[_safe_text(str(item)) for item in raw["options"]],
                allows_multiple_answers=bool(raw.get("allows_multiple_answers")),
            )
            return

        if event_type == "buttons":
            buttons = raw.get("buttons") or []
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton(_safe_text(button["text"]), callback_data=button["data"])] for button in buttons]
            )
            await app.bot.send_message(chat_id=chat_id, text=_clip(event.text), reply_markup=keyboard)
            return

        await app.bot.send_message(chat_id=chat_id, text=_clip(self._render_event(event)))

    @staticmethod
    def _build_message_context(update: Update) -> MessageContext:
        message = update.message
        assert message is not None

        photos = None
        if message.photo:
            photos = [
                PhotoInput(
                    file_id=item.file_id,
                    file_unique_id=item.file_unique_id,
                    width=item.width,
                    height=item.height,
                )
                for item in message.photo
            ]

        animation = None
        if message.animation:
            animation = AnimationInput(
                file_id=message.animation.file_id,
                file_unique_id=message.animation.file_unique_id,
                width=message.animation.width,
                height=message.animation.height,
                duration=message.animation.duration,
                file_name=message.animation.file_name,
                mime_type=message.animation.mime_type,
            )

        document = None
        if message.document:
            document = DocumentInput(
                file_id=message.document.file_id,
                file_unique_id=message.document.file_unique_id,
                file_name=message.document.file_name,
                mime_type=message.document.mime_type,
            )

        sticker = None
        if message.sticker:
            sticker = StickerInput(
                file_id=message.sticker.file_id,
                file_unique_id=message.sticker.file_unique_id,
                emoji=message.sticker.emoji,
                set_name=message.sticker.set_name,
            )

        location = None
        if message.location:
            location = LocationInput(
                latitude=message.location.latitude,
                longitude=message.location.longitude,
            )

        venue = None
        if message.venue:
            venue = VenueInput(
                latitude=message.venue.location.latitude,
                longitude=message.venue.location.longitude,
                title=message.venue.title,
                address=message.venue.address,
            )

        voice = None
        if message.voice:
            voice = VoiceInput(
                file_id=message.voice.file_id,
                file_unique_id=message.voice.file_unique_id,
                duration=message.voice.duration,
                mime_type=message.voice.mime_type,
            )

        audio = None
        if message.audio:
            audio = AudioInput(
                file_id=message.audio.file_id,
                file_unique_id=message.audio.file_unique_id,
                duration=message.audio.duration,
                file_name=message.audio.file_name,
                mime_type=message.audio.mime_type,
            )

        video = None
        if message.video:
            video = VideoInput(
                file_id=message.video.file_id,
                file_unique_id=message.video.file_unique_id,
                width=message.video.width,
                height=message.video.height,
                duration=message.video.duration,
            )

        contact = None
        if message.contact:
            contact = ContactInput(
                phone_number=_safe_text(message.contact.phone_number),
                first_name=_safe_text(message.contact.first_name),
                last_name=_safe_text(message.contact.last_name) if message.contact.last_name else None,
                user_id=message.contact.user_id,
            )

        poll = None
        if message.poll:
            poll = PollInput(
                question=_safe_text(message.poll.question),
                options=[_safe_text(option.text) for option in message.poll.options],
                allows_multiple_answers=message.poll.allows_multiple_answers,
            )

        return MessageContext(
            chat_id=update.effective_chat.id,
            text=_safe_text(message.text or message.caption or ""),
            caption=_safe_text(message.caption) if message.caption else None,
            animation=animation,
            photos=photos,
            document=document,
            sticker=sticker,
            location=location,
            venue=venue,
            audio=audio,
            voice=voice,
            video=video,
            contact=contact,
            poll=poll,
            raw_update=update,
        )

    @staticmethod
    def _render_event(event: AppEvent) -> str:
        if event.type == "output":
            return event.text
        if event.type == "status":
            return f"[status] {event.text}"
        if event.type == "error":
            return f"[error] {event.text}"
        return f"[{event.type}] {event.text}"


import contextlib
