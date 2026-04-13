from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from robot.config import load_settings


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "README.md").write_text("# sample\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_codex_flag_defaults_enabled(self) -> None:
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            settings = load_settings(self.root)
        self.assertTrue(settings.codex_bypass_approvals_and_sandbox)
        self.assertTrue(settings.codex_skip_git_repo_check)

    def test_codex_flags_can_be_disabled_via_env(self) -> None:
        with unittest.mock.patch.dict(
            os.environ,
            {
                "ROBOT_CODEX_BYPASS_APPROVALS_AND_SANDBOX": "0",
                "ROBOT_CODEX_SKIP_GIT_REPO_CHECK": "false",
            },
            clear=True,
        ):
            settings = load_settings(self.root)
        self.assertFalse(settings.codex_bypass_approvals_and_sandbox)
        self.assertFalse(settings.codex_skip_git_repo_check)


if __name__ == "__main__":
    unittest.main()
