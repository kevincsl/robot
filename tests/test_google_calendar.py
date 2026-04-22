from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from robot.config import load_settings
from robot.google_calendar import GoogleCalendarDependencyError, google_calendar_status_text, google_calendar_upcoming_text


class GoogleCalendarModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        (root / "README.md").write_text("# robot\n", encoding="utf-8")
        self.settings = load_settings(root)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_status_reports_disabled_when_feature_flag_off(self) -> None:
        object.__setattr__(self.settings, "google_calendar_enabled", False)
        body = google_calendar_status_text(self.settings)
        self.assertIn("state: disabled", body)

    def test_status_reports_missing_dependencies(self) -> None:
        object.__setattr__(self.settings, "google_calendar_enabled", True)
        with patch(
            "robot.google_calendar._import_google_modules",
            side_effect=GoogleCalendarDependencyError("missing deps"),
        ):
            body = google_calendar_status_text(self.settings)
        self.assertIn("state: missing_dependencies", body)
        self.assertIn("missing deps", body)

    def test_upcoming_requires_feature_flag(self) -> None:
        object.__setattr__(self.settings, "google_calendar_enabled", False)
        body = google_calendar_upcoming_text(self.settings)
        self.assertIn("disabled", body.lower())


if __name__ == "__main__":
    unittest.main()
