from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from teleapp.context import MessageContext

from robot.config import load_settings
from robot.routing import AGENT_REQUEST, COMMAND_REQUEST, CONTROL_REQUEST, classify_request, handle_command, handle_control
from robot.state import ChatStateStore


class RoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        (root / "README.md").write_text("# robot\n", encoding="utf-8")
        self.settings = load_settings(root)
        self.store = ChatStateStore(self.settings)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_classify_command_request(self) -> None:
        ctx = MessageContext(chat_id=1, text="/status", command="status")
        request = classify_request(ctx)
        self.assertEqual(request.kind, COMMAND_REQUEST)

    def test_classify_control_request(self) -> None:
        ctx = MessageContext(chat_id=1, text="/reset", command="reset")
        request = classify_request(ctx)
        self.assertEqual(request.kind, CONTROL_REQUEST)

    def test_classify_agent_request(self) -> None:
        ctx = MessageContext(chat_id=1, text="fix this bug")
        request = classify_request(ctx)
        self.assertEqual(request.kind, AGENT_REQUEST)

    def test_provider_command_updates_state(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/provider gemini", command="provider"))
        body = handle_command(1, request, self.settings, self.store)
        self.assertIn("Provider updated.", body)
        self.assertEqual(self.store.get_chat_state(1)["provider"], "gemini")

    def test_reset_clears_current_thread(self) -> None:
        self.store.set_thread_id(1, "codex", "thread-1")
        request = classify_request(MessageContext(chat_id=1, text="/reset", command="reset"))
        body = handle_control(1, request, self.store)
        self.assertIn("Thread state cleared", body)
        self.assertIsNone(self.store.get_chat_state(1)["thread_id"])


if __name__ == "__main__":
    unittest.main()

