from __future__ import annotations

import io
import json
import unittest.mock
import unittest
from contextlib import redirect_stdout
from unittest.mock import AsyncMock

from teleapp.protocol import AppEvent
from telegram.error import RetryAfter

from robot.hosted_app import _TypingController, _should_send_typing, _should_stop_typing, _emit_event


class HostedAppTests(unittest.TestCase):
    def test_emit_event_suppresses_noop(self) -> None:
        buffer = io.StringIO()
        event = AppEvent(
            type="noop",
            text="",
            chat_id=123,
            request_id="123-1",
            stream="inprocess",
            raw={},
        )

        with redirect_stdout(buffer):
            _emit_event(event)

        self.assertEqual(buffer.getvalue(), "")

    def test_emit_event_writes_normal_output(self) -> None:
        buffer = io.StringIO()
        event = AppEvent(
            type="output",
            text="hello",
            chat_id=123,
            request_id="123-1",
            stream="inprocess",
            raw={},
        )

        with redirect_stdout(buffer):
            _emit_event(event)

        written = buffer.getvalue().strip()
        self.assertTrue(written)
        payload = json.loads(written)
        self.assertEqual(payload["type"], "output")
        self.assertEqual(payload["text"], "hello")

    def test_emit_event_observes_typing_controller(self) -> None:
        buffer = io.StringIO()
        event = AppEvent(
            type="status",
            text="running",
            chat_id=123,
            request_id="123-1",
            stream="inprocess",
            raw={"status_key": "heartbeat:123-1", "replace": True, "typing": "active"},
        )
        controller = unittest.mock.Mock()

        with redirect_stdout(buffer):
            _emit_event(event, controller)

        controller.observe.assert_called_once_with(event)


class TypingControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = unittest.mock.Mock()
        self.client.enabled = True
        self.client.send = AsyncMock()
        self.client.close = AsyncMock()
        self.controller = _TypingController(self.client)

    def test_observe_start_stop_rules(self) -> None:
        start_event = AppEvent(
            type="status",
            text="queued",
            chat_id=7,
            request_id="req-1",
            stream="inprocess",
            raw={"status_key": "heartbeat:req-1", "replace": True, "typing": "active"},
        )
        stop_event = AppEvent(
            type="output",
            text="done",
            chat_id=7,
            request_id="req-1",
            stream="inprocess",
            raw={},
        )

        with (
            unittest.mock.patch.object(self.controller, "start") as mock_start,
            unittest.mock.patch.object(self.controller, "stop") as mock_stop,
        ):
            self.controller.observe(start_event)
            self.controller.observe(stop_event)

        mock_start.assert_called_once_with(7)
        mock_stop.assert_called_once_with(7)

    def test_observe_ignores_noop(self) -> None:
        noop_event = AppEvent(
            type="noop",
            text="",
            chat_id=7,
            request_id="req-1",
            stream="inprocess",
            raw={},
        )
        with unittest.mock.patch.object(self.controller, "stop") as mock_stop:
            self.controller.observe(noop_event)
        mock_stop.assert_not_called()

    def test_maybe_send_typing_action_is_throttled(self) -> None:
        import asyncio

        asyncio.run(self.controller.maybe_send(100, now=10.0))
        asyncio.run(self.controller.maybe_send(100, now=11.0))
        asyncio.run(self.controller.maybe_send(100, now=21.1))

        self.assertEqual(self.client.send.await_count, 2)
        self.assertEqual(self.client.send.await_args_list[0].args[0], 100)

    def test_maybe_send_typing_action_suppresses_send_errors(self) -> None:
        import asyncio

        self.client.send.side_effect = RuntimeError("boom")
        asyncio.run(self.controller.maybe_send(200, now=20.0))
        self.assertEqual(self.client.send.await_count, 1)

    def test_maybe_send_typing_action_applies_retry_after_backoff(self) -> None:
        import asyncio

        self.client.send.side_effect = RetryAfter(25)
        asyncio.run(self.controller.maybe_send(300, now=100.0))
        self.assertEqual(self.client.send.await_count, 1)
        asyncio.run(self.controller.maybe_send(300, now=101.0))
        self.assertEqual(self.client.send.await_count, 1)

    def test_typing_event_helpers_follow_status_and_output_rules(self) -> None:
        status_active = AppEvent(
            type="status",
            text="running",
            chat_id=1,
            request_id="r1",
            stream="inprocess",
            raw={"status_key": "heartbeat:r1", "replace": True, "typing": "active"},
        )
        status_stop = AppEvent(
            type="status",
            text="finished",
            chat_id=1,
            request_id="r1",
            stream="inprocess",
            raw={"status_key": "heartbeat:r1", "replace": True, "typing": "stop"},
        )
        output = AppEvent(
            type="output",
            text="done",
            chat_id=1,
            request_id="r1",
            stream="inprocess",
            raw={},
        )

        self.assertTrue(_should_send_typing(status_active))
        self.assertFalse(_should_send_typing(status_stop))
        self.assertTrue(_should_stop_typing(status_stop))
        self.assertTrue(_should_stop_typing(output))

    def test_typing_event_helpers_ignore_heartbeat_without_explicit_typing_state(self) -> None:
        heartbeat_only = AppEvent(
            type="status",
            text="heartbeat",
            chat_id=1,
            request_id="r1",
            stream="inprocess",
            raw={"status_key": "heartbeat:r1", "replace": True},
        )

        self.assertFalse(_should_send_typing(heartbeat_only))
        self.assertFalse(_should_stop_typing(heartbeat_only))


if __name__ == "__main__":
    unittest.main()
