from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from robot.agents import AgentCoordinator
from robot.config import load_settings
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

        async def capture(chat_id: int, text: str, event_type: str = "output", raw=None) -> None:
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


if __name__ == "__main__":
    unittest.main()
