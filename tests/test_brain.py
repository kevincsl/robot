from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from robot.brain import (
    archive_schedule_note,
    archive_past_due_schedule_notes,
    append_to_daily,
    build_decision_support_brief,
    build_schedule_brief,
    build_schedule_range_brief,
    collect_brain_reminders,
    create_schedule_note,
    create_inbox_note,
    create_knowledge_note_from_text,
    create_project_note_from_text,
    create_resource_note_from_text,
    get_active_or_next_schedule,
    list_schedule_notes,
    parse_natural_language_schedule,
    parse_schedule_update_details,
    read_daily,
    read_note,
    search_vault,
    update_schedule_note,
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
        (self.vault / "06 Schedule").mkdir(parents=True, exist_ok=True)
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
        (self.vault / "98 Templates" / "Template - Schedule Note.md").write_text(
            "---\n"
            "type: schedule\n"
            "status: active\n"
            "created:\n"
            "updated:\n"
            "project:\n"
            "topic:\n"
            "tags:\n"
            "source:\n"
            "review: true\n"
            "date:\n"
            "time:\n"
            "recurrence_type:\n"
            "recurrence_value:\n"
            "---\n\n"
            "# Schedule\n",
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
            relative_path = append_to_daily(self.settings, "?皜?????剜?啁?蹓?")

        self.assertTrue(relative_path.startswith("01 Daily Notes/"))
        body = read_daily(self.settings)
        self.assertIn("?皜?????剜?啁?蹓?", body)
        self.assertIn("type: daily", body)

    def test_create_inbox_note_sets_defaults(self) -> None:
        with patch("robot.brain._run_brain_command", side_effect=subprocess.CalledProcessError(1, ["obsidian"])):
            relative_path = create_inbox_note(self.settings, "????謕?賹???寞?")

        body = (self.vault / relative_path).read_text(encoding="utf-8")
        self.assertIn("????謕?賹???寞?", body)
        self.assertIn("type: inbox", body)

    def test_read_note_and_search_fall_back_to_filesystem(self) -> None:
        with patch("robot.brain._run_brain_command", side_effect=subprocess.CalledProcessError(1, ["obsidian"])):
            body = read_note(self.settings, "03 Knowledge/Obsidian.md")
            matches = search_vault(self.settings, "markdown", limit=5)

        self.assertIn("Obsidian", body)
        self.assertEqual(matches, ["03 Knowledge/Obsidian.md"])

    def test_create_project_note_from_text_appends_source(self) -> None:
        with patch("robot.brain._run_brain_command", side_effect=subprocess.CalledProcessError(1, ["obsidian"])):
            relative_path = create_project_note_from_text(self.settings, "Roadmap", "source project text")

        body = (self.vault / relative_path).read_text(encoding="utf-8")
        self.assertIn("type: project", body)
        self.assertIn("project: Roadmap", body)
        self.assertIn("source project text", body)

    def test_create_knowledge_note_from_text_appends_source(self) -> None:
        with patch("robot.brain._run_brain_command", side_effect=subprocess.CalledProcessError(1, ["obsidian"])):
            relative_path = create_knowledge_note_from_text(self.settings, "Prompt Engineering", "source knowledge text")

        body = (self.vault / relative_path).read_text(encoding="utf-8")
        self.assertIn("type: knowledge", body)
        self.assertIn("source knowledge text", body)

    def test_create_resource_note_from_text_appends_source(self) -> None:
        with patch("robot.brain._run_brain_command", side_effect=subprocess.CalledProcessError(1, ["obsidian"])):
            relative_path = create_resource_note_from_text(self.settings, "Article Notes", "source resource text")

        body = (self.vault / relative_path).read_text(encoding="utf-8")
        self.assertIn("type: resource", body)
        self.assertIn("source resource text", body)

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
        self.assertIn("Should I use Obsidian?", brief)

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
        self.assertIn("Decision Review", joined)



    def test_parse_natural_language_schedule_supports_today_evening_half_hour(self) -> None:
        parsed = parse_natural_language_schedule(
            "今天下午6點半要吃藥",
            now=datetime(2026, 4, 12, 9, 0),
        )

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["title"], "吃藥")
        self.assertEqual(parsed["date_text"], "2026-04-12")
        self.assertEqual(parsed["time_text"], "18:30")

    def test_parse_natural_language_schedule_supports_point_and_minutes(self) -> None:
        parsed = parse_natural_language_schedule(
            "今天晚上23點40分要睡覺",
            now=datetime(2026, 4, 12, 9, 0),
        )

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["title"], "睡覺")
        self.assertEqual(parsed["date_text"], "2026-04-12")
        self.assertEqual(parsed["time_text"], "23:40")

    def test_parse_natural_language_schedule_supports_relative_minutes(self) -> None:
        parsed = parse_natural_language_schedule(
            "30分鐘後要休息",
            now=datetime(2026, 4, 12, 9, 10),
        )

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["title"], "休息")
        self.assertEqual(parsed["date_text"], "2026-04-12")
        self.assertEqual(parsed["time_text"], "09:40")

    def test_parse_natural_language_schedule_supports_tomorrow_morning(self) -> None:
        parsed = parse_natural_language_schedule(
            "明天早上9點開會",
            now=datetime(2026, 4, 12, 21, 0),
        )

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["title"], "開會")
        self.assertEqual(parsed["date_text"], "2026-04-13")
        self.assertEqual(parsed["time_text"], "09:00")

    def test_parse_natural_language_schedule_supports_next_weekday(self) -> None:
        parsed = parse_natural_language_schedule(
            "下週二下午3點交報告",
            now=datetime(2026, 4, 13, 9, 0),
        )

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["title"], "交報告")
        self.assertEqual(parsed["date_text"], "2026-04-21")
        self.assertEqual(parsed["time_text"], "15:00")

    def test_schedule_cache_is_invalidated_after_update(self) -> None:
        with patch("robot.brain._run_brain_command", side_effect=subprocess.CalledProcessError(1, ["obsidian"])):
            relative_path = create_schedule_note(
                self.settings,
                "升學輔導會議",
                "2026-04-20",
                "12:00",
            )
            first = list_schedule_notes(self.settings, limit=10)
            update_schedule_note(self.settings, relative_path, time_text="13:00")
            second = list_schedule_notes(self.settings, limit=10)

        self.assertEqual(first[0]["time"], "12:00")
        self.assertEqual(second[0]["time"], "13:00")

    def test_parse_natural_language_schedule_supports_daily_recurrence(self) -> None:
        parsed = parse_natural_language_schedule(
            "每天早上7點吃藥",
            now=datetime(2026, 4, 13, 9, 0),
        )

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["title"], "吃藥")
        self.assertEqual(parsed["time_text"], "07:00")
        self.assertEqual(parsed["recurrence_type"], "daily")
        self.assertEqual(parsed["recurrence_value"], "daily")

    def test_parse_natural_language_schedule_supports_weekly_recurrence(self) -> None:
        parsed = parse_natural_language_schedule(
            "每週三晚上8點吃火鍋",
            now=datetime(2026, 4, 13, 9, 0),
        )

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["title"], "吃火鍋")
        self.assertEqual(parsed["date_text"], "2026-04-15")
        self.assertEqual(parsed["time_text"], "20:00")
        self.assertEqual(parsed["recurrence_type"], "weekly")
        self.assertEqual(parsed["recurrence_value"], "2")

    def test_parse_natural_language_schedule_supports_monthly_recurrence(self) -> None:
        parsed = parse_natural_language_schedule(
            "每月1號繳房租",
            now=datetime(2026, 4, 13, 9, 0),
        )

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["title"], "繳房租")
        self.assertEqual(parsed["date_text"], "2026-05-01")
        self.assertEqual(parsed["time_text"], "")
        self.assertEqual(parsed["recurrence_type"], "monthly")
        self.assertEqual(parsed["recurrence_value"], "1")

    def test_parse_natural_language_schedule_supports_chinese_month_day(self) -> None:
        parsed = parse_natural_language_schedule(
            "4月20日中午12點有一個升學輔導會議在第一會議室",
            now=datetime(2026, 4, 13, 9, 0),
        )

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["title"], "升學輔導會議在第一會議室")
        self.assertEqual(parsed["date_text"], "2026-04-20")
        self.assertEqual(parsed["time_text"], "12:00")

    def test_parse_schedule_update_details_supports_time_only_update(self) -> None:
        parsed = parse_schedule_update_details(
            "下午1點",
            current_title="升學輔導會議在第一會議室",
            now=datetime(2026, 4, 13, 9, 0),
        )

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["date_text"], "")
        self.assertEqual(parsed["time_text"], "13:00")
        self.assertEqual(parsed["title"], "升學輔導會議在第一會議室")

    def test_parse_schedule_update_details_supports_recurring_update(self) -> None:
        parsed = parse_schedule_update_details(
            "每天早上8點",
            current_title="吃藥",
            now=datetime(2026, 4, 13, 9, 0),
        )

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["time_text"], "08:00")
        self.assertEqual(parsed["recurrence_type"], "daily")
        self.assertEqual(parsed["recurrence_value"], "daily")

    def test_schedule_brief_shows_daily_recurrence(self) -> None:
        (self.vault / "06 Schedule" / "吃藥.md").write_text(
            "---\n"
            "type: schedule\n"
            "date: 2026-04-13\n"
            "time: 07:30\n"
            "recurrence_type: daily\n"
            "recurrence_value: daily\n"
            "---\n\n"
            "# 吃藥\n",
            encoding="utf-8",
        )

        body = build_schedule_brief(self.settings, today_only=False, limit=10)

        self.assertIn("每天 07:30 | 吃藥", body)
        self.assertIn("06 Schedule/吃藥.md", body)

    def test_today_schedule_brief_includes_daily_recurrence(self) -> None:
        (self.vault / "06 Schedule" / "吃藥.md").write_text(
            "---\n"
            "type: schedule\n"
            "date: 2026-04-01\n"
            "time: 07:30\n"
            "recurrence_type: daily\n"
            "recurrence_value: daily\n"
            "---\n\n"
            "# 吃藥\n",
            encoding="utf-8",
        )

        body = build_schedule_brief(self.settings, today_only=True, limit=10)

        self.assertIn("每天 07:30 | 吃藥", body)

    def test_next_schedule_expands_daily_recurrence(self) -> None:
        (self.vault / "06 Schedule" / "吃藥.md").write_text(
            "---\n"
            "type: schedule\n"
            "date: 2026-04-01\n"
            "time: 07:30\n"
            "recurrence_type: daily\n"
            "recurrence_value: daily\n"
            "---\n\n"
            "# 吃藥\n",
            encoding="utf-8",
        )

        item = get_active_or_next_schedule(
            self.settings,
            now=datetime(2026, 4, 13, 7, 20),
            lookahead_minutes=20,
        )

        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item["title"], "吃藥")
        self.assertEqual(item["date"], "2026-04-13")
        self.assertEqual(item["time"], "07:30")
        self.assertEqual(item["recurrence"], "每天")

    def test_next_schedule_accepts_fullwidth_time_colon(self) -> None:
        (self.vault / "06 Schedule" / "喝水.md").write_text(
            "---\n"
            "type: schedule\n"
            "date: 2026-04-13\n"
            "time: 15：30\n"
            "---\n\n"
            "# 喝水\n",
            encoding="utf-8",
        )

        item = get_active_or_next_schedule(
            self.settings,
            now=datetime(2026, 4, 13, 15, 20),
            lookahead_minutes=20,
        )

        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item["title"], "喝水")
        self.assertEqual(item["time"], "15：30")

    def test_week_schedule_range_expands_daily_recurrence(self) -> None:
        (self.vault / "06 Schedule" / "吃藥.md").write_text(
            "---\n"
            "type: schedule\n"
            "date: 2026-04-01\n"
            "time: 07:30\n"
            "recurrence_type: daily\n"
            "recurrence_value: daily\n"
            "---\n\n"
            "# 吃藥\n",
            encoding="utf-8",
        )

        body = build_schedule_range_brief(
            self.settings,
            period="week",
            now=datetime(2026, 4, 13, 9, 0),
            limit=20,
        )

        self.assertIn("本週行程 2026-04-13 ~ 2026-04-19", body)
        self.assertIn("2026-04-13 07:30 | 吃藥 (每天)", body)
        self.assertIn("2026-04-19 07:30 | 吃藥 (每天)", body)

    def test_next_week_schedule_range_has_next_week_title(self) -> None:
        (self.vault / "06 Schedule" / "會議.md").write_text(
            "---\n"
            "type: schedule\n"
            "date: 2026-04-20\n"
            "time: 12:00\n"
            "---\n\n"
            "# 會議\n",
            encoding="utf-8",
        )

        body = build_schedule_range_brief(
            self.settings,
            period="next_week",
            now=datetime(2026, 4, 13, 9, 0),
            limit=20,
        )

        self.assertIn("下週行程 2026-04-20 ~ 2026-04-26", body)
        self.assertIn("2026-04-20 12:00 | 會議", body)

    def test_month_schedule_range_includes_monthly_recurrence(self) -> None:
        (self.vault / "06 Schedule" / "繳房租.md").write_text(
            "---\n"
            "type: schedule\n"
            "date: 2026-04-01\n"
            "time: 09:00\n"
            "recurrence_type: monthly\n"
            "recurrence_value: 1\n"
            "---\n\n"
            "# 繳房租\n",
            encoding="utf-8",
        )

        body = build_schedule_range_brief(
            self.settings,
            period="month",
            now=datetime(2026, 4, 13, 9, 0),
            limit=20,
        )

        self.assertIn("本月行程 2026-04", body)
        self.assertIn("2026-04-01 09:00 | 繳房租 (每月1號)", body)

    def test_archive_schedule_note_moves_file_to_archive(self) -> None:
        source = self.vault / "06 Schedule" / "吃藥.md"
        source.write_text("# 吃藥\n", encoding="utf-8")

        archived = archive_schedule_note(self.settings, "06 Schedule/吃藥.md")

        self.assertEqual(archived, "99 Archive/Deleted Schedule/吃藥.md")
        self.assertFalse(source.exists())
        self.assertTrue((self.vault / archived).exists())

    def test_archive_past_due_schedule_notes_archives_only_one_time_past_items(self) -> None:
        (self.vault / "06 Schedule" / "休息.md").write_text(
            "---\n"
            "type: schedule\n"
            "date: 2026-04-13\n"
            "time: 01:10\n"
            "---\n\n"
            "# 休息\n",
            encoding="utf-8",
        )
        (self.vault / "06 Schedule" / "吃藥.md").write_text(
            "---\n"
            "type: schedule\n"
            "date: 2026-04-01\n"
            "time: 07:30\n"
            "recurrence_type: daily\n"
            "recurrence_value: daily\n"
            "---\n\n"
            "# 吃藥\n",
            encoding="utf-8",
        )

        archived = archive_past_due_schedule_notes(
            self.settings,
            now=datetime(2026, 4, 13, 9, 0),
            limit=50,
        )

        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0]["title"], "休息")
        self.assertFalse((self.vault / "06 Schedule" / "休息.md").exists())
        self.assertTrue((self.vault / "99 Archive" / "Deleted Schedule" / "休息.md").exists())
        self.assertTrue((self.vault / "06 Schedule" / "吃藥.md").exists())

    def test_update_schedule_note_updates_properties(self) -> None:
        note = self.vault / "06 Schedule" / "會議.md"
        note.write_text(
            "---\n"
            "type: schedule\n"
            "date: 2026-04-20\n"
            "time: 12:00\n"
            "recurrence_type: \n"
            "recurrence_value: \n"
            "---\n\n"
            "# 會議\n",
            encoding="utf-8",
        )

        update_schedule_note(
            self.settings,
            "06 Schedule/會議.md",
            time_text="13:00",
            recurrence_type="daily",
            recurrence_value="daily",
        )

        body = note.read_text(encoding="utf-8")
        self.assertIn("time: 13:00", body)
        self.assertIn("recurrence_type: daily", body)
        self.assertIn("recurrence_value: daily", body)
if __name__ == "__main__":
    unittest.main()

