from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from robot.brain import (
    append_to_daily,
    build_decision_support_brief,
    collect_brain_reminders,
    create_inbox_note,
    create_knowledge_note_from_text,
    create_project_note_from_text,
    create_resource_note_from_text,
    read_daily,
    read_note,
    search_vault,
)
from robot.config import load_settings


class BrainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.vault = self.root / "secondbrain"
        (self.vault / "98 Templates").mkdir(parents=True, exist_ok=True)
        (self.vault / "01 Daily Notes").mkdir(parents=True, exist_ok=True)
        (self.vault / "02 Projects").mkdir(parents=True, exist_ok=True)
        (self.vault / "03 Knowledge").mkdir(parents=True, exist_ok=True)
        (self.vault / "04 Resources").mkdir(parents=True, exist_ok=True)
        (self.vault / "00 Inbox").mkdir(parents=True, exist_ok=True)
        (self.vault / "07 Decision Support").mkdir(parents=True, exist_ok=True)

        (self.vault / "98 Templates" / "Template - Daily Note.md").write_text(
            "---\n"
            "type: daily\n"
            "status: active\n"
            "created:\n"
            "updated:\n"
            "project:\n"
            "topic:\n"
            "tags:\n"
            "source:\n"
            "review: true\n"
            "---\n\n"
            "# Daily Note - {{date:YYYY-MM-DD}}\n",
            encoding="utf-8",
        )
        (self.vault / "98 Templates" / "Template - Project Note.md").write_text(
            "---\n"
            "type: project\n"
            "status: active\n"
            "created:\n"
            "updated:\n"
            "project:\n"
            "topic:\n"
            "tags:\n"
            "source:\n"
            "review: true\n"
            "---\n\n"
            "# Project\n",
            encoding="utf-8",
        )
        (self.vault / "98 Templates" / "Template - Knowledge Note.md").write_text(
            "---\n"
            "type: knowledge\n"
            "status: active\n"
            "created:\n"
            "updated:\n"
            "project:\n"
            "topic:\n"
            "tags:\n"
            "source:\n"
            "review: true\n"
            "---\n\n"
            "# Knowledge\n",
            encoding="utf-8",
        )
        (self.vault / "98 Templates" / "Template - Resource Note.md").write_text(
            "---\n"
            "type: resource\n"
            "status: active\n"
            "created:\n"
            "updated:\n"
            "project:\n"
            "topic:\n"
            "tags:\n"
            "source:\n"
            "review: true\n"
            "---\n\n"
            "# Resource\n",
            encoding="utf-8",
        )
        (self.vault / "03 Knowledge" / "Obsidian.md").write_text(
            "# Obsidian\n\nObsidian is a markdown-based knowledge system.\n",
            encoding="utf-8",
        )
        self.settings = load_settings(self.root)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_append_to_daily_falls_back_to_filesystem(self) -> None:
        with patch("robot.brain._run_brain_command", side_effect=subprocess.CalledProcessError(1, ["obsidian"])):
            relative_path = append_to_daily(self.settings, "整理第二大腦流程")

        self.assertTrue(relative_path.startswith("01 Daily Notes/"))
        body = read_daily(self.settings)
        self.assertIn("整理第二大腦流程", body)
        self.assertIn("type: daily", body)

    def test_create_inbox_note_sets_defaults(self) -> None:
        with patch("robot.brain._run_brain_command", side_effect=subprocess.CalledProcessError(1, ["obsidian"])):
            relative_path = create_inbox_note(self.settings, "收集這段原始內容")

        body = (self.vault / relative_path).read_text(encoding="utf-8")
        self.assertIn("收集這段原始內容", body)
        self.assertIn("type: inbox", body)

    def test_read_note_and_search_fall_back_to_filesystem(self) -> None:
        with patch("robot.brain._run_brain_command", side_effect=subprocess.CalledProcessError(1, ["obsidian"])):
            body = read_note(self.settings, "03 Knowledge/Obsidian.md")
            matches = search_vault(self.settings, "markdown", limit=5)

        self.assertIn("Obsidian", body)
        self.assertEqual(matches, ["03 Knowledge/Obsidian.md"])

    def test_create_project_note_from_text_appends_source(self) -> None:
        with patch("robot.brain._run_brain_command", side_effect=subprocess.CalledProcessError(1, ["obsidian"])):
            relative_path = create_project_note_from_text(self.settings, "Roadmap", "這是一段專案整理內容")

        body = (self.vault / relative_path).read_text(encoding="utf-8")
        self.assertIn("type: project", body)
        self.assertIn("project: Roadmap", body)
        self.assertIn("這是一段專案整理內容", body)

    def test_create_knowledge_note_from_text_appends_source(self) -> None:
        with patch("robot.brain._run_brain_command", side_effect=subprocess.CalledProcessError(1, ["obsidian"])):
            relative_path = create_knowledge_note_from_text(self.settings, "Prompt Engineering", "這是一段知識整理內容")

        body = (self.vault / relative_path).read_text(encoding="utf-8")
        self.assertIn("type: knowledge", body)
        self.assertIn("這是一段知識整理內容", body)

    def test_create_resource_note_from_text_appends_source(self) -> None:
        with patch("robot.brain._run_brain_command", side_effect=subprocess.CalledProcessError(1, ["obsidian"])):
            relative_path = create_resource_note_from_text(self.settings, "Article Notes", "這是一段資源整理內容")

        body = (self.vault / relative_path).read_text(encoding="utf-8")
        self.assertIn("type: resource", body)
        self.assertIn("這是一段資源整理內容", body)

    def test_build_decision_support_brief_returns_structured_sections(self) -> None:
        with patch(
            "robot.brain.search_vault_context",
            return_value=[
                {
                    "file": "03 Knowledge/Obsidian.md",
                    "matches": [{"text": "Obsidian is a markdown-based knowledge system."}],
                }
            ],
        ):
            related, brief = build_decision_support_brief(self.settings, "Should I use Obsidian?", limit=5)

        self.assertEqual(related, ["03 Knowledge/Obsidian.md"])
        self.assertIn("問題定義", brief)
        self.assertIn("支持理由", brief)
        self.assertIn("反對理由", brief)
        self.assertIn("風險與盲點", brief)
        self.assertIn("建議下一步", brief)

    def test_collect_brain_reminders_detects_stale_inbox_and_repeated_topic(self) -> None:
        inbox_note = self.vault / "00 Inbox" / "old.md"
        inbox_note.write_text("# Inbox\n\nold content\n", encoding="utf-8")
        two_days_ago = (datetime.now() - timedelta(days=2)).timestamp()
        os.utime(inbox_note, (two_days_ago, two_days_ago))

        decision_note = self.vault / "07 Decision Support" / "Decision Review - old.md"
        decision_note.write_text("# Decision Review\n", encoding="utf-8")
        four_days_ago = (datetime.now() - timedelta(days=4)).timestamp()
        os.utime(decision_note, (four_days_ago, four_days_ago))

        for idx in range(2):
            daily = self.vault / "01 Daily Notes" / f"2026-04-0{idx + 1}.md"
            daily.write_text(
                "---\n"
                "topic: product\n"
                "---\n\n"
                f"# Daily {idx}\n",
                encoding="utf-8",
            )

        with patch("robot.brain._run_brain_command", side_effect=subprocess.CalledProcessError(1, ["obsidian"])):
            reminders = collect_brain_reminders(self.settings, limit=5)

        joined = "\n".join(reminders)
        self.assertIn("Inbox", joined)
        self.assertIn("超過 1 天未整理", joined)
        self.assertIn("Decision Review", joined)
        self.assertIn("重複出現的主題", joined)


if __name__ == "__main__":
    unittest.main()
