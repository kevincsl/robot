from __future__ import annotations

import unittest
from argparse import Namespace
from pathlib import Path

from teleapp import (
    AnimationResponse,
    AudioResponse,
    Button,
    ButtonResponse,
    ContactResponse,
    DocumentResponse,
    ErrorResponse,
    LocationResponse,
    PhotoResponse,
    PollResponse,
    StatusResponse,
    StickerResponse,
    TeleApp,
    TextResponse,
    VenueResponse,
    VoiceResponse,
    build_runtime_config,
)
from teleapp.context import MessageContext
from teleapp.protocol import AppEvent, decode_output_line
from teleapp.supervisor import AppSupervisor


class DummyHandler:
    async def on_text(self, ctx):
        return f"handled: {ctx.text}"


class TeleAppTests(unittest.TestCase):
    def test_from_args_builds_runtime(self) -> None:
        app = TeleApp.from_args(
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
        self.assertEqual(app.config.allowed_user_id, 1)
        self.assertEqual(app.config.telegram_chat_id, 1)
        self.assertEqual(app.config.app_path.name, "echo_app.py")
        self.assertIsNotNone(app.gateway)
        self.assertIsNotNone(app.supervisor)

    def test_attach_callable_registers_inprocess_handler(self) -> None:
        app = TeleApp(build_runtime_config())

        async def handle(ctx):
            return f"echo: {ctx.text}"

        app.attach_callable(handle)
        self.assertIsNotNone(app.supervisor._callable_handler)

    def test_message_decorator_registers_handler(self) -> None:
        app = TeleApp(build_runtime_config())

        @app.message
        async def handle(ctx):
            return f"decorated: {ctx.text}"

        self.assertEqual(app._message_handler, handle)

    def test_attach_handler_registers_object_handler(self) -> None:
        app = TeleApp(build_runtime_config())
        handler = DummyHandler()
        app.attach_handler(handler)
        self.assertIs(app._message_handler, handler)

    def test_command_decorator_registers_command_handler(self) -> None:
        app = TeleApp(build_runtime_config())

        @app.command("/hello")
        async def hello(ctx):
            return f"hello {ctx.text}"

        self.assertIn("hello", app._command_handlers)
        self.assertEqual(app._command_handlers["hello"], hello)

    def test_message_handler_can_classify_unknown_command_text(self) -> None:
        app = TeleApp(build_runtime_config())

        @app.message
        async def handle(ctx):
            return f"command={ctx.command} text={ctx.text}"

        response = app._dispatch_context(MessageContext(chat_id=1, text="payload", command="model"))
        result = __import__("asyncio").run(response)
        self.assertEqual(result.text, "command=model text=payload")

    def test_route_decorator_registers_predicate_handler(self) -> None:
        app = TeleApp(build_runtime_config())

        @app.route(lambda ctx: ctx.text.startswith("ping"))
        async def handle(ctx):
            return "pong"

        self.assertEqual(len(app._routes), 1)
        predicate, handler = app._routes[0]
        self.assertTrue(predicate(type("Ctx", (), {"text": "ping now"})()))
        self.assertEqual(handler, handle)

    def test_supervisor_records_last_timing_on_completion(self) -> None:
        app = TeleApp(build_runtime_config())
        supervisor = AppSupervisor(app.config)
        now = __import__("datetime").datetime.now()
        supervisor._active_request = type(
            "Req",
            (),
            {
                "chat_id": 1,
                "request_id": "1-1",
                "text": "",
                "command": "menu",
                "queued_at": now,
                "dispatched_at": now,
                "first_event_at": None,
            },
        )()
        event = decode_output_line(
            '{"type":"buttons","text":"pick","chat_id":1,"request_id":"1-1","raw":{"buttons":[{"text":"A","data":"a"}]}}',
            stream="stdout",
        )
        assert event is not None
        __import__("asyncio").run(supervisor._complete_request(event))
        timing = supervisor.state.chat_sessions[1].last_timing
        self.assertEqual(timing["request_id"], "1-1")
        self.assertEqual(timing["event_type"], "buttons")

    def test_run_overrides_basic_config_fields(self) -> None:
        app = TeleApp(build_runtime_config())
        captured: dict[str, object] = {}

        def fake_run_polling():
            captured["token"] = app.config.telegram_token
            captured["allowed_user_id"] = app.config.allowed_user_id
            captured["chat_id"] = app.config.telegram_chat_id

        app.run_polling = fake_run_polling  # type: ignore[method-assign]
        app.run(token="abc", allowed_user_id=7, chat_id=8)
        self.assertEqual(captured["token"], "abc")
        self.assertEqual(captured["allowed_user_id"], 7)
        self.assertEqual(captured["chat_id"], 8)

    def test_hooks_are_registered(self) -> None:
        app = TeleApp(build_runtime_config())

        @app.before_message
        async def before(ctx):
            return None

        @app.after_message
        async def after(ctx, response):
            return None

        @app.on_error
        async def on_error(ctx, exc):
            return None

        @app.on_startup
        async def startup():
            return None

        @app.on_shutdown
        async def shutdown():
            return None

        self.assertEqual(len(app._before_message_hooks), 1)
        self.assertEqual(len(app._after_message_hooks), 1)
        self.assertEqual(len(app._error_hooks), 1)
        self.assertEqual(len(app._startup_hooks), 1)
        self.assertEqual(len(app._shutdown_hooks), 1)

    def test_response_classes_keep_text_and_type(self) -> None:
        self.assertEqual(TextResponse("ok").event_type, "output")
        self.assertEqual(StatusResponse("wait").event_type, "status")
        self.assertEqual(ErrorResponse("bad").event_type, "error")
        self.assertEqual(PhotoResponse(text="", file_id="file").event_type, "photo")
        self.assertEqual(DocumentResponse(text="", file_id="file").event_type, "document")
        self.assertEqual(LocationResponse(text="", latitude=1.0, longitude=2.0).event_type, "location")
        self.assertEqual(ButtonResponse(text="pick", buttons=[Button("A", "a")]).event_type, "buttons")
        self.assertEqual(AnimationResponse(text="", file_id="anim").event_type, "animation")
        self.assertEqual(AudioResponse(text="", file_id="audio").event_type, "audio")
        self.assertEqual(VoiceResponse(text="", file_id="voice").event_type, "voice")
        self.assertEqual(StickerResponse(sticker="sticker").event_type, "sticker")
        self.assertEqual(ContactResponse(text="", phone_number="123", first_name="A").event_type, "contact")
        self.assertEqual(PollResponse(text="", question="Q", options=["A", "B"]).event_type, "poll")
        self.assertEqual(VenueResponse(text="", latitude=1.0, longitude=2.0, title="T", address="A").event_type, "venue")

    def test_event_to_response_preserves_raw_metadata(self) -> None:
        app = TeleApp(build_runtime_config())
        ctx = MessageContext(chat_id=1, text="x")
        event = AppEvent(type="status", text="running", raw={"status_key": "heartbeat", "replace": True})
        response = app._event_to_response(event)
        roundtrip = response.to_event(ctx)
        self.assertEqual(roundtrip.raw["status_key"], "heartbeat")
        self.assertTrue(roundtrip.raw["replace"])


if __name__ == "__main__":
    unittest.main()
