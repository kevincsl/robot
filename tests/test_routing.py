from __future__ import annotations

import asyncio
import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from markitdown._exceptions import FileConversionException
from teleapp import ButtonResponse, DocumentResponse
from teleapp.context import DocumentInput, MessageContext
from teleapp.protocol import AppEvent

from robot.agents import AgentCoordinator
from robot.config import load_settings
from robot.model_catalog import CatalogModel, ModelCatalog
from robot.projects import discover_project_workspaces
from robot.routing import (
    AGENT_REQUEST,
    COMMAND_REQUEST,
    CONTROL_REQUEST,
    HOSTED_BUILD_TAG,
    UI_BUILD_TAG,
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
        object.__setattr__(self.settings, "codex_bypass_approvals_and_sandbox", False)
        object.__setattr__(self.settings, "codex_skip_git_repo_check", False)
        state_home = root / ".robot_state"
        state_home.mkdir(parents=True, exist_ok=True)
        object.__setattr__(self.settings, "state_home", state_home)
        object.__setattr__(self.settings, "session_state_path", state_home / "robot_state.json")
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

    def test_classify_quick_command_request(self) -> None:
        ctx = MessageContext(chat_id=1, text="/quick", command="quick")
        request = classify_request(ctx)
        self.assertEqual(request.kind, COMMAND_REQUEST)
        self.assertEqual(request.command, "quick")

    def test_classify_command_request_without_ctx_command(self) -> None:
        ctx = MessageContext(chat_id=1, text="/model")
        request = classify_request(ctx)
        self.assertEqual(request.kind, COMMAND_REQUEST)
        self.assertEqual(request.command, "model")

    def test_classify_command_request_uses_ctx_text_payload_when_command_is_separate(self) -> None:
        ctx = MessageContext(chat_id=1, text="13:32", command="brainautodaily")
        request = classify_request(ctx)
        self.assertEqual(request.kind, COMMAND_REQUEST)
        self.assertEqual(request.command, "brainautodaily")
        self.assertEqual(request.payload, "13:32")

    def test_classify_command_request_with_bot_suffix(self) -> None:
        ctx = MessageContext(chat_id=1, text="/model@my_robot_bot")
        request = classify_request(ctx)
        self.assertEqual(request.kind, COMMAND_REQUEST)
        self.assertEqual(request.command, "model")

    def test_plain_text_user_mode_switch_is_handled_before_agent(self) -> None:
        body = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="使用者模式"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIn("已切換為使用者模式", body)
        self.assertEqual(self.store.get_display_mode(1), "user")

    def test_plain_text_developer_mode_switch_is_handled_before_agent(self) -> None:
        self.store.set_display_mode(1, "user")
        body = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="開發者模式"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIn("已切換為開發者模式", body)
        self.assertEqual(self.store.get_display_mode(1), "developer")

    def test_classify_control_request(self) -> None:
        ctx = MessageContext(chat_id=1, text="/reset", command="reset")
        request = classify_request(ctx)
        self.assertEqual(request.kind, CONTROL_REQUEST)

    def test_classify_panic_as_control_request(self) -> None:
        ctx = MessageContext(chat_id=1, text="/panic", command="panic")
        request = classify_request(ctx)
        self.assertEqual(request.kind, CONTROL_REQUEST)

    def test_classify_agent_request(self) -> None:
        ctx = MessageContext(chat_id=1, text="fix this bug")
        request = classify_request(ctx)
        self.assertEqual(request.kind, AGENT_REQUEST)

    def test_classify_common_phrase_as_control(self) -> None:
        ctx = MessageContext(chat_id=1, text="繼續")
        request = classify_request(ctx)
        self.assertEqual(request.kind, AGENT_REQUEST)
        self.assertIsNone(request.command)

    def test_classify_unknown_ctx_command_as_command_request(self) -> None:
        ctx = MessageContext(chat_id=1, text="", command="not_a_real_command")
        request = classify_request(ctx)
        self.assertEqual(request.kind, COMMAND_REQUEST)
        self.assertEqual(request.command, "not_a_real_command")

    def test_menu_trigger_returns_buttons(self) -> None:
        body = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="menu"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIsInstance(body, ButtonResponse)
        self.assertIn("robot menu", body.text.lower())
        self.assertIn(UI_BUILD_TAG, body.text)
        self.assertIn("其他自然語言訊息不會被選單吃掉", body.text)
        self.assertEqual([button.data for button in body.buttons or []], ["menu:status", "menu:provider", "menu:model", "menu:projects", "menu:cancel"])
        self.assertIsNone(self.store.get_ui_flow(1))

    def test_menu_trigger_returns_user_mode_buttons(self) -> None:
        self.store.set_display_mode(1, "user")
        body = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="menu"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIsInstance(body, ButtonResponse)
        self.assertEqual([button.data for button in body.buttons or []], ["menu:status", "menu:projects", "menu:cancel"])

    def test_menu_trigger_uses_external_json_buttons(self) -> None:
        payload = {
            "user": [
                {"text": "自訂狀態", "data": "menu:status"},
                {"text": "自訂取消", "data": "menu:cancel"},
            ],
            "developer": [
                {"text": "開發狀態", "data": "menu:status"},
                {"text": "開發專案", "data": "menu:projects"},
            ],
        }
        (self.settings.project_root / "menu_buttons.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        body = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="menu"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIsInstance(body, ButtonResponse)
        self.assertEqual([button.text for button in body.buttons or []], ["開發狀態", "開發專案"])
        self.assertEqual([button.data for button in body.buttons or []], ["menu:status", "menu:projects"])

    def test_status_includes_build_tags(self) -> None:
        self.store.set_last_provider_timing(1, {"elapsed_seconds": 8, "return_code": 0, "cancelled": False, "model": "claude-sonnet-4-6"})
        request = classify_request(MessageContext(chat_id=1, text="/status", command="status"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn(f"ui_build: {UI_BUILD_TAG}", body)
        self.assertIn(f"hosted_build: {HOSTED_BUILD_TAG}", body)
        self.assertIn("provider_elapsed_seconds: 8", body)
        self.assertIn("runtime_model: claude-sonnet-4-6", body)
        self.assertIn("queued_jobs: 0", body)
        self.assertIn("scheduled_jobs: 0", body)
        self.assertIn("ui_flow: -", body)
        self.assertIn("security_risk_mode: off", body)
        self.assertIn("codex_bypass_approvals_and_sandbox: False", body)
        self.assertIn("codex_skip_git_repo_check: False", body)
        self.assertIn("runtime_commit:", body)

    def test_status_shows_runtime_model_not_run_yet_before_any_provider_run(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/status", command="status"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("runtime_model: not_run_yet", body)

    def test_quick_command_returns_quick_reference(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/quick", command="quick"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("quick reference", body)
        self.assertIn("/brainbatchauto [limit]", body)
        self.assertIn("/menu", body)
        self.assertIn("/model [name]", body)
        self.assertIn("/mode [user|developer]", body)

    def test_guide_command_returns_docs_overview(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/guide", command="guide"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("features guide", body)
        self.assertIn("FEATURES_GUIDE.md", body)
        self.assertIn("/provider /model /project list", body)
        self.assertIn("/mode [user|developer]", body)

    def test_mode_command_without_payload_returns_second_level_commands(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/mode", command="mode"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("display_mode 可輸入:", body)
        self.assertIn("1. /display_mode_user", body)
        self.assertIn("2. /display_mode_dev", body)

    def test_mode_command_switches_to_user_mode(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/mode user", command="mode"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("已切換為使用者模式", body)
        self.assertEqual(self.store.get_display_mode(1), "user")

    def test_mode_command_switches_to_developer_mode_via_alias(self) -> None:
        self.store.set_display_mode(1, "user")
        request = classify_request(MessageContext(chat_id=1, text="/devmode", command="devmode"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("已切換為開發者模式", body)
        self.assertEqual(self.store.get_display_mode(1), "developer")

    def test_display_command_without_payload_returns_usage(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/display", command="display"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("COPY CODE 顯示模式", body)
        self.assertIn("/display copy_code", body)

    def test_display_command_accepts_legacy_all_mode_value(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/display all", command="display"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("COPY CODE 顯示模式已更新", body)
        self.assertIn("mode: copy_code", body)
        self.assertEqual(self.store.get_code_display_mode(1), "all")

    def test_display_command_switches_to_copy_code_mode(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/display copy_code", command="display"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("COPY CODE 顯示模式已更新", body)
        self.assertIn("mode: copy_code", body)
        self.assertEqual(self.store.get_code_display_mode(1), "all")

    def test_display_copy_code_command_switches_mode(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/display_copy_code", command="display_copy_code"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("COPY CODE 顯示模式已更新", body)
        self.assertIn("mode: copy_code", body)
        self.assertEqual(self.store.get_code_display_mode(1), "all")

    def test_status_shows_risk_mode_when_dangerous_flags_enabled(self) -> None:
        object.__setattr__(self.settings, "codex_bypass_approvals_and_sandbox", True)
        request = classify_request(MessageContext(chat_id=1, text="/status", command="status"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("security_risk_mode: on", body)
        self.assertIn("codex_bypass_approvals_and_sandbox: True", body)

    def test_status_shows_queue_schedule_and_flow_context(self) -> None:
        self.store.enqueue_agent_job(
            1,
            {
                "job_id": "job-queued-1",
                "kind": "provider",
                "goal": "inspect queue",
                "project_name": "robot",
            },
        )
        self.store.add_agent_schedule(
            1,
            {
                "job_id": "job-scheduled-1",
                "kind": "auto_dev",
                "goal": "scheduled goal",
                "run_at": "2026-05-01T10:00",
            },
        )
        self.store.set_ui_flow(1, {"kind": "await_brain_search"})
        request = classify_request(MessageContext(chat_id=1, text="/status", command="status"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("queued_jobs: 1", body)
        self.assertIn("scheduled_jobs: 1", body)
        self.assertIn("ui_flow: await_brain_search", body)

    def test_continue_without_active_job_falls_through_to_agent(self) -> None:
        self.store.set_agent_current_run(1, None)
        self.store.clear_agent_queue(1)
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="繼續"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_continue_with_active_job_uses_control_path(self) -> None:
        self.store.set_agent_current_run(
            1,
            {
                "job_id": "job-1",
                "kind": "provider",
                "goal": "test goal",
            },
        )
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="繼續"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_brain_trigger_returns_second_level_commands(self) -> None:
        body = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="brain"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIn("brain 可輸入:", body)
        self.assertIn("1. /brain_add", body)
        self.assertIn("4. /brain_search", body)
        self.assertIn("15. /brain_weekly", body)
        self.assertIsNone(self.store.get_ui_flow(1))

    def test_brain_schedule_button_opens_schedule_menu(self) -> None:
        body = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="brain:schedule"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIsInstance(body, ButtonResponse)
        self.assertIn("行程選單", body.text)
        self.assertEqual(
            [button.data for button in body.buttons or []],
            [
                "brain:schedule_new",
                "brain:schedule_today",
                "brain:schedule_week",
                "brain:schedule_next_week",
                "brain:schedule_month",
                "brain:schedule_list",
                "brain:cancel",
            ],
        )

    def test_menu_command_without_text_still_returns_buttons(self) -> None:
        body = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="menu"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIsInstance(body, ButtonResponse)
        self.assertIn("robot menu", body.text.lower())
        self.assertIsNone(self.store.get_ui_flow(1))

    def test_model_command_without_text_opens_model_chooser(self) -> None:
        body = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="model"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        # handle_request can return ButtonResponse
        body_text = body.text if hasattr(body, "text") else body
        self.assertIn("Select Model", body_text)

    def test_brain_command_without_text_still_returns_second_level_commands(self) -> None:
        body = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="brain"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIn("brain 可輸入:", body)
        self.assertIn("/brain_add", body)
        self.assertIn("/brain_weekly", body)
        self.assertIsNone(self.store.get_ui_flow(1))

    def test_plain_text_menu_routes_to_agent(self) -> None:
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="menu"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_plain_text_brain_routes_to_agent(self) -> None:
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="brain"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_flat_menu_text_action_works_without_open_menu_flow(self) -> None:
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="status"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_flat_brain_text_action_works_without_open_brain_flow(self) -> None:
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="搜尋"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_brain_capture_flow_appends_to_daily(self) -> None:
        self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="brain"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="brain:capture"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="今天整理第二大腦流程"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()
        self.assertIsNone(self.store.get_ui_flow(1))

    def test_brainread_command_reads_daily(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/brainread", command="brainread"))
        with patch("robot.routing.read_daily", return_value="# Daily\n\ncontent"):
            body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("content", body)

    def test_brainweb_command_captures_url_to_daily(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/brainweb https://example.com", command="brainweb"))
        with patch(
            "robot.routing.capture_web_to_daily",
            return_value=(
                "01 Daily Notes/2026-04-14.md",
                "Example Title",
                "Example body content",
                ["point 1", "point 2", "point 3"],
                ["example.com", "api"],
            ),
        ) as mock_capture:
            body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        mock_capture.assert_called_once_with(self.settings, "https://example.com", max_chars=2500)
        self.assertIn("已寫入今日筆記（網頁收錄）", body)
        self.assertIn("Example Title", body)
        self.assertIn("tags: example.com, api", body)
        self.assertIn("摘要重點：", body)
        self.assertIn("- point 1", body)

    def test_brainweb_command_requires_url(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/brainweb", command="brainweb"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("Usage: /brainweb <url>", body)

    def test_brainweb_command_handles_invalid_url(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/brainweb bad-url", command="brainweb"))
        with patch("robot.routing.capture_web_to_daily", side_effect=ValueError("Invalid URL")):
            body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("網址格式錯誤", body)

    def test_brainsearch_command_lists_matches(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/brainsearch product", command="brainsearch"))
        with patch("robot.routing.search_vault", return_value=["03 Knowledge/product.md", "02 Projects/roadmap.md"]):
            body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIsInstance(body, ButtonResponse)
        self.assertIn("搜尋結果", body.text)
        self.assertEqual([button.data for button in body.buttons or []], ["brain:open_note:0", "brain:open_note:1"])

    def test_brain_search_slash_alias_opens_search_flow(self) -> None:
        body = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="brain_search"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIn("請輸入要搜尋 secondbrain 的關鍵字", body)
        self.assertEqual(self.store.get_ui_flow(1), {"kind": "await_brain_search"})

    def test_brain_search_flow_returns_clickable_results(self) -> None:
        self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="brain"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="brain:search"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="product"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_brain_open_note_reads_selected_result(self) -> None:
        self.store.set_ui_flow(1, {"kind": "brain_search_results", "results": ["03 Knowledge/product.md"]})
        with patch("robot.routing.read_note", return_value="# Product\n\ncontent"):
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="", command="brain:open_note:0"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertIn("03 Knowledge/product.md", body)
        self.assertIn("content", body)

    def test_braindecide_returns_brief_and_path(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/braindecide Should I focus on product?", command="braindecide"))
        with patch("robot.routing.build_decision_support_brief", return_value=(["03 Knowledge/product.md"], "brief body")):
            with patch("robot.routing.create_decision_note_from_brief", return_value="07 Decision Support/Decision Review - x.md"):
                body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("brief body", body)
        self.assertIn("Decision Review", body)

    def test_brainremind_command_returns_reminders(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/brainremind", command="brainremind"))
        with patch("robot.routing.collect_brain_reminders", return_value=["- Inbox 還有 2 篇未整理內容"]):
            body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("提醒", body)
        self.assertIn("Inbox", body)

    def test_braindaily_command_returns_daily_brief(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/braindaily", command="braindaily"))
        with patch("robot.routing.build_daily_brief", return_value="每日摘要\n\n內容"):
            body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("每日摘要", body)

    def test_brainweekly_command_returns_weekly_brief(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/brainweekly", command="brainweekly"))
        with patch("robot.routing.build_weekly_brief", return_value="每週摘要\n\n內容"):
            body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("每週摘要", body)

    def test_brainauto_status_command_returns_settings(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/brainauto", command="brainauto"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("brain auto", body)
        self.assertIn("daily_time", body)

    def test_brainauto_on_off_commands_update_state(self) -> None:
        off_request = classify_request(MessageContext(chat_id=1, text="/brainauto off", command="brainauto"))
        off_body = self.loop.run_until_complete(handle_command(1, off_request, self.settings, self.store, self.agents))
        self.assertIn("disabled", off_body)
        self.assertFalse(self.store.get_brain_automation(1)["enabled"])

        on_request = classify_request(MessageContext(chat_id=1, text="/brainauto on", command="brainauto"))
        on_body = self.loop.run_until_complete(handle_command(1, on_request, self.settings, self.store, self.agents))
        self.assertIn("enabled", on_body)
        self.assertTrue(self.store.get_brain_automation(1)["enabled"])

    def test_brainautodaily_command_accepts_payload_from_telegram_command_context(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="13:32", command="brainautodaily"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("brain daily automation updated", body)
        self.assertEqual(self.store.get_brain_automation(1)["daily_time"], "13:32")

    def test_brainproject_command_creates_project_note(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/brainproject Roadmap", command="brainproject"))
        with patch("robot.routing.create_project_note", return_value="02 Projects/Roadmap.md"):
            body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("Project", body)
        self.assertIn("02 Projects/Roadmap.md", body)

    def test_brain_project_flow_creates_and_reads_note(self) -> None:
        self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="brain"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="brain:project"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="Roadmap"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_brain_organize_flow_creates_project_from_text(self) -> None:
        self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="brain"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="brain:organize"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="這是一段要整理成專案的原始內容"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()
        self.assertIsNone(self.store.get_ui_flow(1))

    def test_brain_batch_returns_recent_note_buttons(self) -> None:
        with patch("robot.routing.list_recent_notes", side_effect=[["00 Inbox/a.md"], ["01 Daily Notes/2026-04-10.md"]]):
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="", command="brain:batch"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertIsInstance(body, ButtonResponse)
        self.assertEqual([button.data for button in body.buttons or []], ["brain:batch_open:0", "brain:batch_open:1"])

    def test_brain_batch_open_loads_note_and_shows_target_buttons(self) -> None:
        self.store.set_ui_flow(1, {"kind": "brain_batch_results", "results": ["00 Inbox/a.md"]})
        with patch("robot.routing.read_note", return_value="raw note text"):
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="", command="brain:batch_open:0"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertIsInstance(body, ButtonResponse)
        self.assertEqual(
            [button.data for button in body.buttons or []],
            ["brain:organize_target:project", "brain:organize_target:knowledge", "brain:organize_target:resource"],
        )

    def test_brain_batch_auto_returns_summary(self) -> None:
        with patch(
            "robot.routing.auto_organize_recent_notes",
            return_value={
                "processed": 2,
                "created": 2,
                "skipped": 0,
                "failed": 0,
                "by_type": {"project": 1, "knowledge": 1, "resource": 0},
                "items": [
                    {
                        "source_path": "00 Inbox/a.md",
                        "path": "02 Projects/A.md",
                        "target": "project",
                        "status": "created",
                    },
                    {
                        "source_path": "01 Daily Notes/2026-04-10.md",
                        "path": "03 Knowledge/B.md",
                        "target": "knowledge",
                        "status": "created",
                    },
                ],
            },
        ) as mock_auto:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="", command="brain:batch_auto"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        mock_auto.assert_called_once_with(self.settings, limit=10)
        self.assertIn("自動批次整理完成", body)
        self.assertIn("processed: 2", body)
        self.assertIn("02 Projects/A.md", body)

    def test_brainbatchauto_command_accepts_limit(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/brainbatchauto 3", command="brainbatchauto"))
        with patch(
            "robot.routing.auto_organize_recent_notes",
            return_value={
                "processed": 1,
                "created": 1,
                "skipped": 0,
                "failed": 0,
                "by_type": {"project": 0, "knowledge": 1, "resource": 0},
                "items": [
                    {
                        "source_path": "00 Inbox/a.md",
                        "path": "03 Knowledge/A.md",
                        "target": "knowledge",
                        "status": "created",
                    }
                ],
            },
        ) as mock_auto:
            body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        mock_auto.assert_called_once_with(self.settings, limit=3)
        self.assertIn("limit=3", body)
        self.assertIn("created: 1", body)

    def test_brainknowledge_command_creates_knowledge_note(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/brainknowledge Prompt Engineering", command="brainknowledge"))
        with patch("robot.routing.create_knowledge_note", return_value="03 Knowledge/Prompt Engineering.md"):
            body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("Knowledge", body)
        self.assertIn("03 Knowledge/Prompt Engineering.md", body)

    def test_brainresource_command_creates_resource_note(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/brainresource AI article", command="brainresource"))
        with patch("robot.routing.create_resource_note", return_value="04 Resources/AI article.md"):
            body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("Resource", body)
        self.assertIn("04 Resources/AI article.md", body)

    def test_document_upload_prompts_for_action_and_sets_flow(self) -> None:
        ctx = MessageContext(
            chat_id=1,
            text="Meeting notes",
            caption="Meeting notes",
            document=DocumentInput(
                file_id="f1",
                file_unique_id="u1",
                file_name="meeting.pdf",
                mime_type="application/pdf",
                local_path="C:\\temp\\meeting.pdf",
            ),
        )
        with patch(
            "robot.routing.import_markitdown_resource",
            return_value=("04 Resources/Meeting notes.md", "# Meeting notes\n\nSummary body"),
        ) as mock_import, patch("robot.security.sanitize_file_size"):
            body = self.loop.run_until_complete(handle_request(ctx, self.settings, self.store, self.agents))
        mock_import.assert_not_called()
        flow = self.store.get_ui_flow(1)
        self.assertIsInstance(flow, dict)
        self.assertEqual(flow.get("kind"), "await_file_action")
        self.assertEqual(flow.get("local_path"), "C:\\temp\\meeting.pdf")
        self.assertEqual(flow.get("source_name"), "meeting.pdf")
        self.assertEqual(flow.get("title"), "Meeting notes")
        self.assertIn("已收到檔案", body)
        self.assertIn("要怎麼處理", body)

    def test_document_upload_imports_markitdown_resource_after_user_action(self) -> None:
        upload_ctx = MessageContext(
            chat_id=1,
            text="Meeting notes",
            caption="Meeting notes",
            document=DocumentInput(
                file_id="f1",
                file_unique_id="u1",
                file_name="meeting.pdf",
                mime_type="application/pdf",
                local_path="C:\\temp\\meeting.pdf",
            ),
        )
        with patch(
            "robot.routing.import_markitdown_resource",
            return_value=("04 Resources/Meeting notes.md", "# Meeting notes\n\nSummary body"),
        ) as mock_import, patch("robot.security.sanitize_file_size"):
            prompt_body = self.loop.run_until_complete(handle_request(upload_ctx, self.settings, self.store, self.agents))
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="匯入 secondbrain"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )

        self.assertIn("已收到檔案", prompt_body)
        mock_import.assert_called_once()
        args, kwargs = mock_import.call_args
        self.assertEqual(args[0], self.settings)
        self.assertEqual(args[1], Path("C:/temp/meeting.pdf"))
        self.assertEqual(kwargs["title"], "Meeting notes")
        self.assertIn("已匯入文件到 secondbrain", body)
        self.assertIn("04 Resources/Meeting notes.md", body)
        self.assertIn("meeting.pdf", body)
        self.assertIn("Summary body", body)

    def test_document_upload_without_local_path_returns_error(self) -> None:
        ctx = MessageContext(
            chat_id=1,
            text="",
            document=DocumentInput(
                file_id="f1",
                file_unique_id="u1",
                file_name="meeting.pdf",
                mime_type="application/pdf",
                local_path=None,
            ),
        )
        body = self.loop.run_until_complete(handle_request(ctx, self.settings, self.store, self.agents))
        self.assertIn("沒有可讀取的本機路徑", body)


    def test_document_upload_convert_image_to_pdf_after_user_action(self) -> None:
        upload_ctx = MessageContext(
            chat_id=1,
            text="photo",
            caption="photo",
            document=DocumentInput(
                file_id="f1",
                file_unique_id="u1",
                file_name="photo.jpg",
                mime_type="image/jpeg",
                local_path="C:\\temp\\photo.jpg",
            ),
        )
        with patch("robot.routing._convert_image_to_pdf", return_value=Path("C:/temp/photo.pdf")) as mock_convert, patch(
            "robot.security.sanitize_file_size"
        ):
            prompt_body = self.loop.run_until_complete(handle_request(upload_ctx, self.settings, self.store, self.agents))
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="轉存 PDF"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )

        self.assertIn("已收到檔案", prompt_body)
        mock_convert.assert_called_once_with(Path("C:/temp/photo.jpg"))
        self.assertIsInstance(body, DocumentResponse)
        self.assertEqual(body.text, "已轉存 PDF。")
        self.assertEqual(str(body.file_path).replace("\\", "/"), "C:/temp/photo.pdf")
        self.assertEqual(body.caption, "source_file: photo.jpg")

    def test_document_upload_convert_image_to_pdf_send_after_user_action(self) -> None:
        upload_ctx = MessageContext(
            chat_id=1,
            text="photo",
            caption="photo",
            document=DocumentInput(
                file_id="f1",
                file_unique_id="u1",
                file_name="photo.jpg",
                mime_type="image/jpeg",
                local_path="C:\\temp\\photo.jpg",
            ),
        )
        with patch("robot.routing._convert_image_to_pdf", return_value=Path("C:/temp/photo.pdf")) as mock_convert, patch(
            "robot.security.sanitize_file_size"
        ):
            self.loop.run_until_complete(handle_request(upload_ctx, self.settings, self.store, self.agents))
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="Pdf 傳給我"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )

        mock_convert.assert_called_once_with(Path("C:/temp/photo.jpg"))
        self.assertIsInstance(body, DocumentResponse)
        self.assertEqual(body.text, "已轉存 PDF。")
        self.assertEqual(str(body.file_path).replace("\\", "/"), "C:/temp/photo.pdf")
        self.assertEqual(body.caption, "source_file: photo.jpg")

    def test_document_upload_convert_pdf_for_non_image_returns_hint(self) -> None:
        upload_ctx = MessageContext(
            chat_id=1,
            text="Meeting notes",
            caption="Meeting notes",
            document=DocumentInput(
                file_id="f1",
                file_unique_id="u1",
                file_name="meeting.pdf",
                mime_type="application/pdf",
                local_path="C:\\temp\\meeting.pdf",
            ),
        )
        with patch("robot.security.sanitize_file_size"):
            self.loop.run_until_complete(handle_request(upload_ctx, self.settings, self.store, self.agents))
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="轉存 PDF"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )

        self.assertIn("目前只支援把圖片轉成 PDF", body)
        self.assertIn("source_file: meeting.pdf", body)

    def test_document_upload_pdf_missing_dependency_returns_friendly_error(self) -> None:
        upload_ctx = MessageContext(
            chat_id=1,
            text="Meeting notes",
            caption="Meeting notes",
            document=DocumentInput(
                file_id="f1",
                file_unique_id="u1",
                file_name="meeting.pdf",
                mime_type="application/pdf",
                local_path="C:\\temp\\meeting.pdf",
            ),
        )
        with patch(
            "robot.routing.import_markitdown_resource",
            side_effect=FileConversionException(
                message=(
                    "File conversion failed after 1 attempts:\n"
                    "- PdfConverter threw MissingDependencyException with message: "
                    "PdfConverter recognized the input as a potential .pdf file, but the dependencies needed "
                    "to read .pdf files have not been installed. To resolve this error, include the optional "
                    "dependency [pdf] or [all] when installing MarkItDown. For example:\n"
                    "* pip install markitdown[pdf]"
                )
            ),
        ), patch("robot.security.sanitize_file_size"):
            prompt_body = self.loop.run_until_complete(handle_request(upload_ctx, self.settings, self.store, self.agents))
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="匯入 secondbrain"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertIn("已收到檔案", prompt_body)
        self.assertIn("還沒有安裝 PDF 轉換依賴", body)
        self.assertIn("meeting.pdf", body)
        self.assertIn("markitdown[pdf]", body)

    def test_brainschedule_command_without_payload_starts_flow(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/brainschedule", command="brainschedule"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("請輸入行程標題", body)
        flow = self.store.get_ui_flow(1)
        self.assertIsInstance(flow, dict)
        self.assertEqual(flow.get("kind"), "await_brain_schedule_title")

    def test_brain_schedule_new_flow_creates_schedule_note(self) -> None:
        self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="brain:schedule_new"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="Weekly sync"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()
        self.assertIsNone(self.store.get_ui_flow(1))


    def test_brain_schedule_new_flow_accepts_natural_language_then_confirms(self) -> None:
        self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="brain:schedule_new"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="今天下午6點半要吃藥"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()
        self.assertIsNone(self.store.get_ui_flow(1))

    def test_plain_natural_language_schedule_message_routes_to_agent(self) -> None:
        self.store.clear_ui_flow(1)
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="提醒我今天下午6點半吃藥"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_plain_natural_language_schedule_with_point_minutes_routes_to_agent(self) -> None:
        self.store.clear_ui_flow(1)
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="幫我加入行程 今天晚上23點40分要睡覺"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_plain_relative_schedule_message_routes_to_agent(self) -> None:
        self.store.clear_ui_flow(1)
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="30分鐘後要休息"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_plain_next_weekday_schedule_message_routes_to_agent(self) -> None:
        self.store.clear_ui_flow(1)
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="安排下週二下午3點交報告"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_plain_weekly_recurring_schedule_message_routes_to_agent(self) -> None:
        self.store.clear_ui_flow(1)
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="每週三晚上8點吃火鍋"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_schedule_send_agent_routes_original_text_to_codex(self) -> None:
        self.store.set_ui_flow(
            1,
            {
                "kind": "await_brain_schedule_confirm",
                "title": "吃藥",
                "date_text": "2026-04-13",
                "time_text": "18:30",
                "source_text": "提醒我今天下午6點半吃藥",
            },
        )
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="", command="brain:schedule_send_agent"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()
        self.assertIsNone(self.store.get_ui_flow(1))

    def test_schedule_send_agent_uses_last_candidate_when_flow_was_cleared(self) -> None:
        self.store.set_last_schedule_candidate(
            1,
            {
                "kind": "await_brain_schedule_confirm",
                "title": "log",
                "date_text": "2026-04-13",
                "time_text": "23:40",
                "source_text": "今天晚上11點40分那個 log 你看一下",
            },
        )
        self.store.clear_ui_flow(1)
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="", command="brain:schedule_send_agent"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()
        self.assertIsNone(self.store.get_ui_flow(1))
        self.assertIsNone(self.store.get_last_schedule_candidate(1))

    def test_delete_schedule_phrase_routes_to_agent(self) -> None:
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="去除吃藥行程"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_schedule_delete_confirm_archives_note(self) -> None:
        self.store.set_ui_flow(
            1,
            {
                "kind": "await_brain_schedule_delete_confirm",
                "title": "吃藥",
                "path": "06 Schedule/吃藥.md",
                "source_text": "去除吃藥行程",
            },
        )
        with patch("robot.routing.archive_schedule_note", return_value="99 Archive/Deleted Schedule/吃藥.md") as mock_archive:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="", command="brain:schedule_delete_confirm"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        mock_archive.assert_called_once_with(self.settings, "06 Schedule/吃藥.md")
        self.assertIn("已封存行程", body)
        self.assertIn("99 Archive/Deleted Schedule/吃藥.md", body)

    def test_delete_schedule_send_agent_routes_original_text_to_codex(self) -> None:
        self.store.set_ui_flow(
            1,
            {
                "kind": "await_brain_schedule_delete_confirm",
                "title": "吃藥",
                "path": "06 Schedule/吃藥.md",
                "source_text": "去除吃藥行程",
            },
        )
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="", command="brain:schedule_send_agent"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_update_schedule_phrase_routes_to_agent(self) -> None:
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="把升學輔導會議在第一會議室改到下午1點"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_schedule_update_confirm_updates_note(self) -> None:
        self.store.set_ui_flow(
            1,
            {
                "kind": "await_brain_schedule_update_confirm",
                "title": "升學輔導會議在第一會議室",
                "path": "06 Schedule/升學輔導會議在第一會議室.md",
                "date_text": "2026-04-20",
                "time_text": "13:00",
                "recurrence_type": "",
                "recurrence_value": "",
                "source_text": "把升學輔導會議在第一會議室改到下午1點",
            },
        )
        with patch("robot.routing.update_schedule_note", return_value="06 Schedule/升學輔導會議在第一會議室.md") as mock_update:
            with patch("robot.routing.read_note", return_value="# Schedule\n\ntime updated"):
                body = self.loop.run_until_complete(
                    handle_request(
                        MessageContext(chat_id=1, text="", command="brain:schedule_update_confirm"),
                        self.settings,
                        self.store,
                        self.agents,
                    )
                )
        mock_update.assert_called_once_with(
            self.settings,
            "06 Schedule/升學輔導會議在第一會議室.md",
            date_text="2026-04-20",
            time_text="13:00",
            recurrence_type="",
            recurrence_value="",
        )
        self.assertIn("已更新 Schedule 筆記", body)

    def test_schedule_cancel_button_routes_original_text_to_codex(self) -> None:
        self.store.set_ui_flow(
            1,
            {
                "kind": "await_brain_schedule_confirm",
                "title": "log",
                "date_text": "2026-04-13",
                "time_text": "23:40",
                "source_text": "今天晚上11點40分那個 log 你看一下",
            },
        )
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="", command="brain:cancel"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()
        self.assertIsNone(self.store.get_ui_flow(1))

    def test_schedule_cancel_text_routes_original_text_to_codex(self) -> None:
        self.store.set_ui_flow(
            1,
            {
                "kind": "await_brain_schedule_confirm",
                "title": "log",
                "date_text": "2026-04-13",
                "time_text": "23:40",
                "source_text": "今天晚上11點40分那個 log 你看一下",
            },
        )
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="cancel"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()
        self.assertIsNone(self.store.get_ui_flow(1))

    def test_schedule_confirm_writes_recurring_properties(self) -> None:
        self.store.set_ui_flow(
            1,
            {
                "kind": "await_brain_schedule_confirm",
                "title": "吃火鍋",
                "date_text": "2026-04-15",
                "time_text": "20:00",
                "recurrence_type": "weekly",
                "recurrence_value": "2",
            },
        )
        with patch("robot.routing.create_schedule_note", return_value="06 Schedule/吃火鍋.md") as mock_create:
            with patch("robot.routing.read_note", return_value="# Schedule\n\ncontent"):
                body = self.loop.run_until_complete(
                    handle_request(
                        MessageContext(chat_id=1, text="", command="brain:schedule_confirm"),
                        self.settings,
                        self.store,
                        self.agents,
                    )
                )
        mock_create.assert_called_once_with(
            self.settings,
            "吃火鍋",
            date_text="2026-04-15",
            time_text="20:00",
            recurrence_type="weekly",
            recurrence_value="2",
        )
        self.assertIn("已建立 Schedule 筆記", body)

    def test_plain_question_still_reaches_agent(self) -> None:
        self.store.clear_ui_flow(1)
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="請幫我檢查目前queue卡住的原因"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_plain_time_mention_without_schedule_intent_reaches_agent(self) -> None:
        self.store.clear_ui_flow(1)
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="今天晚上11點40分那個 log 你看一下"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()
    def test_brain_schedule_today_returns_brief(self) -> None:
        with patch(
            "robot.routing.list_schedule_occurrences",
            return_value=("今日行程", [{"title": "Standup", "date": "2026-04-12", "time": "09:00", "path": "06 Schedule/Standup.md", "recurrence": ""}]),
        ) as mock_brief:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="", command="brain:schedule_today"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        mock_brief.assert_called_once_with(self.settings, period="day", limit=50)
        self.assertIn("今日行程", body)

    def test_brain_schedule_week_returns_brief(self) -> None:
        with patch(
            "robot.routing.list_schedule_occurrences",
            return_value=("本週行程", [{"title": "吃藥", "date": "2026-04-13", "time": "07:30", "path": "06 Schedule/吃藥.md", "recurrence": "每天"}]),
        ) as mock_brief:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="", command="brain:schedule_week"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        mock_brief.assert_called_once_with(self.settings, period="week", limit=80)
        self.assertIn("本週行程", body)

    def test_brain_schedule_next_week_returns_brief(self) -> None:
        with patch(
            "robot.routing.list_schedule_occurrences",
            return_value=(
                "下週行程",
                [
                    {
                        "title": "會議",
                        "date": "2026-04-20",
                        "time": "13:00",
                        "path": "06 Schedule/會議.md",
                        "recurrence": "",
                    }
                ],
            ),
        ) as mock_occurrences:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="", command="brain:schedule_next_week"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        mock_occurrences.assert_called_once_with(self.settings, period="next_week", limit=80)
        self.assertIn("下週行程", body)
        self.assertEqual(self.store.get_last_schedule_results(1)[0]["title"], "會議")

    def test_last_schedule_reference_routes_to_agent(self) -> None:
        self.store.set_last_schedule_results(
            1,
            [
                {
                    "title": "升學輔導會議在第一會議室",
                    "date": "2026-04-20",
                    "time": "13:00",
                    "path": "06 Schedule/升學輔導會議在第一會議室.md",
                    "recurrence": "",
                }
            ],
        )
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="這個行程是幾點"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_flat_week_schedule_phrase_returns_week_schedule(self) -> None:
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="這一週行程"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_semantic_week_schedule_phrase_over_ten_chars_routes_to_agent(self) -> None:
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="幫我看這禮拜有哪些行程"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_semantic_shortcut_within_five_chars_runs_directly(self) -> None:
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="看本週行程"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_semantic_shortcut_six_to_ten_chars_requires_confirmation(self) -> None:
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="請看本週行程"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_shortcut_confirm_executes_detected_action(self) -> None:
        body = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="shortcut:confirm"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIn("Unknown command: /shortcut:confirm", body)

    def test_shortcut_send_agent_routes_original_text_to_agent(self) -> None:
        body = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="shortcut:send_agent"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIn("Unknown command: /shortcut:send_agent", body)

    def test_semantic_next_week_schedule_phrase_returns_next_week_schedule(self) -> None:
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="下週行程"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_flat_month_schedule_phrase_returns_month_schedule(self) -> None:
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="這個月行程"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_schedule_create_phrase_routes_to_agent(self) -> None:
        with patch("robot.routing.build_schedule_range_brief") as mock_brief:
            with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
                body = self.loop.run_until_complete(
                    handle_request(
                        MessageContext(chat_id=1, text="幫我加入行程 今天晚上23點40分要睡覺"),
                        self.settings,
                        self.store,
                        self.agents,
                    )
                )
        mock_handle_agent.assert_awaited_once()
        self.assertEqual(body, "agent delegated")
        mock_brief.assert_not_called()

    def test_semantic_archive_past_schedule_phrase_routes_to_agent(self) -> None:
        with patch("robot.routing.archive_past_due_schedule_notes", return_value=[]) as mock_archive:
            with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
                body = self.loop.run_until_complete(
                    handle_request(
                        MessageContext(chat_id=1, text="將已經超過時間的行程封存"),
                        self.settings,
                        self.store,
                        self.agents,
                    )
                )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()
        mock_archive.assert_not_called()

    def test_brain_schedule_list_returns_brief(self) -> None:
        with patch("robot.routing.build_schedule_brief", return_value="行程列表\n\n- 2026-04-13 10:00 | Review") as mock_brief:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="", command="brain:schedule_list"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        mock_brief.assert_called_once_with(self.settings, today_only=False, limit=10)
        self.assertIn("行程列表", body)

    def test_brain_schedule_archive_past_returns_summary(self) -> None:
        with patch(
            "robot.routing.archive_past_due_schedule_notes",
            return_value=[
                {
                    "title": "休息",
                    "date": "2026-04-13",
                    "time": "01:10",
                    "path": "06 Schedule/休息.md",
                    "archived_path": "99 Archive/Deleted Schedule/休息.md",
                }
            ],
        ) as mock_archive:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="", command="brain:schedule_archive_past"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        mock_archive.assert_called_once_with(self.settings, limit=200)
        self.assertIn("已封存過期行程", body)
        self.assertIn("06 Schedule/休息.md", body)

    def test_menu_model_flow_rejects_missing_claude_catalog_model(self) -> None:
        self.store.set_provider(1, "claude")
        open_menu = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="menu:model"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIsInstance(open_menu, ButtonResponse)

        applied = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="menu:set_model:claude-not-real"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIn("Model not available for claude", applied)
        self.assertEqual(self.store.get_chat_state(1)["model"], "claude-opus-4-7")

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

    def test_menu_model_flow_updates_to_gpt_5_3_codex_from_button_callback(self) -> None:
        open_menu = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="menu:model"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIsInstance(open_menu, ButtonResponse)

        applied = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="menu:set_model:gpt-5.3-codex"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIsInstance(applied, str)
        self.assertIn("Model updated.", applied)
        self.assertEqual(self.store.get_chat_state(1)["model"], "gpt-5.3-codex")
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
        self.assertEqual(applied, "請直接按 model 按鈕切換，或用 /model <name>。輸入 /menu 返回主選單。")
        flow = self.store.get_ui_flow(1)
        self.assertIsInstance(flow, dict)
        self.assertEqual(flow.get("kind"), "await_model")

    def test_model_command_without_payload_opens_model_chooser(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/model", command="model"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        body_text = body.text if hasattr(body, "text") else body
        self.assertIn("Select Model", body_text)

    def test_models_command_uses_dynamic_catalog(self) -> None:
        self.store.set_provider(1, "codex")
        catalog = ModelCatalog(
            provider="codex",
            items=(
                CatalogModel(name="gpt-5.5", description="Frontier model for complex work."),
                CatalogModel(name="gpt-5.4", description="Strong model for everyday coding."),
            ),
            source="codex debug models",
            note=None,
        )
        request = classify_request(MessageContext(chat_id=1, text="/models", command="models"))
        with patch("robot.routing.get_model_catalog", return_value=catalog):
            body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("Models for codex:", body)
        self.assertIn("source: codex debug models", body)
        self.assertIn("- gpt-5.5", body)
        self.assertIn("- gpt-5.4", body)

    def test_model_codex_command_uses_dynamic_catalog(self) -> None:
        self.store.set_provider(1, "codex")
        catalog = ModelCatalog(
            provider="codex",
            items=(
                CatalogModel(name="gpt-5.5", description="Frontier model for complex work."),
                CatalogModel(name="gpt-5.4", description="Strong model for everyday coding."),
            ),
            source="codex debug models",
            note=None,
        )
        request = classify_request(MessageContext(chat_id=1, text="/model_codex", command="model_codex"))
        with patch("robot.routing.get_model_catalog", return_value=catalog):
            body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("Models for codex:", body)
        self.assertIn("- gpt-5.5", body)
        self.assertIn("- gpt-5.4", body)

    def test_model_command_rejects_missing_claude_catalog_model(self) -> None:
        self.store.set_provider(1, "claude")
        request = classify_request(MessageContext(chat_id=1, text="/model claude-not-real", command="model"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("Model not available for claude", body)
        self.assertEqual(self.store.get_chat_state(1)["model"], "claude-opus-4-7")

    def test_model_command_keeps_custom_model_for_claude(self) -> None:
        object.__setattr__(self.settings, "custom_models", ["deepseek-chat"])
        self.store.set_provider(1, "claude")
        request = classify_request(MessageContext(chat_id=1, text="/model deepseek-chat", command="model"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertEqual(body, "Model updated.\nprovider: claude\nmodel: deepseek-chat")
        self.assertEqual(self.store.get_chat_state(1)["model"], "deepseek-chat")

    def test_menu_text_action_status_works_without_buttons(self) -> None:
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="status"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertIsInstance(body, str)
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_menu_flow_allows_natural_language_to_reach_agent(self) -> None:
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

    def test_plain_text_menu_routes_to_agent(self) -> None:
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="menu"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
        self.assertEqual(body, "agent delegated")
        mock_handle_agent.assert_awaited_once()

    def test_plain_text_brain_routes_to_agent(self) -> None:
        with patch("robot.routing.handle_agent", new=AsyncMock(return_value="agent delegated")) as mock_handle_agent:
            body = self.loop.run_until_complete(
                handle_request(
                    MessageContext(chat_id=1, text="brain"),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
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
        self.assertIn("provider 可輸入:", body)
        self.assertIn("1. /provider_codex", body)
        self.assertIn("2. /provider_claude", body)
        self.assertIn("3. /provider_gemini", body)
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
        self.assertIsInstance(body, ButtonResponse)
        self.assertIn("Available projects:", body.text)
        self.assertTrue(any(button.data.startswith("proj-") for button in (body.buttons or [])))
        self.assertTrue(any(button.text.startswith("Use: ") for button in (body.buttons or [])))
        flow = self.store.get_ui_flow(1)
        self.assertIsInstance(flow, dict)
        self.assertEqual(flow.get("kind"), "await_project")

    def test_projects_command_without_payload_opens_chooser(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/projects", command="projects"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIsInstance(body, ButtonResponse)
        self.assertIn("Available projects:", body.text)
        flow = self.store.get_ui_flow(1)
        self.assertIsInstance(flow, dict)
        self.assertEqual(flow.get("kind"), "await_project")

    def test_project_command_from_plain_command_text_opens_chooser(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="project", command="project"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIsInstance(body, ButtonResponse)
        self.assertIn("Available projects:", body.text)
        flow = self.store.get_ui_flow(1)
        self.assertIsInstance(flow, dict)
        self.assertEqual(flow.get("kind"), "await_project")

    def test_project_discover_alias_opens_chooser(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/project discover", command="project"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIsInstance(body, ButtonResponse)
        self.assertIn("Available projects:", body.text)
        flow = self.store.get_ui_flow(1)
        self.assertIsInstance(flow, dict)
        self.assertEqual(flow.get("kind"), "await_project")

    def test_projects_chooser_marks_registered_status(self) -> None:
        workspaces = discover_project_workspaces(self.settings)
        self.assertTrue(workspaces)
        register_project_name = "demo"
        register_project_path = str(workspaces[0].path)
        register_request = classify_request(
            MessageContext(
                chat_id=1,
                text=f"/project register {register_project_name} {register_project_path}",
                command="project",
            )
        )
        _ = self.loop.run_until_complete(handle_command(1, register_request, self.settings, self.store, self.agents))
        chooser_request = classify_request(MessageContext(chat_id=1, text="/projects", command="projects"))
        body = self.loop.run_until_complete(handle_command(1, chooser_request, self.settings, self.store, self.agents))
        self.assertIsInstance(body, ButtonResponse)
        self.assertIn("Registered in list:", body.text)
        self.assertIn("registered (demo)", body.text)

    def test_projects_list_returns_indexed_text_list(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/projects list", command="projects"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIsInstance(body, str)
        self.assertIn("No registered projects.", body)

    def test_projects_command_with_payload_updates_state(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/projects 1", command="projects"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("Project updated.", body)
        state = self.store.get_chat_state(1)
        self.assertTrue(str(state["project_key"]).startswith("proj-"))

    def test_project_register_list_use_note_doctor_flow(self) -> None:
        workspace = Path(self.tempdir.name) / "demo-project"
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "README.md").write_text("# demo\n", encoding="utf-8")

        register_request = classify_request(
            MessageContext(chat_id=1, text=f"/project register demo {workspace}", command="project")
        )
        register_body = self.loop.run_until_complete(handle_command(1, register_request, self.settings, self.store, self.agents))
        self.assertIn("Project registered.", register_body)
        self.assertIn("name: demo", register_body)

        list_request = classify_request(MessageContext(chat_id=1, text="/project list", command="project"))
        list_body = self.loop.run_until_complete(handle_command(1, list_request, self.settings, self.store, self.agents))
        self.assertIn("Registered projects: 1", list_body)
        self.assertIn("demo", list_body)

        use_request = classify_request(MessageContext(chat_id=1, text="/project use demo", command="project"))
        use_body = self.loop.run_until_complete(handle_command(1, use_request, self.settings, self.store, self.agents))
        self.assertIn("Project updated.", use_body)
        self.assertEqual(self.store.get_chat_state(1)["project_name"], "demo")

        info_request = classify_request(MessageContext(chat_id=1, text="/project info demo", command="project"))
        info_body = self.loop.run_until_complete(handle_command(1, info_request, self.settings, self.store, self.agents))
        self.assertIn("project info", info_body)
        self.assertIn("name: demo", info_body)

        note_request = classify_request(
            MessageContext(chat_id=1, text="/project note demo hello world", command="project")
        )
        note_body = self.loop.run_until_complete(handle_command(1, note_request, self.settings, self.store, self.agents))
        self.assertIn("Project note saved.", note_body)
        note_path = self.settings.state_home / "projects" / "demo" / "notes.md"
        self.assertTrue(note_path.exists())
        self.assertIn("hello world", note_path.read_text(encoding="utf-8"))

        doctor_request = classify_request(MessageContext(chat_id=1, text="/project doctor demo", command="project"))
        doctor_body = self.loop.run_until_complete(handle_command(1, doctor_request, self.settings, self.store, self.agents))
        self.assertIn("demo: ", doctor_body)

    def test_project_flow_updates_state_from_numeric_choice(self) -> None:
        open_menu = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="menu:projects:discover"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIsInstance(open_menu, ButtonResponse)
        self.assertIn("Available projects:", open_menu.text)

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

    def test_project_flow_updates_state_from_inline_button_choice(self) -> None:
        open_menu = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="menu:projects:discover"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIsInstance(open_menu, ButtonResponse)
        project_button = next(
            button for button in (open_menu.buttons or []) if button.data.startswith("proj-")
        )

        applied = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command=project_button.data),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.assertIn("Project updated.", applied)
        self.assertEqual(self.store.get_chat_state(1)["project_key"], project_button.data)
        self.assertIsNone(self.store.get_ui_flow(1))

    def test_project_management_menu_marks_chat_local_active_project(self) -> None:
        workspace = Path(self.tempdir.name) / "demo-project"
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "README.md").write_text("# demo\n", encoding="utf-8")

        self.loop.run_until_complete(
            handle_command(
                1,
                classify_request(MessageContext(chat_id=1, text=f"/project register demo {workspace}", command="project")),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.loop.run_until_complete(
            handle_command(
                1,
                classify_request(MessageContext(chat_id=1, text="/project use demo", command="project")),
                self.settings,
                self.store,
                self.agents,
            )
        )

        body = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="", command="menu:projects"),
                self.settings,
                self.store,
                self.agents,
            )
        )

        self.assertIsInstance(body, ButtonResponse)
        self.assertTrue(any(button.text == "Use demo *" for button in (body.buttons or [])))

    def test_project_registry_list_marks_active_per_chat(self) -> None:
        workspace_a = Path(self.tempdir.name) / "demo-a"
        workspace_a.mkdir(parents=True, exist_ok=True)
        (workspace_a / "README.md").write_text("# demo a\n", encoding="utf-8")
        workspace_b = Path(self.tempdir.name) / "demo-b"
        workspace_b.mkdir(parents=True, exist_ok=True)
        (workspace_b / "README.md").write_text("# demo b\n", encoding="utf-8")

        for chat_id, name, path in ((1, "demo-a", workspace_a), (2, "demo-b", workspace_b)):
            self.loop.run_until_complete(
                handle_command(
                    chat_id,
                    classify_request(MessageContext(chat_id=chat_id, text=f"/project register {name} {path}", command="project")),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )
            self.loop.run_until_complete(
                handle_command(
                    chat_id,
                    classify_request(MessageContext(chat_id=chat_id, text=f"/project use {name}", command="project")),
                    self.settings,
                    self.store,
                    self.agents,
                )
            )

        body_chat_1 = self.loop.run_until_complete(
            handle_command(1, classify_request(MessageContext(chat_id=1, text="/project list", command="project")), self.settings, self.store, self.agents)
        )
        body_chat_2 = self.loop.run_until_complete(
            handle_command(2, classify_request(MessageContext(chat_id=2, text="/project list", command="project")), self.settings, self.store, self.agents)
        )

        line_chat_1_a = next(line for line in body_chat_1.splitlines() if "demo-a |" in line)
        line_chat_1_b = next(line for line in body_chat_1.splitlines() if "demo-b |" in line)
        line_chat_2_a = next(line for line in body_chat_2.splitlines() if "demo-a |" in line)
        line_chat_2_b = next(line for line in body_chat_2.splitlines() if "demo-b |" in line)

        self.assertIn("  *active", line_chat_1_a)
        self.assertNotIn("  *active", line_chat_1_b)
        self.assertNotIn("  *active", line_chat_2_a)
        self.assertIn("  *active", line_chat_2_b)

    def test_project_current_prefers_chat_local_state_over_global_registry(self) -> None:
        workspace_a = Path(self.tempdir.name) / "demo-a"
        workspace_a.mkdir(parents=True, exist_ok=True)
        (workspace_a / "README.md").write_text("# demo a\n", encoding="utf-8")
        workspace_b = Path(self.tempdir.name) / "demo-b"
        workspace_b.mkdir(parents=True, exist_ok=True)
        (workspace_b / "README.md").write_text("# demo b\n", encoding="utf-8")

        self.loop.run_until_complete(
            handle_command(
                1,
                classify_request(MessageContext(chat_id=1, text=f"/project register demo-a {workspace_a}", command="project")),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.loop.run_until_complete(
            handle_command(
                1,
                classify_request(MessageContext(chat_id=1, text=f"/project register demo-b {workspace_b}", command="project")),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.loop.run_until_complete(
            handle_command(
                2,
                classify_request(MessageContext(chat_id=2, text="/project use demo-b", command="project")),
                self.settings,
                self.store,
                self.agents,
            )
        )
        self.store.set_project(1, "proj-chat-local", "demo-a", str(workspace_a))

        body = self.loop.run_until_complete(
            handle_command(1, classify_request(MessageContext(chat_id=1, text="/project current", command="project")), self.settings, self.store, self.agents)
        )

        self.assertIn("active project", body)
        self.assertIn("name: demo-a", body)
        self.assertIn(f"path: {workspace_a}", body)

    def test_doctor_command_returns_report(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/doctor", command="doctor"))
        with patch("robot.routing.build_doctor_report", return_value="robot doctor\nok"):
            body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("robot doctor", body)

    def test_contact_command_crud_flow(self) -> None:
        add_request = classify_request(
            MessageContext(chat_id=1, text="/contact add kevin kevincsl@gmail.com Kevin", command="contact")
        )
        add_body = self.loop.run_until_complete(handle_command(1, add_request, self.settings, self.store, self.agents))
        self.assertIn("Contact saved.", add_body)
        self.assertIn("key: kevin", add_body)

        list_request = classify_request(MessageContext(chat_id=1, text="/contact list", command="contact"))
        list_body = self.loop.run_until_complete(handle_command(1, list_request, self.settings, self.store, self.agents))
        self.assertIn("address book contacts: 1", list_body)
        self.assertIn("kevin", list_body)
        self.assertIn("kevincsl@gmail.com", list_body)

        show_request = classify_request(MessageContext(chat_id=1, text="/contact show kevin", command="contact"))
        show_body = self.loop.run_until_complete(handle_command(1, show_request, self.settings, self.store, self.agents))
        self.assertIn("contact", show_body)
        self.assertIn("name: Kevin", show_body)

        remove_request = classify_request(MessageContext(chat_id=1, text="/contact remove kevin", command="contact"))
        remove_body = self.loop.run_until_complete(handle_command(1, remove_request, self.settings, self.store, self.agents))
        self.assertIn("Contact removed: kevin", remove_body)

    def test_contact_command_alias_and_resolve(self) -> None:
        add_request = classify_request(
            MessageContext(chat_id=1, text="/contact add bob bobkaott@gmail.com Bob", command="contact")
        )
        _ = self.loop.run_until_complete(handle_command(1, add_request, self.settings, self.store, self.agents))

        alias_request = classify_request(
            MessageContext(chat_id=1, text="/contact alias bob add 高嘉辰", command="contact")
        )
        alias_body = self.loop.run_until_complete(handle_command(1, alias_request, self.settings, self.store, self.agents))
        self.assertIn("Contact alias updated.", alias_body)
        self.assertIn("高嘉辰", alias_body)

        resolve_request = classify_request(
            MessageContext(chat_id=1, text="/contact resolve bob 高嘉辰", command="contact")
        )
        resolve_body = self.loop.run_until_complete(
            handle_command(1, resolve_request, self.settings, self.store, self.agents)
        )
        self.assertIn("contact resolve", resolve_body)
        self.assertIn("bobkaott@gmail.com", resolve_body)

    def test_contact_command_validates_add_payload(self) -> None:
        invalid_request = classify_request(
            MessageContext(chat_id=1, text="/contact add bad! not-email Kevin", command="contact")
        )
        invalid_body = self.loop.run_until_complete(
            handle_command(1, invalid_request, self.settings, self.store, self.agents)
        )
        self.assertIn("Contact add failed:", invalid_body)

    def test_contact_command_unknown_subcommand_returns_usage(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/contact ping", command="contact"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("contact usage:", body)

    def test_mailcli_command_resolves_contact_aliases(self) -> None:
        _ = self.loop.run_until_complete(
            handle_command(
                1,
                classify_request(
                    MessageContext(chat_id=1, text="/contact add kevin kevincsl@gmail.com Kevin", command="contact")
                ),
                self.settings,
                self.store,
                self.agents,
            )
        )
        request = classify_request(
            MessageContext(
                chat_id=1,
                text="/mailcli -t kevin -s hello -bdy world",
                command="mailcli",
            )
        )
        with patch("robot.routing._run_sendmail", return_value=(True, "ok: True")) as mock_run:
            body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("mailcli sent.", body)
        called_args = mock_run.call_args.kwargs["args"]
        self.assertIn("-t", called_args)
        self.assertIn("kevincsl@gmail.com", called_args)

    def test_mailcli_command_blocks_unresolved_contact_alias(self) -> None:
        request = classify_request(
            MessageContext(
                chat_id=1,
                text="/mailcli -t unknown_alias -s hello -bdy world",
                command="mailcli",
            )
        )
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("mailcli recipient resolve failed.", body)

    def test_mailjson_command_resolves_contact_aliases(self) -> None:
        _ = self.loop.run_until_complete(
            handle_command(
                1,
                classify_request(
                    MessageContext(chat_id=1, text="/contact add kevin kevincsl@gmail.com Kevin", command="contact")
                ),
                self.settings,
                self.store,
                self.agents,
            )
        )
        _ = self.loop.run_until_complete(
            handle_command(
                1,
                classify_request(
                    MessageContext(chat_id=1, text="/contact add bob bobkaott@gmail.com Bob", command="contact")
                ),
                self.settings,
                self.store,
                self.agents,
            )
        )
        config_path = Path(self.tempdir.name) / "mail.json"
        config_path.write_text(
            json.dumps(
                {
                    "to": "kevin",
                    "cc": ["bob"],
                    "subject": "hello",
                    "body": "world",
                    "format": "plain",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        request = classify_request(
            MessageContext(chat_id=1, text=f"/mailjson {config_path}", command="mailjson")
        )
        with patch("robot.routing._run_sendmail", return_value=(True, "ok: True")) as mock_run:
            body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("mailjson sent.", body)
        resolved_path = Path(mock_run.call_args.kwargs["args"][0])
        parsed = json.loads(resolved_path.read_text(encoding="utf-8"))
        self.assertEqual(parsed["to"], "kevincsl@gmail.com")
        self.assertEqual(parsed["cc"], ["bobkaott@gmail.com"])

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

    def test_panic_clears_current_run_queue_and_schedules(self) -> None:
        self.store.set_agent_current_run(
            1,
            {
                "job_id": "job-current",
                "kind": "provider",
                "goal": "stuck hello",
            },
        )
        self.store.enqueue_agent_job(
            1,
            {
                "job_id": "job-queued",
                "kind": "provider",
                "goal": "queued work",
            },
        )
        self.store.add_agent_schedule(
            1,
            {
                "job_id": "job-scheduled",
                "kind": "auto_dev",
                "goal": "scheduled work",
                "run_at": "2026-05-01T10:00",
            },
        )
        request = classify_request(MessageContext(chat_id=1, text="/panic", command="panic"))
        with patch.object(self.agents, "stop", return_value=True) as mock_stop:
            body = self.loop.run_until_complete(handle_control(1, request, self.store, self.agents))
        mock_stop.assert_called_once_with(1)
        self.assertIn("Panic cleanup applied.", body)
        self.assertIn("stop_signal_sent: True", body)
        self.assertIn("cleared_current_run: True", body)
        self.assertIn("cleared_queue_jobs: 1", body)
        self.assertIn("cleared_scheduled_jobs: 1", body)
        self.assertIsNone(self.store.get_chat_state(1)["agent_current_run"])
        self.assertEqual(self.store.get_agent_queue(1), [])
        self.assertEqual(self.store.get_agent_schedules(1), [])

    def test_run_command_enqueues_job(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/run inspect repo", command="run"))
        body = self.loop.run_until_complete(handle_control(1, request, self.store, self.agents))
        self.assertIsInstance(body, AppEvent)
        assert isinstance(body, AppEvent)
        self.assertEqual(body.type, "status")
        self.assertIn("Provider run started.", body.text)
        self.assertIn("heartbeat: starting (first update within 1 second)", body.text)
        self.assertEqual(body.raw["status_key"], "heartbeat")
        self.assertTrue(body.raw["replace"])
        self.assertTrue(self.agents.is_running(1))

    def test_run_command_uses_user_mode_summary(self) -> None:
        self.store.set_display_mode(1, "user")
        request = classify_request(MessageContext(chat_id=1, text="/run inspect repo", command="run"))
        body = self.loop.run_until_complete(handle_control(1, request, self.store, self.agents))
        state = self.store.get_chat_state(1)
        self.assertIsInstance(body, AppEvent)
        assert isinstance(body, AppEvent)
        self.assertEqual(body.type, "status")
        self.assertEqual(body.text, f"📨 專案[{state['project_name']}] 已接收")
        self.assertEqual(body.raw["status_key"], "heartbeat")
        self.assertTrue(body.raw["replace"])

    def test_run_command_with_request_id_uses_request_scoped_heartbeat_key(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/run inspect repo", command="run", request_id="1-9"))
        body = self.loop.run_until_complete(handle_control(1, request, self.store, self.agents))
        self.assertIsInstance(body, AppEvent)
        assert isinstance(body, AppEvent)
        self.assertEqual(body.request_id, "1-9")
        self.assertEqual(body.raw["status_key"], "heartbeat:1-9")

    def test_agent_command_enqueues_auto_dev_job(self) -> None:
        object.__setattr__(self.settings, "auto_dev_command", ["python", "-c", "import time; time.sleep(30)"])
        request = classify_request(MessageContext(chat_id=1, text="/agent implement /queue", command="agent"))
        body = self.loop.run_until_complete(handle_control(1, request, self.store, self.agents))
        self.assertIsInstance(body, AppEvent)
        assert isinstance(body, AppEvent)
        self.assertEqual(body.type, "status")
        self.assertIn("Auto-dev run started.", body.text)
        self.assertIn("heartbeat: starting (first update within 1 second)", body.text)
        self.assertEqual(body.raw["status_key"], "heartbeat")
        self.assertTrue(body.raw["replace"])
        queue = self.store.get_agent_queue(1)
        self.assertEqual(len(queue), 0)
        current = self.store.get_chat_state(1)["agent_current_run"]
        self.assertIsInstance(current, dict)
        self.assertEqual(current["kind"], "auto_dev")

    def test_plain_text_agent_request_uses_user_mode_summary(self) -> None:
        self.store.set_display_mode(1, "user")
        body = self.loop.run_until_complete(
            handle_request(
                MessageContext(chat_id=1, text="Hi"),
                self.settings,
                self.store,
                self.agents,
            )
        )
        state = self.store.get_chat_state(1)
        self.assertIsInstance(body, AppEvent)
        assert isinstance(body, AppEvent)
        self.assertEqual(body.type, "status")
        self.assertEqual(body.text, f"📨 專案[{state['project_name']}] 已接收")
        self.assertEqual(body.raw["status_key"], "heartbeat")
        self.assertTrue(body.raw["replace"])

    def test_schedule_command_adds_auto_dev_schedule(self) -> None:
        request = classify_request(
            MessageContext(chat_id=1, text="/schedule 2026-04-09 10:00 implement queue", command="schedule")
        )
        body = self.loop.run_until_complete(handle_control(1, request, self.store, self.agents))
        self.assertIn("Scheduled auto-dev run.", body)
        schedules = self.store.get_agent_schedules(1)
        self.assertGreaterEqual(len(schedules), 1)
        self.assertEqual(schedules[-1]["kind"], "auto_dev")

    def test_schedule_command_syncs_google_event_when_enabled(self) -> None:
        object.__setattr__(self.settings, "google_calendar_enabled", True)
        request = classify_request(
            MessageContext(chat_id=1, text="/schedule 2026-04-09 10:00 implement queue", command="schedule")
        )
        with patch("robot.routing.upsert_google_calendar_schedule_event", return_value=("evt-1", True)) as mock_upsert:
            body = self.loop.run_until_complete(handle_control(1, request, self.store, self.agents))
        self.assertIn("Scheduled auto-dev run.", body)
        self.assertIn("google_calendar_sync: created", body)
        self.assertIn("gcal_event_id: evt-1", body)
        mock_upsert.assert_called_once()
        schedules = self.store.get_agent_schedules(1)
        self.assertEqual(schedules[-1].get("gcal_event_id"), "evt-1")

    def test_schedules_command_lists_jobs_with_usage_guidance(self) -> None:
        self.store.add_agent_schedule(
            1,
            {
                "job_id": "job-scheduled-1",
                "kind": "auto_dev",
                "goal": "scheduled goal",
                "run_at": "2026-05-01T10:00",
            },
        )
        request = classify_request(MessageContext(chat_id=1, text="/schedules", command="schedules"))
        body = self.loop.run_until_complete(handle_command(1, request, self.settings, self.store, self.agents))
        self.assertIn("agent schedules (cron jobs)", body)
        self.assertIn("scheduled: 1", body)
        self.assertIn("2026-05-01T10:00", body)
        self.assertIn("/schedule YYYY-MM-DD HH:MM <goal> (新增 cron job)", body)
        self.assertIn("/clearschedule (清除所有 cron jobs)", body)

    def test_clearschedule_alias_clears_scheduled_jobs(self) -> None:
        self.store.add_agent_schedule(
            1,
            {
                "job_id": "job-scheduled-1",
                "kind": "auto_dev",
                "goal": "scheduled goal",
                "run_at": "2026-05-01T10:00",
            },
        )
        request = classify_request(MessageContext(chat_id=1, text="/clearschedule", command="clearschedule"))
        self.assertEqual(request.kind, CONTROL_REQUEST)
        body = self.loop.run_until_complete(handle_control(1, request, self.store, self.agents))
        self.assertIn("Scheduled agent jobs cleared.", body)
        self.assertEqual(self.store.get_agent_schedules(1), [])

    def test_clearschedule_deletes_google_events_when_enabled(self) -> None:
        object.__setattr__(self.settings, "google_calendar_enabled", True)
        self.store.add_agent_schedule(
            1,
            {
                "job_id": "job-scheduled-1",
                "kind": "auto_dev",
                "goal": "scheduled goal",
                "run_at": "2026-05-01T10:00",
                "gcal_event_id": "evt-1",
            },
        )
        self.store.add_agent_schedule(
            1,
            {
                "job_id": "job-scheduled-2",
                "kind": "auto_dev",
                "goal": "scheduled goal2",
                "run_at": "2026-05-01T11:00",
            },
        )
        request = classify_request(MessageContext(chat_id=1, text="/clearschedule", command="clearschedule"))
        with patch("robot.routing.delete_google_calendar_schedule_event", return_value=True) as mock_delete:
            body = self.loop.run_until_complete(handle_control(1, request, self.store, self.agents))
        self.assertIn("Scheduled agent jobs cleared.", body)
        self.assertIn("google_events_targeted: 1", body)
        self.assertIn("google_events_deleted: 1", body)
        self.assertIn("google_delete_errors: 0", body)
        mock_delete.assert_called_once_with(self.settings, event_id="evt-1")
        self.assertEqual(self.store.get_agent_schedules(1), [])

    def test_schedule_sync_command_runs_google_sync_when_enabled(self) -> None:
        object.__setattr__(self.settings, "google_calendar_enabled", True)
        self.store.add_agent_schedule(
            1,
            {
                "job_id": "job-1",
                "kind": "auto_dev",
                "goal": "sync goal",
                "run_at": "2026-05-01T10:00",
            },
        )
        request = classify_request(MessageContext(chat_id=1, text="/schedule sync push 14 80", command="schedule"))
        with patch(
            "robot.routing.sync_schedule_jobs_with_google",
            return_value=(
                [
                    {
                        "job_id": "job-1",
                        "kind": "auto_dev",
                        "goal": "sync goal",
                        "run_at": "2026-05-01T10:00",
                        "gcal_event_id": "evt-1",
                    }
                ],
                {
                    "mode": "push",
                    "local_before": 1,
                    "local_after": 1,
                    "pushed_created": 1,
                    "pushed_updated": 0,
                    "push_errors": 0,
                    "pulled_created": 0,
                    "pulled_updated": 0,
                    "pull_errors": 0,
                    "errors": [],
                },
            ),
        ) as mock_sync:
            body = self.loop.run_until_complete(handle_control(1, request, self.store, self.agents))
        self.assertIn("Schedule sync completed.", body)
        self.assertIn("mode: push", body)
        self.assertIn("days: 14", body)
        self.assertIn("limit: 80", body)
        mock_sync.assert_called_once()
        self.assertEqual(mock_sync.call_args.kwargs["mode"], "push")
        self.assertEqual(mock_sync.call_args.kwargs["days"], 14)
        self.assertEqual(mock_sync.call_args.kwargs["limit"], 80)
        self.assertEqual(self.store.get_agent_schedules(1)[0].get("gcal_event_id"), "evt-1")

    def test_schedule_sync_command_requires_google_enabled(self) -> None:
        object.__setattr__(self.settings, "google_calendar_enabled", False)
        request = classify_request(MessageContext(chat_id=1, text="/schedule sync", command="schedule"))
        body = self.loop.run_until_complete(handle_control(1, request, self.store, self.agents))
        self.assertEqual(body, "Google Calendar sync is disabled. Set ROBOT_GOOGLE_CALENDAR_ENABLED=1 first.")

    def test_schedule_sync_command_validates_payload(self) -> None:
        object.__setattr__(self.settings, "google_calendar_enabled", True)

        request_usage = classify_request(MessageContext(chat_id=1, text="/schedule sync x y z q", command="schedule"))
        body_usage = self.loop.run_until_complete(handle_control(1, request_usage, self.store, self.agents))
        self.assertEqual(body_usage, "Usage: /schedule sync [push|pull|both] [days] [limit]")

        request_days = classify_request(MessageContext(chat_id=1, text="/schedule sync pull 0", command="schedule"))
        body_days = self.loop.run_until_complete(handle_control(1, request_days, self.store, self.agents))
        self.assertEqual(body_days, "days must be between 1 and 120.")

        request_limit = classify_request(MessageContext(chat_id=1, text="/schedule sync push 7 700", command="schedule"))
        body_limit = self.loop.run_until_complete(handle_control(1, request_limit, self.store, self.agents))
        self.assertEqual(body_limit, "limit must be between 1 and 500.")

    def test_schedule_command_without_payload_returns_usage_without_argparse_stderr(self) -> None:
        request = classify_request(MessageContext(chat_id=1, text="/schedule", command="schedule"))
        stderr_buffer = io.StringIO()
        with contextlib.redirect_stderr(stderr_buffer):
            body = self.loop.run_until_complete(handle_control(1, request, self.store, self.agents))
        self.assertIn("Usage: /schedule YYYY-MM-DD HH:MM", body)
        self.assertEqual(stderr_buffer.getvalue(), "")

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
        stop_request = classify_request(MessageContext(chat_id=1, text="/stop", command="stop"))
        body = self.loop.run_until_complete(handle_control(1, stop_request, self.store, self.agents))
        self.assertIn("Stop signal sent", body)
        self.loop.run_until_complete(asyncio.sleep(0.8))
        self.assertFalse(self.agents.is_running(1))
        last_run = self.store.get_chat_state(1)["agent_last_run"]
        self.assertEqual(last_run["status"], "stopped")

    def test_agent_emit_can_carry_status_metadata(self) -> None:
        captured: list[object] = []

        class DummyQueue:
            def put_nowait(self, event) -> None:
                captured.append(event)

        class DummySupervisor:
            _event_queue = DummyQueue()

        self.agents.attach_supervisor(DummySupervisor())
        self.loop.run_until_complete(
            self.agents._emit(
                1,
                "heartbeat",
                event_type="status",
                raw={"status_key": "heartbeat", "replace": True},
            )
        )
        self.assertEqual(len(captured), 1)
        event = captured[0]
        self.assertEqual(event.type, "status")
        self.assertEqual(event.raw["status_key"], "heartbeat")
        self.assertTrue(event.raw["replace"])


if __name__ == "__main__":
    unittest.main()
