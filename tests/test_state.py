from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from robot.config import load_settings
from robot.state import ChatStateStore


class StateTests(unittest.TestCase):
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

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_default_state_uses_defaults(self) -> None:
        state = self.store.get_chat_state(42)
        self.assertEqual(state["provider"], self.settings.default_provider)
        self.assertTrue(state["project_path"])

    def test_provider_keeps_separate_thread_ids(self) -> None:
        self.store.set_thread_id(1, "codex", "codex-thread")
        self.store.set_provider(1, "gemini")
        self.store.set_thread_id(1, "gemini", "gemini-thread")
        self.store.set_provider(1, "codex")
        self.assertEqual(self.store.get_chat_state(1)["thread_id"], "codex-thread")
        self.store.set_provider(1, "gemini")
        self.assertEqual(self.store.get_chat_state(1)["thread_id"], "gemini-thread")

    def test_brain_automation_defaults_exist(self) -> None:
        automation = self.store.get_brain_automation(1)
        self.assertTrue(automation["enabled"])
        self.assertEqual(automation["daily_time"], "21:00")
        self.assertEqual(automation["weekly_day"], 0)
        self.assertEqual(automation["weekly_time"], "09:00")
        self.assertEqual(automation["last_schedule_alert_key"], "")
        self.assertEqual(automation["schedule_alert_window_minutes"], 60)

    def test_brain_automation_can_be_updated(self) -> None:
        automation = self.store.update_brain_automation(1, enabled=False, daily_time="22:30")
        self.assertFalse(automation["enabled"])
        self.assertEqual(automation["daily_time"], "22:30")

    def test_last_schedule_results_round_trip(self) -> None:
        results = [{"title": "會議", "date": "2026-04-20", "time": "13:00"}]
        self.store.set_last_schedule_results(1, results)

        self.assertEqual(self.store.get_last_schedule_results(1), results)
        self.store.clear_last_schedule_results(1)
        self.assertEqual(self.store.get_last_schedule_results(1), [])

    def test_recover_agent_current_run_moves_job_back_to_queue(self) -> None:
        self.store.set_agent_current_run(
            1,
            {
                "job_id": "job-1",
                "kind": "provider",
                "goal": "continue working",
                "project_name": "robot",
            },
        )

        recovered = self.store.recover_agent_current_run(1)

        self.assertIsNotNone(recovered)
        assert recovered is not None
        self.assertEqual(recovered["job_id"], "job-1")
        self.assertEqual(self.store.get_chat_state(1)["agent_current_run"], None)
        queue = self.store.get_agent_queue(1)
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["job_id"], "job-1")
        self.assertTrue(queue[0]["recovered_after_restart"])

    def test_last_provider_timing_round_trip(self) -> None:
        timing = {"job_id": "job-1", "elapsed_seconds": 9, "return_code": 0}
        self.store.set_last_provider_timing(1, timing)

        state = self.store.get_chat_state(1)
        self.assertEqual(state["last_provider_timing"], timing)


if __name__ == "__main__":
    unittest.main()
