from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from robot.config import load_settings
from robot.google_calendar import (
    GoogleCalendarAuthError,
    GoogleCalendarDependencyError,
    authorize_google_calendar,
    google_calendar_status_text,
    google_calendar_upcoming_text,
)


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

    def test_authorize_no_browser_uses_local_server_without_opening_browser(self) -> None:
        object.__setattr__(self.settings, "google_calendar_enabled", True)
        credentials_path = self.settings.google_calendar_credentials_path
        credentials_path.write_text("{}", encoding="utf-8")

        class FakeCreds:
            def to_json(self) -> str:
                return '{"token":"ok"}'

        class FakeFlow:
            def __init__(self) -> None:
                self.calls: list[tuple[int, bool]] = []

            def run_local_server(self, *, port: int, open_browser: bool):
                self.calls.append((port, open_browser))
                return FakeCreds()

        class FakeFlowFactory:
            last_flow: FakeFlow | None = None

            @classmethod
            def from_client_secrets_file(cls, _path: str, _scopes: list[str]) -> FakeFlow:
                cls.last_flow = FakeFlow()
                return cls.last_flow

        with patch(
            "robot.google_calendar._import_google_modules",
            return_value=(object, object, FakeFlowFactory, object, object),
        ):
            message = authorize_google_calendar(self.settings, open_browser=False)

        self.assertIn("authorization completed", message.lower())
        assert FakeFlowFactory.last_flow is not None
        self.assertEqual(FakeFlowFactory.last_flow.calls, [(0, False)])
        self.assertTrue(self.settings.google_calendar_token_path.exists())

    def test_authorize_browser_mode_uses_local_server_with_open_browser(self) -> None:
        object.__setattr__(self.settings, "google_calendar_enabled", True)
        credentials_path = self.settings.google_calendar_credentials_path
        credentials_path.write_text("{}", encoding="utf-8")

        class FakeCreds:
            def to_json(self) -> str:
                return '{"token":"ok"}'

        class FakeFlow:
            def __init__(self) -> None:
                self.calls: list[tuple[int, bool]] = []

            def run_local_server(self, *, port: int, open_browser: bool):
                self.calls.append((port, open_browser))
                return FakeCreds()

        class FakeFlowFactory:
            last_flow: FakeFlow | None = None

            @classmethod
            def from_client_secrets_file(cls, _path: str, _scopes: list[str]) -> FakeFlow:
                cls.last_flow = FakeFlow()
                return cls.last_flow

        with patch(
            "robot.google_calendar._import_google_modules",
            return_value=(object, object, FakeFlowFactory, object, object),
        ):
            authorize_google_calendar(self.settings, open_browser=True)

        assert FakeFlowFactory.last_flow is not None
        self.assertEqual(FakeFlowFactory.last_flow.calls, [(0, True)])

    def test_authorize_wraps_invalid_credentials_as_auth_error(self) -> None:
        object.__setattr__(self.settings, "google_calendar_enabled", True)
        self.settings.google_calendar_credentials_path.write_text("{}", encoding="utf-8")

        class BrokenFlowFactory:
            @classmethod
            def from_client_secrets_file(cls, _path: str, _scopes: list[str]):
                raise ValueError("Client secrets must be for a web or installed app.")

        with patch(
            "robot.google_calendar._import_google_modules",
            return_value=(object, object, BrokenFlowFactory, object, object),
        ):
            with self.assertRaises(GoogleCalendarAuthError) as ctx:
                authorize_google_calendar(self.settings, open_browser=False)
        self.assertIn("credentials file is invalid", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
