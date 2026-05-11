from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from robot.agents import AgentCoordinator
from robot.config import load_settings
from robot.providers import AgentRunResult, RunningInvocation
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

    async def test_brain_automation_skips_when_vault_not_configured(self) -> None:
        chat_id = 22
        object.__setattr__(self.settings, "brain_vault_path", None)
        self.store.update_brain_automation(chat_id, enabled=True, daily_time="09:00")

        await self.coordinator._process_brain_automation(chat_id, datetime(2026, 4, 12, 9, 0))

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

    async def test_shutdown_swallows_completed_worker_exception(self) -> None:
        chat_id = 23

        async def boom() -> None:
            raise RuntimeError("worker failed")

        task = asyncio.create_task(boom())
        await asyncio.sleep(0)
        self.coordinator._worker_tasks[chat_id] = task

        await self.coordinator.shutdown()

        self.assertEqual(self.coordinator._worker_tasks, {})

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
        self.assertIn("Queue waiting.", text)
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
        self.assertIn("Heartbeat.", text)
        self.assertIn("phase: agent: starting", text)
        self.assertIn("elapsed: 00:00", text)

    async def test_emit_deduplicates_repeated_status_with_same_key_and_text(self) -> None:
        chat_id = 24
        queue = asyncio.Queue()
        self.coordinator.attach_supervisor(type("Supervisor", (), {"_event_queue": queue})())

        await AgentCoordinator._emit(
            self.coordinator,
            chat_id,
            "same status",
            event_type="status",
            raw={"status_key": "heartbeat:req-1", "replace": True},
            request_id="req-1",
        )
        await AgentCoordinator._emit(
            self.coordinator,
            chat_id,
            "same status",
            event_type="status",
            raw={"status_key": "heartbeat:req-1", "replace": True},
            request_id="req-1",
        )

        self.assertEqual(queue.qsize(), 1)
        event = queue.get_nowait()
        self.assertEqual(event.type, "status")
        self.assertEqual(event.text, "same status")

        await AgentCoordinator._emit(
            self.coordinator,
            chat_id,
            "done",
            event_type="output",
        )
        await AgentCoordinator._emit(
            self.coordinator,
            chat_id,
            "same status",
            event_type="status",
            raw={"status_key": "heartbeat:req-1", "replace": True},
            request_id="req-1",
        )

        self.assertEqual(queue.qsize(), 2)

    async def test_worker_converts_provider_exceptions_to_failed_output(self) -> None:
        chat_id = 8
        self.store.enqueue_agent_job(
            chat_id,
            {
                "job_id": "job-exception-1",
                "kind": "provider",
                "goal": "explode once",
                "project_name": "robot",
                "project_path": str(self.settings.project_root),
                "provider": "claude",
                "model": "claude-opus-4-7",
                "thread_id": None,
                "source": "manual",
            },
        )

        async def fake_run_agent_request(*args, **kwargs):
            raise RuntimeError("boom")

        with patch("robot.agents.run_agent_request", side_effect=fake_run_agent_request):
            self.coordinator.ensure_worker(chat_id)
            await asyncio.sleep(0.1)

        outputs = [text for event_chat_id, event_type, text in self.events if event_chat_id == chat_id and event_type == "output"]
        self.assertTrue(any("Agent run failed before execution completed." in text for text in outputs))
        state = self.store.get_chat_state(chat_id)
        self.assertIsNone(state["agent_current_run"])
        self.assertEqual(state["last_provider_timing"].get("return_code"), 1)
        self.assertFalse(self.coordinator._worker_tasks.get(chat_id, None) and not self.coordinator._worker_tasks[chat_id].done())

        chat_id = 7
        object.__setattr__(self.settings, "google_calendar_enabled", True)
        self.store.add_agent_schedule(
            chat_id,
            {
                "job_id": "job-1",
                "kind": "auto_dev",
                "goal": "sync schedule",
                "run_at": "2026-04-12T12:00",
            },
        )

        with patch(
            "robot.agents.sync_schedule_jobs_with_google",
            return_value=(
                [
                    {
                        "job_id": "job-1",
                        "kind": "auto_dev",
                        "goal": "sync schedule",
                        "run_at": "2026-04-12T12:00",
                        "gcal_event_id": "evt-1",
                    }
                ],
                {"mode": "both"},
            ),
        ) as mock_sync:
            await self.coordinator._maybe_sync_google_schedules(chat_id, datetime(2026, 4, 12, 9, 0))
            await self.coordinator._maybe_sync_google_schedules(chat_id, datetime(2026, 4, 12, 9, 4))
            await self.coordinator._maybe_sync_google_schedules(chat_id, datetime(2026, 4, 12, 9, 5))

        self.assertEqual(mock_sync.call_count, 2)
        first_call = mock_sync.call_args_list[0]
        self.assertEqual(first_call.kwargs["mode"], "both")
        self.assertEqual(first_call.kwargs["days"], 30)
        self.assertEqual(first_call.kwargs["limit"], 200)
        schedules = self.store.get_agent_schedules(chat_id)
        self.assertEqual(schedules[0].get("gcal_event_id"), "evt-1")

    async def test_google_schedule_sync_skips_when_disabled(self) -> None:
        chat_id = 8
        object.__setattr__(self.settings, "google_calendar_enabled", False)
        with patch("robot.agents.sync_schedule_jobs_with_google") as mock_sync:
            await self.coordinator._maybe_sync_google_schedules(chat_id, datetime(2026, 4, 12, 9, 0))
        mock_sync.assert_not_called()

    async def test_heartbeat_loop_emits_periodic_status_in_user_mode(self) -> None:
        chat_id = 16
        self.store.set_display_mode(chat_id, "user")
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
        self.assertEqual(self.events[0][1], "status")
        self.assertIn("專案[robot/fix]", self.events[0][2])

    async def test_worker_emits_user_mode_provider_output_summary(self) -> None:
        chat_id = 17
        self.store.set_display_mode(chat_id, "user")
        self.store.enqueue_agent_job(
            chat_id,
            {
                "job_id": "job-user-mode-1",
                "kind": "provider",
                "goal": "say hi",
                "project_name": "robot",
                "project_display": "robot [main]",
                "project_path": str(self.settings.project_root),
                "provider": "codex",
                "model": "gpt-5.4",
                "thread_id": None,
                "source": "manual",
                "request_id": "req-1",
                "status_key": "heartbeat:req-1",
            },
        )

        result = AgentRunResult(
            provider="codex",
            model="gpt-5.4",
            final_text="Hi\n\nproject: robot [main]\nprovider: codex\nmodel: gpt-5.4",
            thread_id="thread-1",
            return_code=0,
            elapsed_seconds=7,
            cancelled=False,
        )

        with patch("robot.agents.run_agent_request", new=AsyncMock(return_value=result)):
            self.coordinator.ensure_worker(chat_id)
            await asyncio.sleep(0.1)

        status_texts = [text for event_chat_id, event_type, text in self.events if event_chat_id == chat_id and event_type == "status"]
        output_texts = [text for event_chat_id, event_type, text in self.events if event_chat_id == chat_id and event_type == "output"]
        self.assertTrue(any("📨 專案[robot/main] 已接收" in text for text in status_texts))
        self.assertIn("✅ 專案[robot/main] 處理完成 · 7s\n\nHi\n\n🚀 gpt-5.4", output_texts)
        self.assertFalse(any("provider: codex" in text for text in output_texts))

    async def test_worker_user_mode_deduplicates_existing_model_footer(self) -> None:
        chat_id = 18
        self.store.set_display_mode(chat_id, "user")
        self.store.enqueue_agent_job(
            chat_id,
            {
                "job_id": "job-user-mode-2",
                "kind": "provider",
                "goal": "say hi twice",
                "project_name": "robot",
                "project_display": "robot [main]",
                "project_path": str(self.settings.project_root),
                "provider": "codex",
                "model": "gpt-5.4",
                "thread_id": None,
                "source": "manual",
                "request_id": "req-2",
                "status_key": "heartbeat:req-2",
            },
        )

        result = AgentRunResult(
            provider="codex",
            model="gpt-5.4",
            final_text="Hi\n\nproject: robot [main]\nprovider: codex\nmodel: gpt-5.4\n回覆來自 model: gpt-5.4",
            thread_id="thread-2",
            return_code=0,
            elapsed_seconds=2,
            cancelled=False,
        )

        with patch("robot.agents.run_agent_request", new=AsyncMock(return_value=result)):
            self.coordinator.ensure_worker(chat_id)
            await asyncio.sleep(0.1)

        output_texts = [text for event_chat_id, event_type, text in self.events if event_chat_id == chat_id and event_type == "output"]
        self.assertEqual(
            output_texts[-1],
            "✅ 專案[robot/main] 處理完成 · 2s\n\nHi\n\n🚀 gpt-5.4",
        )

    async def test_worker_user_mode_unwraps_existing_completion_wrapper(self) -> None:
        chat_id = 19
        self.store.set_display_mode(chat_id, "user")
        self.store.enqueue_agent_job(
            chat_id,
            {
                "job_id": "job-user-mode-3",
                "kind": "provider",
                "goal": "say hi wrapped",
                "project_name": "robot",
                "project_display": "robot [main]",
                "project_path": str(self.settings.project_root),
                "provider": "codex",
                "model": "gpt-5.4",
                "thread_id": None,
                "source": "manual",
                "request_id": "req-3",
                "status_key": "heartbeat:req-3",
            },
        )

        result = AgentRunResult(
            provider="codex",
            model="gpt-5.4",
            final_text=(
                "專案[robot/main] 處理完成\n"
                "total_elapsed: 0s\n\n"
                "hello.\n\n"
                "回覆來自 model: gpt-5.4"
            ),
            thread_id="thread-3",
            return_code=0,
            elapsed_seconds=23,
            cancelled=False,
        )

        with patch("robot.agents.run_agent_request", new=AsyncMock(return_value=result)):
            self.coordinator.ensure_worker(chat_id)
            await asyncio.sleep(0.1)

        output_texts = [text for event_chat_id, event_type, text in self.events if event_chat_id == chat_id and event_type == "output"]
        self.assertEqual(
            output_texts[-1],
            "✅ 專案[robot/main] 處理完成 · 23s\n\nhello.\n\n🚀 gpt-5.4",
        )

    async def test_worker_user_mode_unwraps_wrapper_and_strips_duplicate_model_footer(self) -> None:
        chat_id = 20
        self.store.set_display_mode(chat_id, "user")
        self.store.enqueue_agent_job(
            chat_id,
            {
                "job_id": "job-user-mode-4",
                "kind": "provider",
                "goal": "say hi wrapped twice",
                "project_name": "robot",
                "project_display": "robot [main]",
                "project_path": str(self.settings.project_root),
                "provider": "codex",
                "model": "gpt-5.4",
                "thread_id": None,
                "source": "manual",
                "request_id": "req-4",
                "status_key": "heartbeat:req-4",
            },
        )

        result = AgentRunResult(
            provider="codex",
            model="gpt-5.4",
            final_text=(
                "專案[robot/main] 處理完成\n"
                "total_elapsed: 0s\n\n"
                "hello.\n\n"
                "回覆來自 model: gpt-5.4\n\n"
                "回覆來自 model: gpt-5.4"
            ),
            thread_id="thread-4",
            return_code=0,
            elapsed_seconds=23,
            cancelled=False,
        )

        with patch("robot.agents.run_agent_request", new=AsyncMock(return_value=result)):
            self.coordinator.ensure_worker(chat_id)
            await asyncio.sleep(0.1)

        output_texts = [text for event_chat_id, event_type, text in self.events if event_chat_id == chat_id and event_type == "output"]
        self.assertEqual(
            output_texts[-1],
            "✅ 專案[robot/main] 處理完成 · 23s\n\nhello.\n\n🚀 gpt-5.4",
        )

    async def test_worker_user_mode_strips_duplicate_model_footer_without_wrapper(self) -> None:
        chat_id = 21
        self.store.set_display_mode(chat_id, "user")
        self.store.enqueue_agent_job(
            chat_id,
            {
                "job_id": "job-user-mode-5",
                "kind": "provider",
                "goal": "say hello duplicate footer",
                "project_name": "robot",
                "project_display": "robot [main]",
                "project_path": str(self.settings.project_root),
                "provider": "codex",
                "model": "gpt-5.4",
                "thread_id": None,
                "source": "manual",
                "request_id": "req-5",
                "status_key": "heartbeat:req-5",
            },
        )

        result = AgentRunResult(
            provider="codex",
            model="gpt-5.4",
            final_text=(
                "hello.\n\n"
                "回覆來自 model: gpt-5.4\n\n"
                "回覆來自 model: gpt-5.4"
            ),
            thread_id="thread-5",
            return_code=0,
            elapsed_seconds=29,
            cancelled=False,
        )

        with patch("robot.agents.run_agent_request", new=AsyncMock(return_value=result)):
            self.coordinator.ensure_worker(chat_id)
            await asyncio.sleep(0.1)

        output_texts = [text for event_chat_id, event_type, text in self.events if event_chat_id == chat_id and event_type == "output"]
        self.assertEqual(
            output_texts[-1],
            "✅ 專案[robot/main] 處理完成 · 29s\n\nhello.\n\n🚀 gpt-5.4",
        )

    async def test_enqueue_deduplicates_same_request_id(self) -> None:
        chat_id = 19
        job1, pos1, started1 = self.coordinator.enqueue(
            chat_id,
            "hello once",
            source="message",
            request_id="req-dup-1",
            status_key="heartbeat:req-dup-1",
        )
        job2, pos2, started2 = self.coordinator.enqueue(
            chat_id,
            "hello again",
            source="message",
            request_id="req-dup-1",
            status_key="heartbeat:req-dup-1",
        )

        queue = self.store.get_agent_queue(chat_id)
        self.assertEqual(len(queue), 1)
        self.assertEqual(job1, job2)
        self.assertEqual(pos1, 1)
        self.assertEqual(pos2, 1)
        self.assertTrue(started1)
        self.assertFalse(started2)
        await self.coordinator.shutdown()
