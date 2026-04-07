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


if __name__ == "__main__":
    unittest.main()
