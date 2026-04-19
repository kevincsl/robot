from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from robot.agents import AgentCoordinator
from robot.config import load_settings
from robot.providers import RunningInvocation
from robot.state import ChatStateStore


class AgentAutomationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        (root / "README.md").write_text("# sample\n", encoding="utf-8")
        self.settings = load_settings(root)
        state_home = root / ".robot_state"
        state_home.mkdir(parents=True, exist_ok=True)
        object.__setattr__(self.settings, "state_home", state_home)
        object.__setattr__(self.settings, "session_state_path", state_home / "robot_state.json")
        self.store = ChatStateStore(self.settings)
        self.coordinator = AgentCoordinator(self.settings, self.store)
        self.events: list[tuple[int, str, str]] = []

        async def capture(chat_id: int, text: str, event_type: str = "output", raw=None, request_id=None) -> None:
            self.events.append((chat_id, event_type, text))

        self.coordinator._emit = capture  # type: ignore[method-assign]

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    async def test_schedule_alert_is_deduplicated_until_state_changes(self) -> None:
        chat_id = 1
        now = datetime(2026, 4, 12, 9, 0)

        next_schedule = {
            "status": "next",
            "title": "Morning Review",
            "date": "2026-04-12",
            "time": "09:40",
            "path": "06 Schedule/Morning Review.md",
            "minutes_until": "40",
        }
        ten_minute_schedule = {
            **next_schedule,
            "time": "09:10",
            "minutes_until": "10",
        }
        current_schedule = {
            **next_schedule,
            "status": "now",
            "time": "09:40",
            "minutes_until": "0",
        }

        with (
            patch("robot.agents.get_active_or_next_schedule", return_value=next_schedule),
            patch("robot.agents.build_schedule_alert", return_value="60m alert"),
        ):
            await self.coordinator._process_brain_automation(chat_id, now)
            await self.coordinator._process_brain_automation(chat_id, now)

        self.assertEqual(self.events, [(1, "output", "60m alert")])
        self.assertEqual(
            self.store.get_brain_automation(chat_id)["last_schedule_alert_key"],
            "60m|next|2026-04-12|09:40|06 Schedule/Morning Review.md|Morning Review",
        )

        with (
            patch("robot.agents.get_active_or_next_schedule", return_value=ten_minute_schedule),
            patch("robot.agents.build_schedule_alert", return_value="10m alert"),
        ):
            await self.coordinator._process_brain_automation(chat_id, datetime(2026, 4, 12, 9, 30))

        self.assertEqual(
            self.store.get_brain_automation(chat_id)["last_schedule_alert_key"],
            "10m|next|2026-04-12|09:10|06 Schedule/Morning Review.md|Morning Review",
        )

        with (
            patch("robot.agents.get_active_or_next_schedule", return_value=current_schedule),
            patch("robot.agents.build_schedule_alert", return_value="start alert"),
        ):
            await self.coordinator._process_brain_automation(chat_id, datetime(2026, 4, 12, 9, 40))

        self.assertEqual(
            self.events,
            [
                (1, "output", "60m alert"),
                (1, "output", "10m alert"),
                (1, "output", "start alert"),
            ],
        )

    async def test_schedule_alert_key_clears_when_no_schedule_matches(self) -> None:
        chat_id = 2
        self.store.update_brain_automation(chat_id, last_schedule_alert_key="10m|next|2026-04-12|09:05|path|Title")

        with patch("robot.agents.get_active_or_next_schedule", return_value=None):
            await self.coordinator._process_brain_automation(chat_id, datetime(2026, 4, 12, 11, 0))

        self.assertEqual(self.store.get_brain_automation(chat_id)["last_schedule_alert_key"], "")
        self.assertEqual(self.events, [])

    async def test_start_recovers_interrupted_current_run(self) -> None:
        chat_id = 3
        self.store.set_agent_current_run(
            chat_id,
            {
                "job_id": "job-42",
                "kind": "provider",
                "goal": "finish interrupted work",
                "project_name": "robot",
                "provider": "codex",
                "model": "gpt-5.4",
            },
        )

        with (
            patch.object(self.coordinator, "_scheduler_loop", new=AsyncMock(return_value=None)),
            patch.object(self.coordinator, "ensure_worker") as ensure_worker,
        ):
            self.coordinator.start()
            await asyncio.sleep(0)

        queue = self.store.get_agent_queue(chat_id)
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["job_id"], "job-42")
        self.assertTrue(queue[0]["recovered_after_restart"])
        self.assertIsNone(self.store.get_chat_state(chat_id)["agent_current_run"])
        ensure_worker.assert_called_once_with(chat_id)
        self.assertTrue(any("Recovered interrupted run after restart." in text for _, _, text in self.events))

    async def test_shutdown_clears_current_run_without_recovery_loop(self) -> None:
        chat_id = 4
        self.store.enqueue_agent_job(
            chat_id,
            {
                "job_id": "job-shutdown-1",
                "kind": "provider",
                "goal": "long running hello",
                "project_name": "robot",
                "project_path": str(self.settings.project_root),
                "provider": "codex",
                "model": "gpt-5.4",
                "thread_id": None,
                "source": "manual",
            },
        )

        async def fake_run_agent_request(*args, **kwargs):
            await asyncio.sleep(30)
            raise AssertionError("should be cancelled before completion")

        with patch("robot.agents.run_agent_request", side_effect=fake_run_agent_request):
            self.coordinator.ensure_worker(chat_id)
            await asyncio.sleep(0.05)
            current = self.store.get_chat_state(chat_id).get("agent_current_run")
            self.assertIsInstance(current, dict)

            await self.coordinator.shutdown()

        self.assertIsNone(self.store.get_chat_state(chat_id).get("agent_current_run"))
        self.assertIsNone(self.store.recover_agent_current_run(chat_id))

    async def test_queue_watchdog_emits_immediately_before_sleep(self) -> None:
        chat_id = 5
        self.store.enqueue_agent_job(
            chat_id,
            {
                "job_id": "job-queued-1",
                "kind": "provider",
                "goal": "inspect queue",
                "project_name": "robot",
                "project_display": "robot [fix]",
                "project_path": str(self.settings.project_root),
                "provider": "codex",
                "model": "gpt-5.4",
                "thread_id": None,
                "source": "manual",
            },
        )

        with patch("robot.agents.asyncio.sleep", new=AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await self.coordinator._queue_watchdog_loop(chat_id)

        self.assertEqual(len(self.events), 1)
        _chat_id, event_type, text = self.events[0]
        self.assertEqual(event_type, "status")
        self.assertIn("排隊中 ...", text)
        self.assertIn("elapsed: 00:00", text)

    async def test_heartbeat_loop_emits_immediately_before_sleep(self) -> None:
        chat_id = 6
        invocation = RunningInvocation()
        invocation.set_phase("agent: starting")
        job = {
            "kind": "provider",
            "goal": "inspect heartbeat",
            "project_name": "robot",
            "project_display": "robot [fix]",
            "project_path": str(self.settings.project_root),
        }

        with patch("robot.agents.asyncio.sleep", new=AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await self.coordinator._heartbeat_loop(chat_id, job, invocation)

        self.assertEqual(len(self.events), 1)
        _chat_id, event_type, text = self.events[0]
        self.assertEqual(event_type, "status")
        self.assertIn("執行中 ...", text)
        self.assertIn("phase: agent: starting", text)
        self.assertIn("elapsed: 00:00", text)


if __name__ == "__main__":
    unittest.main()
