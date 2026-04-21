from __future__ import annotations

import asyncio
import unittest
from argparse import Namespace
from datetime import datetime
from pathlib import Path

from teleapp import StatusResponse, TeleApp
from teleapp.config import load_config
from teleapp.protocol import AppEvent
from teleapp.supervisor import AppSupervisor


class SupervisorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.config = load_config(
            Namespace(
                app="examples/echo_app.py",
                token="dummy",
                allowed_user_id=1,
                chat_id=1,
                python_executable="python",
                no_hot_reload=True,
                no_auto_restart_on_crash=False,
                reload_quiet_seconds=2,
                reload_poll_seconds=1,
                restart_backoff_seconds=0,
                watch=[],
            )
        )

    async def test_busy_clears_after_response(self) -> None:
        supervisor = AppSupervisor(self.config)
        await supervisor.start()
        await supervisor.send_text(chat_id=1, text="hello")
        self.assertTrue(supervisor.state.busy)
        self.assertEqual(supervisor.state.active_chat_id, 1)
        event = await asyncio.wait_for(supervisor.next_event(), timeout=5)
        self.assertEqual(event.type, "output")
        self.assertFalse(supervisor.state.busy)
        self.assertEqual(supervisor.state.total_queued_requests, 0)
        await supervisor.stop()

    async def test_stale_exit_event_is_ignored(self) -> None:
        supervisor = AppSupervisor(self.config)
        await supervisor.start()
        assert supervisor._runner is not None
        current_pid = supervisor._runner.process.pid
        supervisor._runner.queue.put_nowait(
            AppEvent(
                type="status",
                text="Hosted app exited with code 0.",
                process_pid=current_pid + 1,
                stream="system",
            )
        )
        supervisor._runner.queue.put_nowait(
            AppEvent(
                type="output",
                text="ok",
                process_pid=current_pid,
                stream="stdout",
            )
        )
        event = await asyncio.wait_for(supervisor.next_event(), timeout=5)
        self.assertEqual(event.text, "ok")
        self.assertTrue(supervisor.state.running)
        await supervisor.stop()

    async def test_public_teleapp_facade_exposes_supervisor(self) -> None:
        app = TeleApp.from_config(self.config)
        self.assertIs(app.config, self.config)
        self.assertIsNotNone(app.gateway)
        self.assertIsNotNone(app.supervisor)

    async def test_inprocess_callable_handler_returns_output_event(self) -> None:
        app = TeleApp()

        @app.message
        async def handle(ctx):
            return f"inprocess: {ctx.text}"

        await app.supervisor.start()
        await app.supervisor.send_text(chat_id=11, text="hello")
        event = await asyncio.wait_for(app.supervisor.next_event(), timeout=5)
        self.assertEqual(event.type, "output")
        self.assertEqual(event.chat_id, 11)
        self.assertEqual(event.text, "inprocess: hello")
        await app.supervisor.stop()

    async def test_inprocess_command_handler_uses_command_name(self) -> None:
        app = TeleApp()

        @app.command("/hello")
        async def hello(ctx):
            return f"cmd={ctx.command} text={ctx.text}"

        await app.supervisor.start()
        await app.supervisor.send_text(chat_id=12, text="world", command="hello")
        event = await asyncio.wait_for(app.supervisor.next_event(), timeout=5)
        self.assertEqual(event.text, "cmd=hello text=world")
        await app.supervisor.stop()

    async def test_send_text_preserves_raw_payload_in_request(self) -> None:
        supervisor = AppSupervisor(self.config)
        await supervisor.start()
        await supervisor.send_text(
            chat_id=99,
            text="caption",
            raw={"document": {"file_id": "f1", "file_unique_id": "u1", "file_name": "a.pdf"}},
        )
        active = supervisor._active_request
        self.assertIsNotNone(active)
        assert active is not None
        self.assertIsInstance(active.raw, dict)
        self.assertEqual(active.raw["document"]["file_id"], "f1")
        await supervisor.stop()

    async def test_buttons_event_completes_active_request(self) -> None:
        supervisor = AppSupervisor(self.config)
        await supervisor.start()
        supervisor._active_request = type(
            "Req",
            (),
            {
                "chat_id": 1,
                "request_id": "1-1",
                "text": "",
                "command": "menu",
                "raw": None,
                "queued_at": datetime.now(),
                "dispatched_at": datetime.now(),
                "first_event_at": None,
            },
        )()
        await supervisor._complete_request(
            AppEvent(
                type="buttons",
                text="pick",
                chat_id=1,
                request_id="1-1",
                raw={"buttons": [{"text": "A", "data": "a"}]},
            )
        )
        self.assertIsNone(supervisor._active_request)
        await supervisor.stop()

    async def test_inprocess_route_handler_matches_before_default_handler(self) -> None:
        app = TeleApp()

        @app.route(lambda ctx: ctx.text.startswith("ping"))
        async def route_handler(ctx):
            return "pong"

        @app.message
        async def default_handler(ctx):
            return f"default: {ctx.text}"

        await app.supervisor.start()
        await app.supervisor.send_text(chat_id=13, text="ping now")
        event = await asyncio.wait_for(app.supervisor.next_event(), timeout=5)
        self.assertEqual(event.text, "pong")
        await app.supervisor.stop()

    async def test_before_after_and_error_hooks_run(self) -> None:
        app = TeleApp()
        calls: list[str] = []

        @app.before_message
        async def before(ctx):
            calls.append(f"before:{ctx.text}")

        @app.after_message
        async def after(ctx, response):
            calls.append(f"after:{response.text}")

        @app.on_error
        async def on_error(ctx, exc):
            calls.append(f"error:{exc}")

        @app.message
        async def handler(ctx):
            return StatusResponse("done")

        await app.supervisor.start()
        await app.supervisor.send_text(chat_id=14, text="hook-test")
        event = await asyncio.wait_for(app.supervisor.next_event(), timeout=5)
        self.assertEqual(event.type, "status")
        self.assertEqual(calls, ["before:hook-test", "after:done"])
        await app.supervisor.stop()

    async def test_requests_are_queued_per_chat(self) -> None:
        supervisor = AppSupervisor(self.config)
        await supervisor.start()
        await supervisor.send_text(chat_id=1, text="first")
        await supervisor.send_text(chat_id=2, text="second")
        self.assertEqual(supervisor.state.active_chat_id, 1)
        self.assertEqual(supervisor.state.total_queued_requests, 1)

        first_event = await asyncio.wait_for(supervisor.next_event(), timeout=5)
        self.assertEqual(first_event.chat_id, 1)
        self.assertEqual(supervisor.state.active_chat_id, 2)
        self.assertEqual(supervisor.state.total_queued_requests, 0)

        second_event = await asyncio.wait_for(supervisor.next_event(), timeout=5)
        self.assertEqual(second_event.chat_id, 2)
        self.assertFalse(supervisor.state.busy)
        await supervisor.stop()

    async def test_same_chat_requests_keep_order(self) -> None:
        supervisor = AppSupervisor(self.config)
        await supervisor.start()
        await supervisor.send_text(chat_id=1, text="first")
        await supervisor.send_text(chat_id=1, text="second")
        self.assertEqual(supervisor.state.active_chat_id, 1)
        self.assertEqual(supervisor.state.total_queued_requests, 1)

        first_event = await asyncio.wait_for(supervisor.next_event(), timeout=5)
        second_event = await asyncio.wait_for(supervisor.next_event(), timeout=5)
        self.assertEqual(first_event.text, "echo: first")
        self.assertEqual(second_event.text, "echo: second")
        self.assertFalse(supervisor.state.busy)
        await supervisor.stop()

    async def test_crash_auto_restart_restarts_process(self) -> None:
        supervisor = AppSupervisor(self.config)
        await supervisor.start()
        assert supervisor._runner is not None
        current_pid = supervisor._runner.process.pid
        supervisor._runner.queue.put_nowait(
            AppEvent(
                type="status",
                text="Hosted app exited with code 2.",
                process_pid=current_pid,
                stream="system",
                raw={"return_code": 2},
            )
        )
        event = await asyncio.wait_for(supervisor.next_event(), timeout=5)
        self.assertEqual(event.text, "Hosted app exited with code 2.")
        self.assertTrue(supervisor.state.running)
        self.assertIsNotNone(supervisor.state.pid)
        self.assertNotEqual(supervisor.state.pid, current_pid)
        self.assertEqual(supervisor.state.last_exit_code, 2)
        self.assertEqual(supervisor.state.last_restart_reason, "crash auto-restart (code 2)")
        await supervisor.stop()

    async def test_reload_is_deferred_until_active_request_completes(self) -> None:
        supervisor = AppSupervisor(self.config)
        await supervisor.start()
        await supervisor.send_text(chat_id=1, text="first")
        await supervisor.send_text(chat_id=2, text="second")
        await supervisor.restart("file changed: app.py")
        self.assertEqual(supervisor.state.last_restart_reason, "queued: file changed: app.py")

        first_event = await asyncio.wait_for(supervisor.next_event(), timeout=5)
        self.assertEqual(first_event.chat_id, 1)
        self.assertEqual(supervisor.state.last_restart_reason, "queued: file changed: app.py")

        second_event = await asyncio.wait_for(supervisor.next_event(), timeout=5)
        self.assertEqual(second_event.chat_id, 2)
        self.assertEqual(supervisor.state.last_restart_reason, "file changed: app.py")
        self.assertGreaterEqual(supervisor.state.restart_count, 1)
        await supervisor.stop()

    async def test_many_requests_remain_ordered_and_complete(self) -> None:
        supervisor = AppSupervisor(self.config)
        await supervisor.start()
        expected: list[tuple[int, str]] = []
        for index in range(20):
            chat_id = 1 if index % 2 == 0 else 2
            text = f"msg-{index}"
            expected.append((chat_id, f"echo: {text}"))
            await supervisor.send_text(chat_id=chat_id, text=text)

        seen: list[tuple[int, str]] = []
        for _ in range(20):
            event = await asyncio.wait_for(supervisor.next_event(), timeout=5)
            seen.append((event.chat_id, event.text))

        self.assertEqual(seen, expected)
        self.assertFalse(supervisor.state.busy)
        self.assertEqual(supervisor.state.total_queued_requests, 0)
        await supervisor.stop()


if __name__ == "__main__":
    unittest.main()
