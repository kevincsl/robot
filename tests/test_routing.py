from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from teleapp import ButtonResponse
from teleapp.context import MessageContext

from robot.agents import AgentCoordinator
from robot.config import load_settings
from robot.routing import (
    AGENT_REQUEST,
    COMMAND_REQUEST,
    CONTROL_REQUEST,
    classify_request,
    handle_command,
    handle_control,
    handle_request,
)
from robot.state import ChatStateStore


class RoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        (root / "README.md").write_text("# robot\n", encoding="utf-8")
        self.settings = load_settings(root)
        self.store = ChatStateStore(self.settings)
        self.agents = AgentCoordinator(self.settings, self.store)
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self) -> None:
        self.loop.run_until_complete(self.agents.shutdown())
        self.loop.close()
        self.tempdir.cleanup()

    def test_classify_command_request(self) -> None:
        ctx = MessageContext(chat_id=1, text="/status", command="status")
        request = classify_request(ctx)
        self.assertEqual(request.kind, COMMAND_REQUEST)

    def test_classify_command_request_without_ctx_command(self) -> None:
        ctx = MessageContext(chat_id=1, text="/model")
        request = classify_request(ctx)
        self.assertEqual(request.kind, COMMAND_REQUEST)
        self.assertEqual(request.command, "model")

    def test_classify_command_request_with_bot_suffix(self) -> None:
        ctx = MessageContext(chat_id=1, text="/model@my_robot_bot")
        request = classify_request(ctx)
        self.assertEqual(request.kind, COMMAND_REQUEST)
        self.assertEqual(request.command, "model")

    def test_classify_control_request(self) -> None:
        ctx = MessageContext(chat_id=1, text="/reset", command="reset")
        request = classify_request(ctx)
        self.assertEqual(request.kind, CONTROL_REQUEST)

    def test_classify_agent_request(self) -> None:
        ctx = MessageContext(chat_id=1, text="fix this bug")
        request = classify_request(ctx)
        self.assertEqual(request.kind, AGENT_REQUEST)

    def test_classify_common_phrase_as_control(self) -> None:
        ctx = MessageContext(chat_id=1, text="繼續")
        request = classify_request(ctx)
        self.assertEqual(request.kind, CONTROL_REQUEST)
        self.assertEqual(request.command, "continue")

    def test_menu_trigger_returns_buttons(self) -> None:
        body = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="menu"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIsInstance(body, ButtonResponse)
        self.assertIn("robot menu", body.text.lower())
        self.assertIn("其他自然語言訊息不會被選單吃掉", body.text)
        self.assertEqual([button.data for button in body.buttons or []], ["menu:status", "menu:provider", "menu:model", "menu:projects", "menu:cancel"])

    def test_menu_model_flow_updates_model_from_button_callback(self) -> None:
        open_menu = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="menu:model"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIsInstance(open_menu, ButtonResponse)
        flow = self.store.get_ui_flow(1)
        self.assertIsInstance(flow, dict)
        self.assertEqual(flow.get("kind"), "await_model")

        applied = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="menu:set_model:gpt-5.4"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIsInstance(applied, str)
        self.assertIn("Model updated.", applied)
        self.assertEqual(self.store.get_chat_state(1)["model"], "gpt-5.4")
        self.assertIsNone(self.store.get_ui_flow(1))

    def test_menu_model_flow_rejects_text_and_keeps_flow(self) -> None:
        open_menu = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="menu:model"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIsInstance(open_menu, ButtonResponse)
        self.assertIn("1.", open_menu.text)

        applied = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="2"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertEqual(applied, "請直接按 model 按鈕切換，或用 /model <name>。輸入 cancel 可離開。")
        flow = self.store.get_ui_flow(1)
        self.assertIsInstance(flow, dict)
        self.assertEqual(flow.get("kind"), "await_model")

    def test_model_command_without_payload_opens_chooser(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/model", command="model"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIsInstance(body, ButtonResponse)
        self.assertIn("Select Model", body.text)
        self.assertIn("1.", body.text)
        flow = self.store.get_ui_flow(1)
        self.assertIsInstance(flow, dict)
        self.assertEqual(flow.get("kind"), "await_model")

    def test_menu_text_action_status_works_without_buttons(self) -> None:
        self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="menu"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        body = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="status"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIsInstance(body, str)
        self.assertIn("robot status", body.lower())

    def test_menu_flow_allows_natural_language_to_reach_agent(self) -> None:
        self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="menu"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="請幫我檢查目前queue卡住的原因"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertIsInstance(body, str)
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_provider_command_updates_state(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/provider gemini", command="provider"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("Provider updated.", body)
        self.assertEqual(self.store.get_chat_state(1)["provider"], "gemini")

    def test_provider_command_without_payload_opens_chooser(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/provider", command="provider"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("可輸入的 provider:", body)
        self.assertIn("1.", body)
        flow = self.store.get_ui_flow(1)
        self.assertIsInstance(flow, dict)
        self.assertEqual(flow.get("kind"), "await_provider")

    def test_provider_flow_updates_state_from_numeric_choice(self) -> None:
        open_menu = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="menu:provider"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIn("1.", open_menu)

        applied = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="2"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIn("Provider updated.", applied)
        self.assertIsNone(self.store.get_ui_flow(1))

    def test_project_command_without_payload_opens_chooser(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/project", command="project"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("Available projects:", body)
        self.assertIn("1.", body)
        flow = self.store.get_ui_flow(1)
        self.assertIsInstance(flow, dict)
        self.assertEqual(flow.get("kind"), "await_project")

    def test_project_flow_updates_state_from_numeric_choice(self) -> None:
        open_menu = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="menu:projects"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIn("1.", open_menu)

        applied = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="1"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIn("Project updated.", applied)
        self.assertIsNone(self.store.get_ui_flow(1))

    def test_doctor_command_returns_report(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/doctor", command="doctor"))
        with patch("robot.routing.build_doctor_report", return_value="robot doctor\nok"):
            body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("robot doctor", body)

    def test_reset_clears_current_thread(self) -> None:
        self.store.set_thread_id(1, "codex", "thread-1")
        request = classify_request(MessageContext(chat_id=1, text="/reset", command="reset"))
        body = self.loop.run_until_complete(handle_control(1, request, self.store, self.agents))
        self.assertIn("Thread state cleared", body)
        self.assertIsNone(self.store.get_chat_state(1)["thread_id"])

    def test_restart_is_managed_by_supervisor(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/restart", command="restart"))
        body = self.loop.run_until_complete(handle_control(1, request, self.store, self.agents))
        self.assertIn("managed by teleapp supervisor", body)

    def test_run_command_enqueues_job(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/run inspect repo", command="run"))
        body = self.loop.run_until_complete(handle_control(1, request, self.store, self.agents))
        self.assertIn("Provider run started.", body)
        self.assertTrue(self.agents.is_running(1))

    def test_agent_command_enqueues_auto_dev_job(self) -> None:
        object.__setattr__(self.settings, "auto_dev_command", ["python", "-c", "import time; time.sleep(30)"])
        request = classify_request(MessageContext(chat_id=1, text="/agent implement /queue", command="agent"))
        body = self.loop.run_until_complete(handle_control(1, request, self.store, self.agents))
        self.assertIn("Auto-dev run started.", body)
        queue = self.store.get_agent_queue(1)
        self.assertEqual(len(queue), 0)
        current = self.store.get_chat_state(1)["agent_current_run"]
        self.assertIsInstance(current, dict)
        self.assertEqual(current["kind"], "auto_dev")

    def test_schedule_command_adds_auto_dev_schedule(self) -> None:
        request = classify_request(
            MessageContext(chat_id=1, text="/schedule 2026-04-09 10:00 implement queue", command="schedule")
        )
        body = self.loop.run_until_complete(handle_control(1, request, self.store, self.agents))
        self.assertIn("Scheduled auto-dev run.", body)
        schedules = self.store.get_agent_schedules(1)
        self.assertGreaterEqual(len(schedules), 1)
        self.assertEqual(schedules[-1]["kind"], "auto_dev")

    def test_stop_terminates_running_process(self) -> None:
        self.store.set_provider(1, "gemini")
        state = self.store.get_chat_state(1)
        self.store.set_project(1, str(state["project_key"]), str(state["project_name"]), str(Path(self.tempdir.name)))
        self.settings.provider_commands["gemini"] = [
            "python",
            "-c",
            "import time; time.sleep(30); print('done')",
        ]
        run_request = classify_request(MessageContext(chat_id=1, text="/run long task", command="run"))
        self.loop.run_until_complete(handle_control(1, run_request, self.store, self.agents))
        self.loop.run_until_complete(asyncio.sleep(0.5))
        stop_request = classify_request(MessageContext(chat_id=1, text="stop"))
        body = self.loop.run_until_complete(handle_control(1, stop_request, self.store, self.agents))
        self.assertIn("Stop signal sent", body)
        self.loop.run_until_complete(asyncio.sleep(0.8))
        self.assertFalse(self.agents.is_running(1))
        last_run = self.store.get_chat_state(1)["agent_last_run"]
        self.assertEqual(last_run["status"], "stopped")


if __name__ == "__main__":
    unittest.main()

