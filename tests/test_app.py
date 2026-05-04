from __future__ import annotations

import asyncio
import os
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock

from telegram.error import RetryAfter

from teleapp.protocol import AppEvent

from robot import app as robot_app


class AppTypingTests(unittest.TestCase):
    def setUp(self) -> None:
        robot_app._LAST_TYPING_SENT_AT.clear()
        robot_app._TYPING_BACKOFF_UNTIL.clear()
        for chat_id in list(robot_app._TYPING_TASKS.keys()):
            robot_app._stop_typing(chat_id)

    def test_should_not_send_typing_for_heartbeat_status_without_explicit_typing(self) -> None:
        event = AppEvent(
            type="status",
            text="running",
            chat_id=1,
            request_id="r1",
            stream="inprocess",
            raw={"status_key": "heartbeat:r1", "replace": True},
        )
        self.assertFalse(robot_app._should_send_typing(event))

    def test_should_send_typing_for_explicit_active_status(self) -> None:
        event = AppEvent(
            type="status",
            text="running",
            chat_id=1,
            request_id="r1",
            stream="inprocess",
            raw={"status_key": "done:r1", "replace": True, "typing": "active"},
        )
        self.assertTrue(robot_app._should_send_typing(event))

    def test_should_not_send_typing_for_non_heartbeat_status(self) -> None:
        event = AppEvent(
            type="status",
            text="boot",
            chat_id=1,
            request_id=None,
            stream="inprocess",
            raw={"status_key": "boot", "replace": True},
        )
        self.assertFalse(robot_app._should_send_typing(event))

    def test_should_not_send_typing_for_explicit_stop_status(self) -> None:
        event = AppEvent(
            type="status",
            text="finished",
            chat_id=1,
            request_id="r1",
            stream="inprocess",
            raw={"status_key": "heartbeat:r1", "replace": True, "typing": "stop"},
        )
        self.assertFalse(robot_app._should_send_typing(event))

    def test_should_not_send_typing_for_non_status_event(self) -> None:
        event = AppEvent(
            type="output",
            text="done",
            chat_id=1,
            request_id=None,
            stream="inprocess",
            raw={},
        )
        self.assertFalse(robot_app._should_send_typing(event))

    def test_should_not_stop_typing_for_status_without_explicit_typing(self) -> None:
        event = AppEvent(
            type="status",
            text="finished",
            chat_id=1,
            request_id="r1",
            stream="inprocess",
            raw={"status_key": "boot", "replace": True},
        )
        self.assertFalse(robot_app._should_stop_typing(event))

    def test_should_stop_typing_for_explicit_stop_status(self) -> None:
        event = AppEvent(
            type="status",
            text="finished",
            chat_id=1,
            request_id="r1",
            stream="inprocess",
            raw={"status_key": "heartbeat:r1", "replace": True, "typing": "stop"},
        )
        self.assertTrue(robot_app._should_stop_typing(event))

    def test_should_stop_typing_for_output_event(self) -> None:
        event = AppEvent(
            type="output",
            text="done",
            chat_id=1,
            request_id="r1",
            stream="inprocess",
            raw={},
        )
        self.assertTrue(robot_app._should_stop_typing(event))

    def test_should_not_stop_typing_for_noop_event(self) -> None:
        event = AppEvent(
            type="noop",
            text="",
            chat_id=1,
            request_id="r1",
            stream="inprocess",
            raw={},
        )
        self.assertFalse(robot_app._should_stop_typing(event))

    def test_maybe_send_typing_action_is_throttled(self) -> None:
        bot = type("Bot", (), {"send_chat_action": AsyncMock()})()
        asyncio.run(robot_app._maybe_send_typing_action(bot, 100, now=10.0))
        asyncio.run(robot_app._maybe_send_typing_action(bot, 100, now=11.0))
        asyncio.run(robot_app._maybe_send_typing_action(bot, 100, now=21.1))

        self.assertEqual(bot.send_chat_action.await_count, 2)
        self.assertEqual(bot.send_chat_action.await_args_list[0].kwargs["chat_id"], 100)
        self.assertEqual(bot.send_chat_action.await_args_list[0].kwargs["action"], "typing")

    def test_maybe_send_typing_action_suppresses_send_errors(self) -> None:
        bot = type("Bot", (), {"send_chat_action": AsyncMock(side_effect=RuntimeError("boom"))})()
        asyncio.run(robot_app._maybe_send_typing_action(bot, 200, now=20.0))
        self.assertEqual(bot.send_chat_action.await_count, 1)
        self.assertEqual(robot_app._LAST_TYPING_SENT_AT.get(200), 20.0)
        self.assertEqual(robot_app._TYPING_BACKOFF_UNTIL.get(200), 30.0)

    def test_maybe_send_typing_action_applies_retry_after_backoff(self) -> None:
        bot = type("Bot", (), {"send_chat_action": AsyncMock(side_effect=RetryAfter(25))})()
        asyncio.run(robot_app._maybe_send_typing_action(bot, 300, now=100.0))
        self.assertEqual(bot.send_chat_action.await_count, 1)
        self.assertEqual(robot_app._TYPING_BACKOFF_UNTIL.get(300), 130.0)

    def test_maybe_send_typing_action_accepts_timedelta_retry_after(self) -> None:
        bot = type("Bot", (), {"send_chat_action": AsyncMock(side_effect=RetryAfter(timedelta(seconds=2)))})()
        asyncio.run(robot_app._maybe_send_typing_action(bot, 301, now=100.0))
        self.assertEqual(bot.send_chat_action.await_count, 1)
        self.assertEqual(robot_app._TYPING_BACKOFF_UNTIL.get(301), 130.0)

    def test_maybe_send_typing_action_skips_during_backoff(self) -> None:
        bot = type("Bot", (), {"send_chat_action": AsyncMock()})()
        robot_app._TYPING_BACKOFF_UNTIL[400] = 55.0
        asyncio.run(robot_app._maybe_send_typing_action(bot, 400, now=50.0))
        self.assertEqual(bot.send_chat_action.await_count, 0)

    def test_start_typing_is_idempotent(self) -> None:
        bot = type("Bot", (), {"send_chat_action": AsyncMock()})()
        with unittest.mock.patch("robot.app.asyncio.create_task") as create_task:
            task = unittest.mock.Mock()
            task.done.return_value = False
            create_task.return_value = task
            robot_app._start_typing(bot, 501)
            robot_app._start_typing(bot, 501)
            typing_coro = create_task.call_args_list[0].args[0]
            typing_coro.close()

        self.assertEqual(create_task.call_count, 1)
        self.assertIn(501, robot_app._TYPING_TASKS)

    def test_stop_typing_cancels_task(self) -> None:
        task = unittest.mock.Mock()
        robot_app._TYPING_TASKS[777] = task
        robot_app._stop_typing(777)
        task.cancel.assert_called_once()
        self.assertNotIn(777, robot_app._TYPING_TASKS)

    def test_typing_min_interval_default_and_clamp(self) -> None:
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(robot_app._typing_min_interval_seconds(), 4.0)
        with unittest.mock.patch.dict(os.environ, {"ROBOT_TYPING_INTERVAL_SECONDS": "2"}, clear=True):
            self.assertEqual(robot_app._typing_min_interval_seconds(), 3.0)
        with unittest.mock.patch.dict(os.environ, {"ROBOT_TYPING_INTERVAL_SECONDS": "4.5"}, clear=True):
            self.assertEqual(robot_app._typing_min_interval_seconds(), 4.5)
        with unittest.mock.patch.dict(os.environ, {"ROBOT_TYPING_INTERVAL_SECONDS": "100"}, clear=True):
            self.assertEqual(robot_app._typing_min_interval_seconds(), 60.0)
        with unittest.mock.patch.dict(os.environ, {"ROBOT_TYPING_INTERVAL_SECONDS": "abc"}, clear=True):
            self.assertEqual(robot_app._typing_min_interval_seconds(), 4.0)


class AppGatewayPatchTests(unittest.TestCase):
    def test_status_render_no_longer_adds_status_prefix(self) -> None:
        event = AppEvent(type="status", text="📨 專案[robot/main] 已接收", chat_id=1, request_id="r1", raw={})
        rendered = robot_app.TelegramGateway._render_event(event)
        self.assertEqual(rendered, "📨 專案[robot/main] 已接收")

    def test_error_render_no_longer_adds_error_prefix(self) -> None:
        event = AppEvent(type="error", text="boom", chat_id=1, request_id="r1", raw={})
        rendered = robot_app.TelegramGateway._render_event(event)
        self.assertEqual(rendered, "boom")


if __name__ == "__main__":
    unittest.main()


