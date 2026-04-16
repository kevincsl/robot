from __future__ import annotations

import json
import re
import subprocess
import time
from collections import Counter
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from markitdown import MarkItDown

from robot.config import Settings


INVALID_PATH_CHARS = re.compile(r'[<>:"/\\|?*]+')
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
TOPIC_RE = re.compile(r"topic:\s*(.+)")
CLI_TIMEOUT_SECONDS = 5
SCHEDULE_CACHE_TTL_SECONDS = 15.0
_SCHEDULE_NOTES_CACHE: dict[str, dict[str, object]] = {}
WEEKDAY_NAMES = ["一", "二", "三", "四", "五", "六", "日"]


def _run_brain_command(settings: Settings, *args: str) -> str:
    command = [*settings.brain_cli_command, *args, f"vault={settings.brain_vault_name}"]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        timeout=CLI_TIMEOUT_SECONDS,
    )
    return (completed.stdout or "").strip()


def _try_cli(settings: Settings, *args: str) -> str | None:
    try:
        return _run_brain_command(settings, *args)
    except (FileNotFoundError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def _vault_root(settings: Settings) -> Path:
    if settings.brain_vault_path is None:
        raise RuntimeError("Brain vault path is not configured.")
    return settings.brain_vault_path


def _relative_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _safe_title(text: str, fallback: str) -> str:
    cleaned = INVALID_PATH_CHARS.sub("-", text.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or fallback


def _read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _invalidate_schedule_cache(settings: Settings) -> None:
    _SCHEDULE_NOTES_CACHE.pop(str(_vault_root(settings).resolve()), None)


def _template_path(settings: Settings, template_name: str) -> Path:
    return _vault_root(settings) / "98 Templates" / f"{template_name}.md"


def _render_template(settings: Settings, template_name: str) -> str:
    content = _read_file(_template_path(settings, template_name))
    today = datetime.now().strftime("%Y-%m-%d")
    return content.replace("{{date:YYYY-MM-DD}}", today)


def _daily_note_path(settings: Settings) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d")
    return _vault_root(settings) / "01 Daily Notes" / f"{stamp}.md"


def _ensure_daily_note(settings: Settings) -> Path:
    path = _daily_note_path(settings)
    if path.exists():
        return path
    try:
        content = _render_template(settings, "Template - Daily Note")
    except FileNotFoundError:
        today = datetime.now().strftime("%Y-%m-%d")
        content = f"# Daily Note - {today}\n"
    _write_file(path, content.rstrip() + "\n")
    return path


def _create_note_direct(settings: Settings, relative_path: str, content: str | None = None, template: str | None = None) -> str:
    vault_root = _vault_root(settings)
    path = vault_root / Path(relative_path)
    if content is None and template is not None:
        content = _render_template(settings, template)
    _write_file(path, (content or "").rstrip() + "\n")
    return _relative_posix(path, vault_root)


def _append_to_note_direct(settings: Settings, relative_path: str, content: str) -> None:
    vault_root = _vault_root(settings)
    path = vault_root / Path(relative_path)
    existing = _read_file(path).rstrip() if path.exists() else ""
    updated = f"{existing}\n{content.rstrip()}\n" if existing else f"{content.rstrip()}\n"
    _write_file(path, updated)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    body = text[match.end():]
    frontmatter: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        frontmatter[key.strip()] = value.strip()
    return frontmatter, body


def _serialize_frontmatter(frontmatter: dict[str, str]) -> str:
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _set_property_direct(settings: Settings, relative_path: str, name: str, value: str) -> None:
    vault_root = _vault_root(settings)
    path = vault_root / Path(relative_path)
    text = _read_file(path) if path.exists() else ""
    frontmatter, body = _parse_frontmatter(text)
    frontmatter[name] = value
    new_text = _serialize_frontmatter(frontmatter) + ("\n" + body.lstrip("\n") if body else "")
    _write_file(path, new_text.rstrip() + "\n")


def set_note_property(settings: Settings, relative_path: str, name: str, value: str, type_name: str = "text") -> None:
    result = _try_cli(settings, "property:set", f"path={relative_path}", f"name={name}", f"value={value}", f"type={type_name}")
    if result is not None:
        return
    _set_property_direct(settings, relative_path, name, value)


def apply_note_defaults(
    settings: Settings,
    relative_path: str,
    *,
    note_type: str,
    title: str,
    topic: str = "",
    project: str = "",
    review: bool = True,
) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    set_note_property(settings, relative_path, "type", note_type)
    set_note_property(settings, relative_path, "status", "active")
    set_note_property(settings, relative_path, "created", today, type_name="date")
    set_note_property(settings, relative_path, "updated", today, type_name="date")
    set_note_property(settings, relative_path, "review", "true" if review else "false", type_name="checkbox")
    if topic:
        set_note_property(settings, relative_path, "topic", topic)
    if project:
        set_note_property(settings, relative_path, "project", project)


def _search_vault_direct(settings: Settings, query: str, limit: int = 10) -> list[str]:
    needle = query.strip().lower()
    if not needle:
        return []
    vault_root = _vault_root(settings)
    matches: list[str] = []
    for path in vault_root.rglob("*.md"):
        try:
            haystack = _read_file(path).lower()
        except OSError:
            continue
        if needle in haystack or needle in path.name.lower():
            matches.append(_relative_posix(path, vault_root))
            if len(matches) >= limit:
                break
    return matches


def _search_vault_context_direct(settings: Settings, query: str, limit: int = 5) -> list[dict[str, object]]:
    needle = query.strip().lower()
    if not needle:
        return []
    vault_root = _vault_root(settings)
    results: list[dict[str, object]] = []
    for path in vault_root.rglob("*.md"):
        try:
            lines = _read_file(path).splitlines()
        except OSError:
            continue
        matched_lines = [line.strip() for line in lines if needle in line.lower()]
        if not matched_lines and needle not in path.name.lower():
            continue
        results.append({"file": _relative_posix(path, vault_root), "matches": [{"text": line} for line in matched_lines[:2]]})
        if len(results) >= limit:
            break
    return results


def append_to_daily(settings: Settings, text: str) -> str:
    timestamp = datetime.now().strftime("%H:%M")
    content = f"- [{timestamp}] {text.strip()}"
    result = _try_cli(settings, "daily:append", f"content={content}")
    if result is not None:
        path = _try_cli(settings, "daily:path")
        relative = path or f"01 Daily Notes/{datetime.now().strftime('%Y-%m-%d')}.md"
        apply_note_defaults(settings, relative, note_type="daily", title=Path(relative).stem, topic="daily", review=True)
        return relative
    path = _ensure_daily_note(settings)
    existing = _read_file(path).rstrip()
    updated = f"{existing}\n\n{content}\n" if existing else f"{content}\n"
    _write_file(path, updated)
    relative = _relative_posix(path, _vault_root(settings))
    apply_note_defaults(settings, relative, note_type="daily", title=path.stem, topic="daily", review=True)
    return relative


def read_daily(settings: Settings) -> str:
    result = _try_cli(settings, "daily:read")
    if result is not None:
        return result
    return _read_file(_ensure_daily_note(settings))


def create_inbox_note(settings: Settings, text: str) -> str:
    stamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    path = f"00 Inbox/{stamp}.md"
    content = f"# Inbox - {stamp}\n\n{text.strip()}\n"
    result = _try_cli(settings, "create", f"path={path}", f"content={content}")
    relative = path if result is not None else _create_note_direct(settings, path, content=content)
    apply_note_defaults(settings, relative, note_type="inbox", title=stamp, topic="inbox", review=True)
    return relative


def create_templated_note(settings: Settings, folder: str, title: str, template: str) -> str:
    safe_title = _safe_title(title, datetime.now().strftime("%Y-%m-%d %H-%M-%S"))
    path = f"{folder}/{safe_title}.md"
    result = _try_cli(settings, "create", f"path={path}", f"template={template}")
    return path if result is not None else _create_note_direct(settings, path, template=template)


def append_note_content(settings: Settings, path: str, text: str) -> None:
    result = _try_cli(settings, "append", f"path={path}", f"content={text}")
    if result is not None:
        return
    _append_to_note_direct(settings, path, text)


def create_project_note(settings: Settings, title: str) -> str:
    path = create_templated_note(settings, "02 Projects", title, "Template - Project Note")
    apply_note_defaults(settings, path, note_type="project", title=title, topic="project", project=title, review=True)
    return path


def create_knowledge_note(settings: Settings, title: str) -> str:
    path = create_templated_note(settings, "03 Knowledge", title, "Template - Knowledge Note")
    apply_note_defaults(settings, path, note_type="knowledge", title=title, topic="knowledge", review=True)
    return path


def create_resource_note(settings: Settings, title: str) -> str:
    path = create_templated_note(settings, "04 Resources", title, "Template - Resource Note")
    apply_note_defaults(settings, path, note_type="resource", title=title, topic="resource", review=True)
    return path


def create_schedule_note(
    settings: Settings,
    title: str,
    date_text: str = "",
    time_text: str = "",
    *,
    recurrence_type: str = "",
    recurrence_value: str = "",
) -> str:
    path = create_templated_note(settings, "06 Schedule", title, "Template - Schedule Note")
    apply_note_defaults(settings, path, note_type="schedule", title=title, topic="schedule", review=True)
    if date_text:
        set_note_property(settings, path, "date", date_text, type_name="date")
    if time_text:
        set_note_property(settings, path, "time", time_text)
    if recurrence_type:
        set_note_property(settings, path, "recurrence_type", recurrence_type)
    if recurrence_value:
        set_note_property(settings, path, "recurrence_value", recurrence_value)
    _invalidate_schedule_cache(settings)
    return path


def update_schedule_note(
    settings: Settings,
    relative_path: str,
    *,
    date_text: str | None = None,
    time_text: str | None = None,
    recurrence_type: str | None = None,
    recurrence_value: str | None = None,
) -> str:
    if date_text is not None:
        set_note_property(settings, relative_path, "date", date_text, type_name="date")
    if time_text is not None:
        set_note_property(settings, relative_path, "time", time_text)
    if recurrence_type is not None:
        set_note_property(settings, relative_path, "recurrence_type", recurrence_type)
    if recurrence_value is not None:
        set_note_property(settings, relative_path, "recurrence_value", recurrence_value)
    _invalidate_schedule_cache(settings)
    return relative_path


def parse_natural_language_schedule(text: str, *, now: datetime | None = None) -> dict[str, str] | None:
    raw = (text or "").strip()
    if not raw:
        return None

    current = now or datetime.now()
    working = raw
    target_date = current.date()
    recurrence_type = ""
    recurrence_value = ""

    relative_minutes = re.search(r"(?P<minutes>\d{1,3})\s*分鐘後", working)
    if relative_minutes:
        offset_minutes = int(relative_minutes.group("minutes"))
        when = current + timedelta(minutes=offset_minutes)
        target_date = when.date()
        hour = when.hour
        minute = when.minute
        working = working.replace(relative_minutes.group(0), " ")
    else:
        daily_match = re.search(r"每天", working)
        weekly_match = re.search(r"每週(?P<weekday>[一二三四五六日天])", working)
        monthly_match = re.search(r"每月(?P<day>\d{1,2})號", working)
        weekday_map = {
            "一": 0,
            "二": 1,
            "三": 2,
            "四": 3,
            "五": 4,
            "六": 5,
            "日": 6,
            "天": 6,
        }

        if daily_match:
            recurrence_type = "daily"
            recurrence_value = "daily"
            working = working.replace(daily_match.group(0), " ")
        elif weekly_match:
            recurrence_type = "weekly"
            recurrence_value = str(weekday_map[weekly_match.group("weekday")])
            target_weekday = int(recurrence_value)
            days_until = (target_weekday - current.weekday()) % 7
            if days_until == 0:
                days_until = 7
            target_date = (current + timedelta(days=days_until)).date()
            working = working.replace(weekly_match.group(0), " ")
        elif monthly_match:
            recurrence_type = "monthly"
            recurrence_value = monthly_match.group("day")
            candidate_day = int(recurrence_value)
            year = current.year
            month = current.month
            while True:
                try:
                    candidate_date = datetime(year, month, candidate_day).date()
                except ValueError:
                    return None
                if candidate_date >= current.date():
                    target_date = candidate_date
                    break
                month += 1
                if month > 12:
                    month = 1
                    year += 1
            working = working.replace(monthly_match.group(0), " ")
        else:
            explicit_date = re.search(r"(?P<year>\d{4})[-/](?P<month>\d{1,2})[-/](?P<day>\d{1,2})", working)
            if explicit_date:
                try:
                    target_date = datetime(
                        int(explicit_date.group("year")),
                        int(explicit_date.group("month")),
                        int(explicit_date.group("day")),
                    ).date()
                except ValueError:
                    return None
                working = working.replace(explicit_date.group(0), " ")
            else:
                month_day_match = re.search(r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日", working)
                if month_day_match:
                    month = int(month_day_match.group("month"))
                    day = int(month_day_match.group("day"))
                    year = current.year
                    while True:
                        try:
                            candidate_date = datetime(year, month, day).date()
                        except ValueError:
                            return None
                        if candidate_date >= current.date():
                            target_date = candidate_date
                            break
                        year += 1
                    working = working.replace(month_day_match.group(0), " ")
                else:
                    weekday_match = re.search(r"下週(?P<weekday>[一二三四五六日天])", working)
                    if weekday_match:
                        target_weekday = weekday_map[weekday_match.group("weekday")]
                        days_until = (target_weekday - current.weekday()) % 7
                        if days_until == 0:
                            days_until = 7
                        target_date = (current + timedelta(days=days_until + 7)).date()
                        working = working.replace(weekday_match.group(0), " ")
                    else:
                        date_keywords = {
                            "今天": 0,
                            "今日": 0,
                            "明天": 1,
                            "明日": 1,
                            "後天": 2,
                        }
                        for keyword, offset in date_keywords.items():
                            if keyword in working:
                                target_date = (current + timedelta(days=offset)).date()
                                working = working.replace(keyword, " ")
                                break

        period_match = re.search(r"(凌晨|清晨|明早|早上|上午|中午|下午|晚上|今晚|明晚|傍晚)", working)
        period = period_match.group(1) if period_match else ""
        if period_match:
            working = working.replace(period_match.group(1), " ")
            if period in {"明早", "明晚"} and recurrence_type == "" and target_date == current.date():
                target_date = (current + timedelta(days=1)).date()

        time_match = re.search(
            r"(?P<hour>\d{1,2})\s*(?:[:：]\s*(?P<minute_colon>\d{1,2})|點\s*(?:(?P<half>半)|(?P<minute_zh>\d{1,2})(?:\s*分)?)?)",
            working,
        )
        if time_match is None:
            if recurrence_type:
                hour = None
                minute = None
            else:
                return None
        else:
            hour = int(time_match.group("hour"))
            minute_raw = time_match.group("minute_colon") or time_match.group("minute_zh") or ""
            minute = 30 if time_match.group("half") else int(minute_raw or "0")
            if minute < 0 or minute > 59 or hour < 0 or hour > 23:
                return None

            if period in {"下午", "晚上", "今晚", "明晚", "傍晚"} and 1 <= hour <= 11:
                hour += 12
            elif period == "中午":
                if hour != 12 and 1 <= hour <= 11:
                    hour += 12
            elif period in {"凌晨", "清晨"} and hour == 12:
                hour = 0

            working = working.replace(time_match.group(0), " ")

    title = re.sub(r"(提醒我|提醒|記得|要|去|該|幫我|需要|加入行程|加進行程|安排|排進|新增行程|建立行程|加入日曆|加入行事曆|有一個)", " ", working)
    title = re.sub(r"\s+", " ", title).strip(" ，,。.;；：:")
    if not title:
        return None

    return {
        "title": title,
        "date_text": target_date.strftime("%Y-%m-%d"),
        "time_text": f"{hour:02d}:{minute:02d}" if hour is not None and minute is not None else "",
        "recurrence_type": recurrence_type,
        "recurrence_value": recurrence_value,
        "source_text": raw,
    }


def parse_schedule_update_details(
    text: str,
    *,
    current_title: str,
    now: datetime | None = None,
) -> dict[str, str] | None:
    raw = (text or "").strip()
    if not raw:
        return None

    current = now or datetime.now()
    working = raw
    explicit_date = False
    explicit_time = False
    recurrence_type = None
    recurrence_value = None
    target_date: datetime.date | None = None
    hour: int | None = None
    minute: int | None = None

    weekday_map = {
        "一": 0,
        "二": 1,
        "三": 2,
        "四": 3,
        "五": 4,
        "六": 5,
        "日": 6,
        "天": 6,
    }

    if "每天" in working:
        recurrence_type = "daily"
        recurrence_value = "daily"
        working = working.replace("每天", " ")
    else:
        weekly_match = re.search(r"每週(?P<weekday>[一二三四五六日天])", working)
        monthly_match = re.search(r"每月(?P<day>\d{1,2})號", working)
        if weekly_match:
            recurrence_type = "weekly"
            recurrence_value = str(weekday_map[weekly_match.group("weekday")])
            target_weekday = int(recurrence_value)
            days_until = (target_weekday - current.weekday()) % 7
            target_date = (current + timedelta(days=days_until)).date()
            explicit_date = True
            working = working.replace(weekly_match.group(0), " ")
        elif monthly_match:
            recurrence_type = "monthly"
            recurrence_value = monthly_match.group("day")
            candidate_day = int(recurrence_value)
            year = current.year
            month = current.month
            while True:
                try:
                    candidate_date = datetime(year, month, candidate_day).date()
                except ValueError:
                    return None
                if candidate_date >= current.date():
                    target_date = candidate_date
                    explicit_date = True
                    break
                month += 1
                if month > 12:
                    month = 1
                    year += 1
            working = working.replace(monthly_match.group(0), " ")

    explicit_date_match = re.search(r"(?P<year>\d{4})[-/](?P<month>\d{1,2})[-/](?P<day>\d{1,2})", working)
    month_day_match = re.search(r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日", working)
    weekday_match = re.search(r"下週(?P<weekday>[一二三四五六日天])", working)
    if explicit_date_match:
        target_date = datetime(
            int(explicit_date_match.group("year")),
            int(explicit_date_match.group("month")),
            int(explicit_date_match.group("day")),
        ).date()
        explicit_date = True
        working = working.replace(explicit_date_match.group(0), " ")
    elif month_day_match:
        month = int(month_day_match.group("month"))
        day = int(month_day_match.group("day"))
        year = current.year
        while True:
            try:
                candidate_date = datetime(year, month, day).date()
            except ValueError:
                return None
            if candidate_date >= current.date():
                target_date = candidate_date
                explicit_date = True
                break
            year += 1
        working = working.replace(month_day_match.group(0), " ")
    elif weekday_match:
        target_weekday = weekday_map[weekday_match.group("weekday")]
        days_until = (target_weekday - current.weekday()) % 7
        if days_until == 0:
            days_until = 7
        target_date = (current + timedelta(days=days_until + 7)).date()
        explicit_date = True
        working = working.replace(weekday_match.group(0), " ")
    else:
        date_keywords = {
            "今天": 0,
            "今日": 0,
            "明天": 1,
            "明日": 1,
            "後天": 2,
        }
        for keyword, offset in date_keywords.items():
            if keyword in working:
                target_date = (current + timedelta(days=offset)).date()
                explicit_date = True
                working = working.replace(keyword, " ")
                break

    period_match = re.search(r"(凌晨|清晨|明早|早上|上午|中午|下午|晚上|今晚|明晚|傍晚)", working)
    period = period_match.group(1) if period_match else ""
    if period_match:
        working = working.replace(period_match.group(1), " ")

    time_match = re.search(
        r"(?P<hour>\d{1,2})\s*(?:[:：]\s*(?P<minute_colon>\d{1,2})|點\s*(?:(?P<half>半)|(?P<minute_zh>\d{1,2})(?:\s*分)?)?)",
        working,
    )
    if time_match is not None:
        hour = int(time_match.group("hour"))
        minute_raw = time_match.group("minute_colon") or time_match.group("minute_zh") or ""
        minute = 30 if time_match.group("half") else int(minute_raw or "0")
        explicit_time = True
        if period in {"下午", "晚上", "今晚", "明晚", "傍晚"} and 1 <= hour <= 11:
            hour += 12
        elif period == "中午":
            if hour != 12 and 1 <= hour <= 11:
                hour += 12
        elif period in {"凌晨", "清晨"} and hour == 12:
            hour = 0

    if not explicit_date and not explicit_time and recurrence_type is None:
        return None

    parsed = parse_natural_language_schedule(f"{raw} {current_title}", now=current)
    title_text = current_title
    if parsed is not None:
        candidate_title = (parsed.get("title") or "").strip()
        if candidate_title and candidate_title != current_title:
            title_text = candidate_title

    return {
        "title": title_text,
        "date_text": target_date.strftime("%Y-%m-%d") if explicit_date and target_date is not None else "",
        "time_text": f"{hour:02d}:{minute:02d}" if explicit_time and hour is not None and minute is not None else "",
        "recurrence_type": recurrence_type or "",
        "recurrence_value": recurrence_value or "",
    }


def _recurrence_label(item: dict[str, str]) -> str:
    recurrence_type = (item.get("recurrence_type") or "").strip()
    recurrence_value = (item.get("recurrence_value") or "").strip()
    if recurrence_type == "daily":
        return "每天"
    if recurrence_type == "weekly":
        try:
            weekday = int(recurrence_value)
        except ValueError:
            return "每週"
        if 0 <= weekday < len(WEEKDAY_NAMES):
            return f"每週{WEEKDAY_NAMES[weekday]}"
        return "每週"
    if recurrence_type == "monthly":
        return f"每月{recurrence_value}號" if recurrence_value else "每月"
    return ""


def _schedule_happens_on(item: dict[str, str], current: datetime) -> bool:
    recurrence_type = (item.get("recurrence_type") or "").strip()
    recurrence_value = (item.get("recurrence_value") or "").strip()
    if recurrence_type == "daily":
        return True
    if recurrence_type == "weekly":
        try:
            return current.weekday() == int(recurrence_value)
        except ValueError:
            return False
    if recurrence_type == "monthly":
        try:
            return current.day == int(recurrence_value)
        except ValueError:
            return False
    return (item.get("date") or "").strip() == current.strftime("%Y-%m-%d")


def _parse_schedule_time(time_text: str) -> tuple[int, int] | None:
    normalized = time_text.replace("：", ":")
    try:
        hour_text, minute_text = normalized.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError:
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return hour, minute


def _next_schedule_occurrence(item: dict[str, str], current: datetime) -> datetime | None:
    time_parts = _parse_schedule_time((item.get("time") or "").strip())
    if time_parts is None:
        return None
    hour, minute = time_parts
    recurrence_type = (item.get("recurrence_type") or "").strip()
    recurrence_value = (item.get("recurrence_value") or "").strip()

    if recurrence_type == "daily":
        candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate < current - timedelta(minutes=30):
            candidate += timedelta(days=1)
        return candidate

    if recurrence_type == "weekly":
        try:
            target_weekday = int(recurrence_value)
        except ValueError:
            return None
        days_until = (target_weekday - current.weekday()) % 7
        candidate_date = (current + timedelta(days=days_until)).date()
        candidate = datetime(candidate_date.year, candidate_date.month, candidate_date.day, hour, minute)
        if candidate < current - timedelta(minutes=30):
            candidate += timedelta(days=7)
        return candidate

    if recurrence_type == "monthly":
        try:
            target_day = int(recurrence_value)
        except ValueError:
            return None
        year = current.year
        month = current.month
        while True:
            try:
                candidate = datetime(year, month, target_day, hour, minute)
            except ValueError:
                return None
            if candidate >= current - timedelta(minutes=30):
                return candidate
            month += 1
            if month > 12:
                month = 1
                year += 1

    date_text = (item.get("date") or "").strip()
    if not date_text:
        return None
    try:
        return datetime.fromisoformat(f"{date_text} {hour:02d}:{minute:02d}")
    except ValueError:
        return None


def _schedule_occurrences_between(
    item: dict[str, str],
    start: datetime,
    end: datetime,
) -> list[tuple[datetime, dict[str, str]]]:
    time_parts = _parse_schedule_time((item.get("time") or "").strip())
    hour, minute = time_parts if time_parts is not None else (0, 0)
    recurrence_type = (item.get("recurrence_type") or "").strip()
    recurrence_value = (item.get("recurrence_value") or "").strip()
    occurrences: list[tuple[datetime, dict[str, str]]] = []

    if recurrence_type == "daily":
        cursor = start.date()
        while cursor <= end.date():
            occurrences.append((datetime(cursor.year, cursor.month, cursor.day, hour, minute), item))
            cursor += timedelta(days=1)
        return occurrences

    if recurrence_type == "weekly":
        try:
            target_weekday = int(recurrence_value)
        except ValueError:
            return []
        cursor = start.date()
        while cursor <= end.date():
            if cursor.weekday() == target_weekday:
                occurrences.append((datetime(cursor.year, cursor.month, cursor.day, hour, minute), item))
            cursor += timedelta(days=1)
        return occurrences

    if recurrence_type == "monthly":
        try:
            target_day = int(recurrence_value)
        except ValueError:
            return []
        cursor = start.date().replace(day=1)
        while cursor <= end.date():
            try:
                candidate = datetime(cursor.year, cursor.month, target_day, hour, minute)
            except ValueError:
                candidate = None
            if candidate is not None and start <= candidate <= end:
                occurrences.append((candidate, item))
            next_month = cursor.month + 1
            next_year = cursor.year
            if next_month > 12:
                next_month = 1
                next_year += 1
            cursor = cursor.replace(year=next_year, month=next_month)
        return occurrences

    date_text = (item.get("date") or "").strip()
    if not date_text:
        return []
    try:
        date_part = datetime.fromisoformat(date_text).date()
    except ValueError:
        return []
    candidate = datetime(date_part.year, date_part.month, date_part.day, hour, minute)
    return [(candidate, item)] if start <= candidate <= end else []


def list_schedule_notes(settings: Settings, limit: int = 10) -> list[dict[str, str]]:
    vault_root = _vault_root(settings)
    base = vault_root / "06 Schedule"
    if not base.exists():
        return []

    cache_key = str(vault_root.resolve())
    cached = _SCHEDULE_NOTES_CACHE.get(cache_key)
    if cached:
        cached_at = float(cached.get("cached_at") or 0.0)
        cached_items = cached.get("items")
        if time.monotonic() - cached_at <= SCHEDULE_CACHE_TTL_SECONDS and isinstance(cached_items, list):
            return [dict(item) for item in cached_items[: max(1, limit)]]

    items: list[dict[str, str]] = []
    for path in base.rglob("*.md"):
        if path.name.lower() == "readme.md":
            continue
        try:
            text = _read_file(path)
        except OSError:
            continue
        frontmatter, _ = _parse_frontmatter(text)
        items.append(
            {
                "path": _relative_posix(path, vault_root),
                "title": path.stem,
                "date": str(frontmatter.get("date") or "").strip(),
                "time": str(frontmatter.get("time") or "").strip(),
                "recurrence_type": str(frontmatter.get("recurrence_type") or "").strip(),
                "recurrence_value": str(frontmatter.get("recurrence_value") or "").strip(),
            }
        )

    def sort_key(item: dict[str, str]) -> tuple[str, str, str]:
        return (
            item.get("date") or "9999-99-99",
            item.get("time") or "99:99",
            item.get("title") or "",
        )

    items.sort(key=sort_key)
    _SCHEDULE_NOTES_CACHE[cache_key] = {
        "cached_at": time.monotonic(),
        "items": [dict(item) for item in items],
    }
    return [dict(item) for item in items[: max(1, limit)]]


def find_schedule_notes(settings: Settings, query: str, limit: int = 10) -> list[dict[str, str]]:
    normalized = (query or "").strip().lower()
    if not normalized:
        return []
    matches: list[dict[str, str]] = []
    for item in list_schedule_notes(settings, limit=200):
        title = (item.get("title") or "").strip().lower()
        path = (item.get("path") or "").strip().lower()
        if normalized in title or normalized in path:
            matches.append(item)
    return matches[: max(1, limit)]


def archive_schedule_note(settings: Settings, relative_path: str) -> str:
    vault_root = _vault_root(settings).resolve()
    source = (vault_root / Path(relative_path)).resolve()
    if vault_root not in source.parents or source.suffix.lower() != ".md":
        raise ValueError("Invalid schedule note path")
    schedule_root = (vault_root / "06 Schedule").resolve()
    if schedule_root not in source.parents:
        raise ValueError("Path is not a schedule note")
    if not source.exists():
        raise FileNotFoundError(relative_path)

    archive_dir = vault_root / "99 Archive" / "Deleted Schedule"
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / source.name
    if target.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = archive_dir / f"{source.stem}-{stamp}{source.suffix}"
    source.replace(target)
    _invalidate_schedule_cache(settings)
    return _relative_posix(target, vault_root)


def archive_past_due_schedule_notes(
    settings: Settings,
    *,
    now: datetime | None = None,
    grace_minutes: int = 30,
    limit: int = 100,
) -> list[dict[str, str]]:
    current = now or datetime.now()
    archived: list[dict[str, str]] = []
    for item in list_schedule_notes(settings, limit=limit):
        if (item.get("recurrence_type") or "").strip():
            continue
        date_text = (item.get("date") or "").strip()
        time_text = (item.get("time") or "").strip()
        if not date_text or not time_text:
            continue
        time_parts = _parse_schedule_time(time_text)
        if time_parts is None:
            continue
        hour, minute = time_parts
        try:
            when_date = datetime.fromisoformat(date_text).date()
        except ValueError:
            continue
        when = datetime(when_date.year, when_date.month, when_date.day, hour, minute)
        if when > current - timedelta(minutes=grace_minutes):
            continue
        path = item.get("path") or ""
        if not path:
            continue
        archived_path = archive_schedule_note(settings, path)
        archived.append(
            {
                "title": item.get("title") or "",
                "path": path,
                "archived_path": archived_path,
                "date": date_text,
                "time": time_text,
            }
        )
    return archived


def build_schedule_brief(settings: Settings, *, today_only: bool = False, limit: int = 10) -> str:
    items = list_schedule_notes(settings, limit=max(limit * 3, 10))
    current = datetime.now()
    today = current.strftime("%Y-%m-%d")
    if today_only:
        items = [item for item in items if _schedule_happens_on(item, current)]
        title = f"今日日程 {today}"
    else:
        title = "行程列表"

    lines = [title, ""]
    if not items:
        lines.append("- 目前沒有符合條件的行程")
        return "\n".join(lines)

    for item in items[: max(1, limit)]:
        recurrence = _recurrence_label(item)
        if recurrence:
            when = " ".join(part for part in [recurrence, item.get("time") or ""] if part).strip()
        else:
            when = " ".join(part for part in [item.get("date") or "", item.get("time") or ""] if part).strip()
        when = when or "未排時間"
        lines.append(f"- {when} | {item.get('title')}")
        lines.append(f"  {item.get('path')}")
    return "\n".join(lines)


def build_schedule_range_brief(
    settings: Settings,
    *,
    period: str = "day",
    now: datetime | None = None,
    limit: int = 50,
) -> str:
    current = now or datetime.now()
    if period == "next_week":
        start = (current - timedelta(days=current.weekday()) + timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7) - timedelta(microseconds=1)
        title = f"下週行程 {start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')}"
    elif period == "week":
        start = (current - timedelta(days=current.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7) - timedelta(microseconds=1)
        title = f"本週行程 {start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')}"
    elif period == "month":
        start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            next_month = start.replace(year=start.year + 1, month=1)
        else:
            next_month = start.replace(month=start.month + 1)
        end = next_month - timedelta(microseconds=1)
        title = f"本月行程 {start.strftime('%Y-%m')}"
    else:
        start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1) - timedelta(microseconds=1)
        title = f"今日行程 {start.strftime('%Y-%m-%d')}"

    occurrences: list[tuple[datetime, dict[str, str]]] = []
    for item in list_schedule_notes(settings, limit=max(limit * 4, 100)):
        occurrences.extend(_schedule_occurrences_between(item, start, end))
    occurrences.sort(key=lambda occurrence: (occurrence[0], occurrence[1].get("title") or ""))

    lines = [title, ""]
    if not occurrences:
        lines.append("- 目前沒有符合條件的行程")
        return "\n".join(lines)

    for when, item in occurrences[: max(1, limit)]:
        time_text = (item.get("time") or "").strip() or "未排時間"
        recurrence = _recurrence_label(item)
        recurrence_note = f" ({recurrence})" if recurrence else ""
        lines.append(f"- {when.strftime('%Y-%m-%d')} {time_text} | {item.get('title')}{recurrence_note}")
        lines.append(f"  {item.get('path')}")
    return "\n".join(lines)


def list_schedule_occurrences(
    settings: Settings,
    *,
    period: str = "day",
    now: datetime | None = None,
    limit: int = 50,
) -> tuple[str, list[dict[str, str]]]:
    current = now or datetime.now()
    if period == "next_week":
        start = (current - timedelta(days=current.weekday()) + timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7) - timedelta(microseconds=1)
        title = f"下週行程 {start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')}"
    elif period == "week":
        start = (current - timedelta(days=current.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7) - timedelta(microseconds=1)
        title = f"本週行程 {start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')}"
    elif period == "month":
        start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            next_month = start.replace(year=start.year + 1, month=1)
        else:
            next_month = start.replace(month=start.month + 1)
        end = next_month - timedelta(microseconds=1)
        title = f"本月行程 {start.strftime('%Y-%m')}"
    else:
        start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1) - timedelta(microseconds=1)
        title = f"今日行程 {start.strftime('%Y-%m-%d')}"

    occurrences: list[tuple[datetime, dict[str, str]]] = []
    for item in list_schedule_notes(settings, limit=max(limit * 4, 100)):
        occurrences.extend(_schedule_occurrences_between(item, start, end))
    occurrences.sort(key=lambda occurrence: (occurrence[0], occurrence[1].get("title") or ""))

    results: list[dict[str, str]] = []
    for when, item in occurrences[: max(1, limit)]:
        time_text = (item.get("time") or "").strip() or "未排時間"
        recurrence = _recurrence_label(item)
        results.append(
            {
                "title": item.get("title") or "",
                "date": when.strftime("%Y-%m-%d"),
                "time": time_text,
                "path": item.get("path") or "",
                "recurrence": recurrence,
            }
        )
    return title, results


def get_active_or_next_schedule(
    settings: Settings,
    *,
    now: datetime | None = None,
    lookahead_minutes: int = 60,
) -> dict[str, str] | None:
    current = now or datetime.now()
    items = list_schedule_notes(settings, limit=100)
    best: tuple[int, datetime, dict[str, str]] | None = None

    for item in items:
        when = _next_schedule_occurrence(item, current)
        if when is None:
            continue

        delta_minutes = int((when - current).total_seconds() // 60)
        if delta_minutes < -30 or delta_minutes > lookahead_minutes:
            continue

        if delta_minutes <= 0:
            priority = 0
        elif delta_minutes <= 10:
            priority = 1
        else:
            priority = 2

        candidate = (priority, when, item)
        if best is None or candidate < best:
            best = candidate

    if best is None:
        return None

    _, when, item = best
    delta_minutes = int((when - current).total_seconds() // 60)
    status = "now" if delta_minutes <= 0 else "next"
    return {
        "status": status,
        "title": item.get("title") or "",
        "date": when.strftime("%Y-%m-%d"),
        "time": item.get("time") or "",
        "path": item.get("path") or "",
        "minutes_until": str(delta_minutes),
        "recurrence": _recurrence_label(item),
    }


def build_schedule_alert(settings: Settings, *, now: datetime | None = None) -> str | None:
    match = get_active_or_next_schedule(settings, now=now)
    if match is None:
        return None

    title = match.get("title") or "Untitled schedule"
    date_text = match.get("date") or ""
    time_text = match.get("time") or ""
    path = match.get("path") or ""
    minutes_until = int(match.get("minutes_until") or "0")

    if match.get("status") == "now":
        header = "現在該做的事"
        detail = f"{title} 已到時間，請開始。"
    elif minutes_until <= 10:
        header = "即將開始的事"
        detail = f"{title} 將在 {minutes_until} 分鐘後開始。"
    else:
        header = "下一個行程"
        detail = f"{title} 將在 {minutes_until} 分鐘後開始。"

    return "\n".join(
        [
            header,
            detail,
            f"時間: {date_text} {time_text}".strip(),
            f"path: {path}",
        ]
    )


def create_project_note_from_text(settings: Settings, title: str, source_text: str) -> str:
    path = create_project_note(settings, title)
    append_note_content(settings, path, f"\n\n## 從 Inbox / Daily 整理而來\n\n{source_text.strip()}\n")
    return path


def create_knowledge_note_from_text(settings: Settings, title: str, source_text: str) -> str:
    path = create_knowledge_note(settings, title)
    append_note_content(settings, path, f"\n\n## 原始整理內容\n\n{source_text.strip()}\n")
    return path


def create_resource_note_from_text(settings: Settings, title: str, source_text: str) -> str:
    path = create_resource_note(settings, title)
    append_note_content(settings, path, f"\n\n## 原始資料\n\n{source_text.strip()}\n")
    return path


class _HTMLContentExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_script = False
        self._in_style = False
        self._in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        lowered = tag.lower()
        if lowered == "script":
            self._in_script = True
        elif lowered == "style":
            self._in_style = True
        elif lowered == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        lowered = tag.lower()
        if lowered == "script":
            self._in_script = False
        elif lowered == "style":
            self._in_style = False
        elif lowered == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if self._in_script or self._in_style:
            return
        text = (data or "").strip()
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
            return
        self.text_parts.append(text)


def _is_valid_web_url(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def fetch_webpage_text(url: str, *, timeout_seconds: float = 8.0, max_chars: int = 12000) -> tuple[str, str]:
    if not _is_valid_web_url(url):
        raise ValueError("Invalid URL. Only http/https URLs are supported.")

    req = Request(
        url.strip(),
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; robot/0.1.1; +https://github.com/kevincsl/robot)",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        },
    )
    max_bytes = 2_000_000
    with urlopen(req, timeout=timeout_seconds) as resp:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total >= max_bytes:
                break
        raw = b"".join(chunks)
        content_type = resp.headers.get_content_charset() or "utf-8"
    html = raw.decode(content_type, errors="replace")

    parser = _HTMLContentExtractor()
    parser.feed(html)
    title = re.sub(r"\s+", " ", " ".join(parser.title_parts)).strip()
    merged = "\n".join(parser.text_parts)
    merged = re.sub(r"[ \t]+", " ", merged)
    merged = re.sub(r"\n{3,}", "\n\n", merged).strip()
    if len(merged) > max_chars:
        merged = merged[:max_chars].rstrip() + "..."
    return title, merged


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in values:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(item.strip())
    return ordered


def _build_web_summary_points(title: str, text: str, *, max_points: int = 3) -> list[str]:
    candidates: list[str] = []
    if title.strip():
        candidates.append(title.strip())

    normalized = re.sub(r"\s+", " ", (text or "").replace("\n", " ")).strip()
    parts = re.split(r"[。！？!?；;]\s*|(?<=\.)\s+", normalized)
    for part in parts:
        sentence = part.strip(" -\t\r\n")
        if 18 <= len(sentence) <= 140:
            candidates.append(sentence)

    unique = _dedupe_keep_order(candidates)
    if not unique:
        fallback = normalized[:120].strip()
        return [fallback] if fallback else []
    return unique[: max(1, max_points)]


def _build_web_tags(url: str, title: str, text: str, *, max_tags: int = 6) -> list[str]:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    haystack = f"{title}\n{text}".lower()
    tags: list[str] = []
    if host:
        tags.append(host)

    keyword_tags = [
        ("ai", "ai"),
        ("nvidia", "nvidia"),
        ("openclaw", "openclaw"),
        ("minimax", "minimax"),
        ("api", "api"),
        ("教學", "tutorial"),
        ("教程", "tutorial"),
        ("新聞", "news"),
        ("評測", "review"),
        ("github", "github"),
    ]
    for keyword, tag in keyword_tags:
        if keyword in haystack:
            tags.append(tag)

    unique = _dedupe_keep_order(tags)
    return unique[: max(1, max_tags)]


def capture_web_to_daily(settings: Settings, url: str, *, max_chars: int = 2500) -> tuple[str, str, str, list[str], list[str]]:
    title, text = fetch_webpage_text(url, max_chars=max_chars)
    safe_title = title or url.strip()
    summary_points = _build_web_summary_points(safe_title, text, max_points=3)
    tags = _build_web_tags(url, safe_title, text, max_tags=6)

    summary_block = "\n".join(f"- {point}" for point in summary_points) if summary_points else "- (none)"
    tags_line = ", ".join(tags) if tags else "(none)"
    body = (
        "網頁收錄\n"
        f"- url: {url.strip()}\n"
        f"- title: {safe_title}\n"
        f"- tags: {tags_line}\n\n"
        "摘要重點\n"
        f"{summary_block}\n\n"
        "原始內容\n"
        f"{text}"
    )
    path = append_to_daily(settings, body)
    return path, safe_title, text, summary_points, tags


def _normalize_for_auto_organize(text: str) -> str:
    return (text or "").strip().lower()


def _infer_auto_organize_target(text: str) -> str:
    normalized = _normalize_for_auto_organize(text)
    if not normalized:
        return "knowledge"

    project_keywords = (
        "專案",
        "project",
        "roadmap",
        "milestone",
        "deadline",
        "需求",
        "待辦",
        "todo",
        "bug",
        "issue",
        "版本",
        "交付",
        "開發",
    )
    resource_keywords = (
        "http://",
        "https://",
        "www.",
        ".pdf",
        ".ppt",
        ".pptx",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".csv",
        ".md",
        ".txt",
        "連結",
        "網址",
        "參考",
        "article",
        "paper",
        "repo",
        "github",
        "youtube",
        "影片",
    )

    if any(keyword in normalized for keyword in project_keywords):
        return "project"
    if any(keyword in normalized for keyword in resource_keywords):
        return "resource"
    return "knowledge"


def _extract_auto_organize_title(text: str, fallback: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return fallback
    first = lines[0]
    if first.startswith("#"):
        first = first.lstrip("#").strip()
    first = re.sub(r"^\[[0-9]{1,2}:[0-9]{2}\]\s*", "", first)
    first = re.sub(r"\s+", " ", first).strip(" -:：")
    if not first:
        return fallback
    return first[:60]


def auto_organize_recent_notes(settings: Settings, *, limit: int = 10) -> dict[str, object]:
    bounded_limit = max(1, min(limit, 50))
    recent_items = _list_notes_with_mtime(settings, "00 Inbox") + _list_notes_with_mtime(settings, "01 Daily Notes")
    recent_items.sort(key=lambda item: item[1], reverse=True)
    selected_paths = [path for path, _ in recent_items[:bounded_limit]]
    if not selected_paths:
        return {
            "processed": 0,
            "created": 0,
            "failed": 0,
            "skipped": 0,
            "by_type": {"project": 0, "knowledge": 0, "resource": 0},
            "items": [],
        }

    by_type: Counter[str] = Counter()
    results: list[dict[str, str]] = []
    created = 0
    failed = 0
    skipped = 0

    for index, source_path in enumerate(selected_paths, start=1):
        fallback_title = f"Auto Organized {datetime.now().strftime('%Y-%m-%d')} #{index}"
        try:
            source_text = read_note(settings, source_path).strip()
        except OSError as exc:
            failed += 1
            results.append(
                {
                    "source_path": source_path,
                    "target": "",
                    "title": "",
                    "path": "",
                    "status": "failed",
                    "error": str(exc),
                }
            )
            continue

        if not source_text:
            skipped += 1
            results.append(
                {
                    "source_path": source_path,
                    "target": "",
                    "title": "",
                    "path": "",
                    "status": "skipped",
                    "error": "empty note",
                }
            )
            continue

        target = _infer_auto_organize_target(source_text)
        title = _extract_auto_organize_title(source_text, fallback_title)
        try:
            if target == "project":
                new_path = create_project_note_from_text(settings, title, source_text)
            elif target == "resource":
                new_path = create_resource_note_from_text(settings, title, source_text)
            else:
                new_path = create_knowledge_note_from_text(settings, title, source_text)
        except OSError as exc:
            failed += 1
            results.append(
                {
                    "source_path": source_path,
                    "target": target,
                    "title": title,
                    "path": "",
                    "status": "failed",
                    "error": str(exc),
                }
            )
            continue

        created += 1
        by_type[target] += 1
        results.append(
            {
                "source_path": source_path,
                "target": target,
                "title": title,
                "path": new_path,
                "status": "created",
                "error": "",
            }
        )

    return {
        "processed": len(selected_paths),
        "created": created,
        "failed": failed,
        "skipped": skipped,
        "by_type": {
            "project": int(by_type.get("project", 0)),
            "knowledge": int(by_type.get("knowledge", 0)),
            "resource": int(by_type.get("resource", 0)),
        },
        "items": results,
    }


def import_markitdown_resource(settings: Settings, source_path: Path, title: str | None = None) -> tuple[str, str]:
    md = MarkItDown()
    result = md.convert(str(source_path))
    text_content = (result.text_content or "").strip()
    if not text_content:
        text_content = f"# {source_path.name}\n\n(No extracted text)\n"

    note_title = title or source_path.stem
    note_path = create_resource_note_from_text(settings, note_title, text_content)
    append_note_content(
        settings,
        note_path,
        "\n\n## 匯入來源\n\n"
        f"- file_name: {source_path.name}\n"
        f"- imported_at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
    )
    return note_path, text_content


def read_note(settings: Settings, path: str) -> str:
    result = _try_cli(settings, "read", f"path={path}")
    if result is not None:
        return result
    return _read_file(_vault_root(settings) / Path(path))


def search_vault(settings: Settings, query: str, limit: int = 10) -> list[str]:
    output = _try_cli(settings, "search", f"query={query.strip()}", "format=json", f"limit={max(1, limit)}")
    if output is not None:
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            return []
        return [item for item in payload if isinstance(item, str)]
    return _search_vault_direct(settings, query, limit=max(1, limit))


def search_vault_context(settings: Settings, query: str, limit: int = 5) -> list[dict[str, object]]:
    output = _try_cli(settings, "search:context", f"query={query.strip()}", "format=json", f"limit={max(1, limit)}")
    if output is not None:
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            return []
        return [item for item in payload if isinstance(item, dict)]
    return _search_vault_context_direct(settings, query, limit=max(1, limit))


def list_recent_notes(settings: Settings, folder: str, limit: int = 10) -> list[str]:
    vault_root = _vault_root(settings)
    base = vault_root / folder
    if not base.exists():
        return []
    candidates: list[Path] = []
    for path in base.rglob("*.md"):
        if path.name.lower() == "readme.md":
            continue
        candidates.append(path)
    candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return [_relative_posix(path, vault_root) for path in candidates[: max(1, limit)]]


def _list_notes_with_mtime(settings: Settings, folder: str) -> list[tuple[str, datetime]]:
    vault_root = _vault_root(settings)
    base = vault_root / folder
    if not base.exists():
        return []
    items: list[tuple[str, datetime]] = []
    for path in base.rglob("*.md"):
        if path.name.lower() == "readme.md":
            continue
        items.append((_relative_posix(path, vault_root), datetime.fromtimestamp(path.stat().st_mtime)))
    items.sort(key=lambda item: item[1], reverse=True)
    return items


def _extract_topic(text: str) -> str:
    match = TOPIC_RE.search(text)
    if not match:
        return ""
    return match.group(1).strip()


def ensure_weekly_summary_note(settings: Settings) -> str:
    stamp = datetime.now().strftime("%G-[W]%V")
    path = f"07 Decision Support/Weekly Summary - {stamp}.md"
    result = _try_cli(settings, "create", f"path={path}", "template=Template - Weekly Summary")
    relative = path if result is not None else _create_note_direct(settings, path, template="Template - Weekly Summary")
    apply_note_defaults(settings, relative, note_type="review", title=stamp, topic="weekly-summary", review=True)
    return relative


def collect_brain_reminders(settings: Settings, limit: int = 5) -> list[str]:
    now = datetime.now()
    inbox = list_recent_notes(settings, "00 Inbox", limit=limit)
    daily = list_recent_notes(settings, "01 Daily Notes", limit=limit)
    inbox_with_time = _list_notes_with_mtime(settings, "00 Inbox")
    decision_with_time = _list_notes_with_mtime(settings, "07 Decision Support")
    reminders: list[str] = []

    if inbox:
        reminders.append(f"- Inbox 還有 {len(inbox)} 篇最近未整理內容")
    if daily:
        reminders.append(f"- Daily Notes 最近有 {len(daily)} 篇可回顧筆記")

    stale_inbox = [path for path, mtime in inbox_with_time if now - mtime >= timedelta(days=1)]
    if stale_inbox:
        reminders.append(f"- 有 {len(stale_inbox)} 篇 Inbox 已超過 1 天未整理")

    stale_decisions = [
        path
        for path, mtime in decision_with_time
        if "Decision Review -" in path and now - mtime >= timedelta(days=3)
    ]
    if stale_decisions:
        reminders.append(f"- 有 {len(stale_decisions)} 篇 Decision Review 超過 3 天未回看")

    topic_counter: Counter[str] = Counter()
    for relative in list_recent_notes(settings, "01 Daily Notes", limit=max(limit, 10)):
        try:
            topic = _extract_topic(read_note(settings, relative))
        except OSError:
            topic = ""
        if topic:
            topic_counter[topic] += 1
    repeated_topics = [topic for topic, count in topic_counter.items() if count >= 2]
    if repeated_topics:
        joined = ", ".join(repeated_topics[:3])
        reminders.append(f"- 最近重複出現的主題：{joined}")

    if not reminders:
        reminders.append("- 目前沒有明顯待提醒項目")
    return reminders


def build_daily_brief(settings: Settings) -> str:
    today_body = read_daily(settings).strip()
    reminders = collect_brain_reminders(settings, limit=3)
    lines = [
        "每日摘要",
        "",
        "今日筆記重點：",
        today_body if today_body else "- 今日尚未有內容",
        "",
        "提醒：",
        *reminders,
    ]
    return "\n".join(lines)


def build_weekly_brief(settings: Settings, limit: int = 10) -> str:
    recent = list_recent_notes(settings, "01 Daily Notes", limit=limit)
    topic_counter: Counter[str] = Counter()
    for relative in recent:
        try:
            text = read_note(settings, relative)
        except OSError:
            continue
        match = TOPIC_RE.search(text)
        if match:
            topic = match.group(1).strip()
            if topic:
                topic_counter[topic] += 1
    lines = ["每週摘要", "", "最近筆記："]
    if recent:
        lines.extend(f"- {item}" for item in recent[:limit])
    else:
        lines.append("- 沒有最近的 Daily Notes")
    lines.extend(["", "高頻主題："])
    if topic_counter:
        lines.extend(f"- {topic} ({count})" for topic, count in topic_counter.most_common(5))
    else:
        lines.append("- 尚未累積可辨識的 topic")
    lines.extend(["", "提醒：", *collect_brain_reminders(settings, limit=3)])
    return "\n".join(lines)


def _build_decision_lines(question: str, matches: list[dict[str, object]], limit: int = 5) -> tuple[list[str], list[str]]:
    related_paths: list[str] = []
    background_points: list[str] = []
    for item in matches[:limit]:
        file_path = str(item.get("file") or "").strip()
        if not file_path:
            continue
        related_paths.append(file_path)
        snippets = [str(match.get("text") or "").strip() for match in list(item.get("matches") or [])[:2]]
        snippet_text = " / ".join(part for part in snippets if part)
        if snippet_text:
            background_points.append(f"- {file_path}: {snippet_text}")
        else:
            background_points.append(f"- {file_path}")
    if not background_points:
        background_points.append("- 找不到高度相關筆記")

    if related_paths:
        support = [
            "- 這個問題在你的第二大腦中已有可回收的背景與既有脈絡。",
            "- 你不是從零判斷，至少有一些過去資料可供交叉比對。",
        ]
        oppose = [
            "- 相關筆記目前仍偏片段，還不足以直接形成強結論。",
            "- 目前找到的是相近脈絡，不保證立場一致或證據完整。",
        ]
        risks = [
            "- 語意相近不等於事實相同，仍需人工判讀上下文。",
            "- 若只根據近期筆記，可能忽略更早但更關鍵的紀錄。",
        ]
        next_steps = [
            "- 先讀一遍相關筆記，確認真正支持與反對的論點。",
            "- 把明確證據補進決策筆記，再做最終判斷。",
        ]
    else:
        support = [
            "- 目前唯一正向訊號，是你已經意識到這題值得被明確整理。",
        ]
        oppose = [
            "- 現在缺少足夠既有資料支撐，直接下決策容易失真。",
        ]
        risks = [
            "- 你可能尚未把真正關鍵的背景寫進第二大腦。",
        ]
        next_steps = [
            "- 先補充背景資料，再重新發動決策支援。",
        ]

    lines = [
        f"決策支援：{question}",
        "",
        "問題定義：",
        f"- {question}",
        "",
        "相關背景：",
        *background_points,
        "",
        "相關筆記：",
    ]
    if related_paths:
        lines.extend(f"- {item}" for item in related_paths)
    else:
        lines.append("- 無")
    lines.extend(
        [
            "",
            "支持理由：",
            *support,
            "",
            "反對理由：",
            *oppose,
            "",
            "風險與盲點：",
            *risks,
            "",
            "建議下一步：",
            *next_steps,
        ]
    )
    return related_paths, lines


def create_decision_note(settings: Settings, question: str, related_notes: list[str] | None = None) -> str:
    stamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    path = f"07 Decision Support/Decision Review - {stamp}.md"
    lines = [
        f"# Decision Review - {stamp}",
        "",
        "## 問題定義",
        "",
        f"- {question.strip()}",
        "",
        "## 相關背景",
        "",
        "- ",
        "",
        "## 相關筆記",
        "",
    ]
    if related_notes:
        lines.extend(f"- {item}" for item in related_notes[:10])
    else:
        lines.append("- ")
    lines.extend(
        [
            "",
            "## 支持理由",
            "",
            "- ",
            "",
            "## 反對理由",
            "",
            "- ",
            "",
            "## 風險與盲點",
            "",
            "- ",
            "",
            "## 建議下一步",
            "",
            "- ",
            "",
        ]
    )
    content = "\n".join(lines)
    result = _try_cli(settings, "create", f"path={path}", f"content={content}")
    relative = path if result is not None else _create_note_direct(settings, path, content=content)
    apply_note_defaults(settings, relative, note_type="review", title=stamp, topic="decision-support", review=True)
    return relative


def create_decision_note_from_brief(settings: Settings, question: str, brief: str, related_notes: list[str] | None = None) -> str:
    stamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    path = f"07 Decision Support/Decision Review - {stamp}.md"
    content = f"# Decision Review - {stamp}\n\n{brief.strip()}\n"
    result = _try_cli(settings, "create", f"path={path}", f"content={content}")
    relative = path if result is not None else _create_note_direct(settings, path, content=content)
    apply_note_defaults(settings, relative, note_type="review", title=stamp, topic="decision-support", review=True)
    return relative


def build_decision_support_brief(settings: Settings, question: str, limit: int = 5) -> tuple[list[str], str]:
    matches = search_vault_context(settings, question, limit=limit)
    related_paths, lines = _build_decision_lines(question, matches, limit=limit)
    return related_paths, "\n".join(lines)
