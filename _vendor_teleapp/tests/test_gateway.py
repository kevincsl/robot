from __future__ import annotations

import unittest
from argparse import Namespace
from types import SimpleNamespace

from teleapp.config import load_config
from teleapp.context import AnimationInput, AudioInput, DocumentInput, LocationInput, PhotoInput, StickerInput, VenueInput, VoiceInput
from teleapp.protocol import AppEvent
from teleapp.state import ChatSessionState
from teleapp.telegram_gateway import TelegramGateway


class DummyMessage:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.sent.append(text)


class DummyBot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def send_message(self, **kwargs):
        self.calls.append(("message", kwargs))
        return SimpleNamespace(message_id=999)

    async def edit_message_text(self, **kwargs):
        self.calls.append(("edit_message_text", kwargs))

    async def send_photo(self, **kwargs):
        self.calls.append(("photo", kwargs))

    async def send_animation(self, **kwargs):
        self.calls.append(("animation", kwargs))

    async def send_document(self, **kwargs):
        self.calls.append(("document", kwargs))

    async def send_sticker(self, **kwargs):
        self.calls.append(("sticker", kwargs))

    async def send_location(self, **kwargs):
        self.calls.append(("location", kwargs))

    async def send_venue(self, **kwargs):
        self.calls.append(("venue", kwargs))

    async def send_audio(self, **kwargs):
        self.calls.append(("audio", kwargs))

    async def send_voice(self, **kwargs):
        self.calls.append(("voice", kwargs))

    async def send_video(self, **kwargs):
        self.calls.append(("video", kwargs))

    async def send_contact(self, **kwargs):
        self.calls.append(("contact", kwargs))

    async def send_poll(self, **kwargs):
        self.calls.append(("poll", kwargs))


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.config = load_config(
            Namespace(
                app="examples/echo_app.py",
                token="dummy",
                allowed_user_id=1,
                chat_id=1,
                python_executable="python",
                no_hot_reload=True,
                reload_quiet_seconds=2,
                reload_poll_seconds=1,
                watch=[],
            )
        )

    def test_render_event_formats_known_types(self) -> None:
        self.assertEqual(TelegramGateway._render_event(AppEvent(type="output", text="ok")), "ok")
        self.assertEqual(TelegramGateway._render_event(AppEvent(type="status", text="up")), "up")
        self.assertEqual(TelegramGateway._render_event(AppEvent(type="error", text="bad")), "[error] bad")

    def test_build_command_menu_keeps_fixed_entries(self) -> None:
        gateway = TelegramGateway(self.config)
        gateway.set_custom_commands({"foo", "status", "model"})
        names = [item.command for item in gateway._build_command_menu()]
        self.assertEqual(
            names[:9],
            ["start", "help", "status", "restart", "menu", "brain", "schedules", "panic", "reset"],
        )
        self.assertIn("foo", names)
        self.assertEqual(names.count("status"), 1)
        self.assertEqual(names.count("foo"), 1)

    async def test_start_command_shows_runtime_entrypoints(self) -> None:
        gateway = TelegramGateway(self.config)
        message = DummyMessage()
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=1),
            message=message,
        )

        await gateway._start_command(update, None)
        self.assertEqual(len(message.sent), 1)
        body = message.sent[0]
        self.assertIn("teleapp", body)
        self.assertIn("/status", body)
        self.assertIn("/restart", body)

    async def test_status_command_includes_queue_summary(self) -> None:
        gateway = TelegramGateway(self.config)
        state = gateway.supervisor.state
        state.running = True
        state.pid = 321
        state.busy = True
        state.active_chat_id = 7
        state.active_request_id = "7-1"
        state.total_queued_requests = 2
        state.last_restart_reason = "queued: file changed"
        state.last_error = "none"
        state.chat_sessions[7] = ChatSessionState(chat_id=7, queued_requests=1, active_request_id="7-1")
        state.chat_sessions[8] = ChatSessionState(chat_id=8, queued_requests=1, active_request_id=None)
        state.chat_sessions[8].last_timing = {
            "request_id": "8-3",
            "queued_ms": 12,
            "first_event_ms": 55,
            "total_ms": 78,
            "event_type": "output",
        }

        message = DummyMessage()
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=1),
            effective_chat=SimpleNamespace(id=1),
            message=message,
        )

        await gateway._status_command(update, None)
        self.assertEqual(len(message.sent), 1)
        body = message.sent[0]
        self.assertIn("running: yes", body)
        self.assertIn("active_chat_id: 7", body)
        self.assertIn("queued_requests: 2", body)
        self.assertIn("chat 7: queued=1 active=7-1", body)
        self.assertIn("chat 8: queued=1 active=-", body)
        self.assertIn("last_timing: request_id=8-3 queued_ms=12 first_event_ms=55 total_ms=78 event=output", body)

    def test_build_message_context_extracts_media_shapes(self) -> None:
        photo = SimpleNamespace(file_id="p1", file_unique_id="up1", width=100, height=200)
        animation = SimpleNamespace(file_id="an1", file_unique_id="uan1", width=120, height=90, duration=2, file_name="demo.gif", mime_type="image/gif")
        document = SimpleNamespace(file_id="d1", file_unique_id="ud1", file_name="a.txt", mime_type="text/plain")
        sticker = SimpleNamespace(file_id="s1", file_unique_id="us1", emoji="smile", set_name="demo")
        location = SimpleNamespace(latitude=25.0, longitude=121.0)
        venue = SimpleNamespace(location=SimpleNamespace(latitude=25.1, longitude=121.5), title="Place", address="Addr")
        voice = SimpleNamespace(file_id="v1", file_unique_id="uv1", duration=3, mime_type="audio/ogg")
        audio = SimpleNamespace(file_id="a1", file_unique_id="ua1", duration=8, file_name="demo.mp3", mime_type="audio/mpeg")
        video = SimpleNamespace(file_id="vid1", file_unique_id="uvid1", width=320, height=240, duration=6)
        contact = SimpleNamespace(phone_number="123", first_name="Kevin", last_name="Lin", user_id=1)
        poll = SimpleNamespace(
            question="Q?",
            options=[SimpleNamespace(text="A"), SimpleNamespace(text="B")],
            allows_multiple_answers=False,
        )
        message = SimpleNamespace(
            text=None,
            caption="cap",
            photo=[photo],
            animation=animation,
            document=document,
            sticker=sticker,
            location=location,
            venue=venue,
            voice=voice,
            audio=audio,
            video=video,
            contact=contact,
            poll=poll,
        )
        update = SimpleNamespace(effective_chat=SimpleNamespace(id=99), message=message)
        ctx = TelegramGateway._build_message_context(update)
        self.assertEqual(ctx.chat_id, 99)
        self.assertEqual(ctx.text, "cap")
        self.assertEqual(ctx.caption, "cap")
        self.assertIsInstance(ctx.photos[0], PhotoInput)
        self.assertIsInstance(ctx.animation, AnimationInput)
        self.assertIsInstance(ctx.document, DocumentInput)
        self.assertIsInstance(ctx.sticker, StickerInput)
        self.assertIsInstance(ctx.location, LocationInput)
        self.assertIsInstance(ctx.venue, VenueInput)
        self.assertIsInstance(ctx.voice, VoiceInput)
        self.assertIsInstance(ctx.audio, AudioInput)
        self.assertEqual(ctx.video.file_id, "vid1")
        self.assertEqual(ctx.contact.phone_number, "123")
        self.assertEqual(ctx.poll.question, "Q?")

    async def test_send_event_routes_media_outputs(self) -> None:
        gateway = TelegramGateway(self.config)
        app = SimpleNamespace(bot=DummyBot())

        await gateway._send_event(
            app,
            1,
            AppEvent(type="location", text="", raw={"latitude": 1.0, "longitude": 2.0}),
        )
        await gateway._send_event(
            app,
            1,
            AppEvent(type="venue", text="", raw={"latitude": 1.0, "longitude": 2.0, "title": "Place", "address": "Addr"}),
        )
        await gateway._send_event(
            app,
            1,
            AppEvent(type="sticker", text="", raw={"sticker": "sticker-file-id"}),
        )
        await gateway._send_event(
            app,
            1,
            AppEvent(type="buttons", text="pick", raw={"buttons": [{"text": "A", "data": "a"}]}),
        )
        await gateway._send_event(
            app,
            1,
            AppEvent(type="audio", text="", raw={"file_id": "audio-file-id", "caption": "audio"}),
        )
        await gateway._send_event(
            app,
            1,
            AppEvent(type="animation", text="", raw={"file_id": "animation-file-id", "caption": "anim"}),
        )
        await gateway._send_event(
            app,
            1,
            AppEvent(type="voice", text="", raw={"file_id": "voice-file-id", "caption": "voice"}),
        )
        await gateway._send_event(
            app,
            1,
            AppEvent(type="video", text="", raw={"file_id": "video-file-id", "caption": "video"}),
        )
        await gateway._send_event(
            app,
            1,
            AppEvent(type="contact", text="", raw={"phone_number": "123", "first_name": "Kevin", "last_name": "Lin"}),
        )
        await gateway._send_event(
            app,
            1,
            AppEvent(type="poll", text="", raw={"question": "Q?", "options": ["A", "B"], "allows_multiple_answers": False}),
        )

        self.assertEqual(app.bot.calls[0][0], "location")
        self.assertEqual(app.bot.calls[1][0], "venue")
        self.assertEqual(app.bot.calls[2][0], "sticker")
        self.assertEqual(app.bot.calls[3][0], "message")
        self.assertEqual(app.bot.calls[4][0], "audio")
        self.assertEqual(app.bot.calls[5][0], "animation")
        self.assertEqual(app.bot.calls[6][0], "voice")
        self.assertEqual(app.bot.calls[7][0], "video")
        self.assertEqual(app.bot.calls[8][0], "contact")
        self.assertEqual(app.bot.calls[9][0], "poll")

    async def test_status_event_reuses_existing_message_when_replace_is_enabled(self) -> None:
        gateway = TelegramGateway(self.config)
        app = SimpleNamespace(bot=DummyBot())
        session = gateway.supervisor.state.chat_sessions.setdefault(1, ChatSessionState(chat_id=1))
        session.status_messages["heartbeat"] = 321

        await gateway._send_event(
            app,
            1,
            AppEvent(type="status", text="updated", raw={"status_key": "heartbeat", "replace": True}),
        )

        self.assertEqual(app.bot.calls[0][0], "edit_message_text")
        self.assertEqual(app.bot.calls[0][1]["chat_id"], 1)
        self.assertEqual(app.bot.calls[0][1]["message_id"], 321)

    async def test_raw_buttons_force_keyboard_even_if_type_is_output(self) -> None:
        gateway = TelegramGateway(self.config)
        app = SimpleNamespace(bot=DummyBot())

        await gateway._send_event(
            app,
            1,
            AppEvent(type="output", text="menu", raw={"buttons": [{"text": "A", "data": "a"}]}),
        )

        self.assertEqual(app.bot.calls[0][0], "message")
        self.assertNotIn("reply_markup", app.bot.calls[0][1])


if __name__ == "__main__":
    unittest.main()
