from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values
from markitdown._exceptions import FileConversionException, MarkItDownException
from teleapp import Button, ButtonResponse
from teleapp.context import MessageContext
from teleapp.protocol import AppEvent

from robot.agents import AgentCoordinator
from robot.brain import (
    auto_organize_recent_notes,
    archive_schedule_note,
    archive_past_due_schedule_notes,
    append_to_daily,
    build_decision_support_brief,
    build_daily_brief,
    build_schedule_brief,
    build_schedule_range_brief,
    build_weekly_brief,
    collect_brain_reminders,
    capture_web_to_daily,
    create_decision_note,
    create_decision_note_from_brief,
    create_inbox_note,
    create_knowledge_note,
    create_knowledge_note_from_text,
    create_project_note,
    create_project_note_from_text,
    create_resource_note,
    create_resource_note_from_text,
    create_schedule_note,
    ensure_weekly_summary_note,
    import_markitdown_resource,
    list_recent_notes,
    list_schedule_occurrences,
    parse_natural_language_schedule,
    read_daily,
    read_note,
    search_vault,
    update_schedule_note,
)
from robot.config import MODEL_CHOICES, MODEL_DESCRIPTIONS, PROVIDER_LABELS, SUPPORTED_MODELS, Settings, VERSION
from robot.diagnostics import build_doctor_report
from robot.google_calendar import (
    delete_google_calendar_schedule_event,
    sync_schedule_jobs_with_google,
    upsert_google_calendar_schedule_event,
)
from robot.projects import discover_project_workspaces, find_workspace, format_project_with_branch
from robot.project_registry import (
    active_project,
    add_project_note,
    get_project,
    list_registered_projects,
    project_doctor,
    project_info,
    project_status,
    register_project,
    use_project,
)
from robot.state import ChatStateStore

COMMAND_REQUEST = "command"
CONTROL_REQUEST = "control"
AGENT_REQUEST = "agent"

COMMAND_NAMES = {
    "start",
    "help",
    "quick",
    "guide",
    "about",
    "status",
    "doctor",
    "contact",
    "contacts",
    "mailcli",
    "mailjson",
    "mailbatch",
    "mailmcp",
    "provider",
    "model",
    "models",
    "project",
    "projects",
    "queue",
    "schedules",
    "agentstatus",
    "agentprofiles",
    "menu",
    "brain",
    "brainread",
    "braininbox",
    "brainweb",
    "brainsearch",
    "braindecide",
    "brainsummary",
    "brainproject",
    "brainknowledge",
    "brainresource",
    "brainschedule",
    "brainorganize",
    "brainbatch",
    "brainbatchauto",
    "brainremind",
    "braindaily",
    "brainweekly",
    "brainauto",
    "brainautodaily",
    "brainautoweekly",
    "robotonly",
    "robots",
    "robotstatus",
}

CONTROL_NAMES = {
    "reset",
    "newthread",
    "restart",
    "panic",
    "clearqueue",
    "clearschedule",
    "clearschedules",
    "run",
    "agent",
    "agentresume",
    "schedule",
}

MENU_COMMAND_PREFIX = "menu:"
BRAIN_COMMAND_PREFIX = "brain:"
UI_BUILD_TAG = "ui-build:2026-04-10-b"
HOSTED_BUILD_TAG = "hosted-build:2026-04-10-c"
FLOW_AWAIT_MODEL = "await_model"
FLOW_AWAIT_PROVIDER = "await_provider"
FLOW_AWAIT_PROJECT = "await_project"
FLOW_AWAIT_BRAIN_CAPTURE = "await_brain_capture"
FLOW_AWAIT_BRAIN_INBOX = "await_brain_inbox"
FLOW_AWAIT_BRAIN_SEARCH = "await_brain_search"
FLOW_AWAIT_BRAIN_DECIDE = "await_brain_decide"
FLOW_AWAIT_BRAIN_PROJECT = "await_brain_project"
FLOW_AWAIT_BRAIN_KNOWLEDGE = "await_brain_knowledge"
FLOW_AWAIT_BRAIN_RESOURCE = "await_brain_resource"
FLOW_AWAIT_BRAIN_SCHEDULE_TITLE = "await_brain_schedule_title"
FLOW_AWAIT_BRAIN_SCHEDULE_DATE = "await_brain_schedule_date"
FLOW_AWAIT_BRAIN_SCHEDULE_TIME = "await_brain_schedule_time"
FLOW_AWAIT_BRAIN_SCHEDULE_CONFIRM = "await_brain_schedule_confirm"
FLOW_AWAIT_BRAIN_SCHEDULE_DELETE_CONFIRM = "await_brain_schedule_delete_confirm"
FLOW_AWAIT_BRAIN_SCHEDULE_UPDATE_CONFIRM = "await_brain_schedule_update_confirm"
FLOW_AWAIT_BRAIN_ORGANIZE_TEXT = "await_brain_organize_text"
FLOW_AWAIT_BRAIN_ORGANIZE_TARGET = "await_brain_organize_target"
FLOW_AWAIT_BRAIN_ORGANIZE_TITLE = "await_brain_organize_title"
FLOW_BRAIN_SEARCH_RESULTS = "brain_search_results"
FLOW_BRAIN_BATCH_RESULTS = "brain_batch_results"


def _runtime_git_commit() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=1.5,
        )
    except (FileNotFoundError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return "-"
    return (completed.stdout or "").strip() or "-"


def _project_display(project_name: object, project_path: object) -> str:
    return format_project_with_branch(
        str(project_name or "-"),
        str(project_path or ""),
    )


def _schedule_confirm_response(parsed: dict[str, str]) -> ButtonResponse:
    return ButtonResponse(
        "\n".join(
            [
                "看起來像一筆行程，要怎麼處理？",
                "",
                f"標題: {parsed['title']}",
                f"日期: {parsed['date_text']}",
                f"時間: {parsed['time_text']}",
                "",
                f"原文: {parsed['source_text']}",
                "",
                "按「確認建立」會寫入第二大腦。",
                "按「改送 Claude」會把原句直接送去 AI。",
                "按「取消」也會改送 Claude，不會建立行程。",
                "如果你只是想問 AI，不要建立行程，請按「改送 Claude」。",
            ]
        ),
        buttons=[
            Button("確認建立", "brain:schedule_confirm"),
            Button("改送 Claude", "brain:schedule_send_agent"),
            Button("取消", "brain:cancel"),
        ],
    )


def _schedule_delete_confirm_response(match: dict[str, str], source_text: str) -> ButtonResponse:
    recurrence_label = str(match.get("recurrence") or "").strip()
    recurrence = " ".join(
        part for part in [recurrence_label, match.get("time") or ""] if part
    ).strip()
    when = recurrence or " ".join(part for part in [match.get("date") or "", match.get("time") or ""] if part).strip() or "未排時間"
    warning_line = (
        "這是一筆週期性行程。刪除後會停止未來所有重複提醒。"
        if recurrence_label
        else "這是一筆單次行程。刪除後只會移除這一筆。"
    )
    return ButtonResponse(
        "\n".join(
            [
                "看起來你是要刪除一筆行程，要怎麼處理？",
                "",
                f"標題: {match.get('title') or ''}",
                f"時間: {when}",
                f"path: {match.get('path') or ''}",
                "",
                f"原文: {source_text}",
                "",
                warning_line,
                "按「確認刪除」會把這筆行程移到 Archive。",
                "按「改送 Claude」會把原句直接送去 AI。",
            ]
        ),
        buttons=[
            Button("確認刪除", "brain:schedule_delete_confirm"),
            Button("改送 Claude", "brain:schedule_send_agent"),
            Button("取消", "brain:cancel"),
        ],
    )


def _schedule_update_confirm_response(match: dict[str, str], updates: dict[str, str], source_text: str) -> ButtonResponse:
    current_when = " ".join(part for part in [match.get("date") or "", match.get("time") or ""] if part).strip() or "未排時間"
    new_when = " ".join(part for part in [updates.get("date_text") or "", updates.get("time_text") or ""] if part).strip() or current_when
    recurrence_type = (updates.get("recurrence_type") or "").strip()
    recurrence_value = (updates.get("recurrence_value") or "").strip()
    recurrence_line = ""
    if recurrence_type == "daily":
        recurrence_line = "新的週期: 每天"
    elif recurrence_type == "weekly":
        labels = ["每週一", "每週二", "每週三", "每週四", "每週五", "每週六", "每週日"]
        try:
            weekday = int(recurrence_value)
        except ValueError:
            weekday = -1
        recurrence_line = f"新的週期: {labels[weekday] if 0 <= weekday < len(labels) else '每週'}"
    elif recurrence_type == "monthly":
        recurrence_line = f"新的週期: 每月{recurrence_value}號" if recurrence_value else "新的週期: 每月"
    elif recurrence_type == "":
        recurrence_line = "新的週期: 單次行程"
    lines = [
        "看起來你是要修改一筆行程，要怎麼處理？",
        "",
        f"標題: {match.get('title') or ''}",
        f"目前: {current_when}",
        f"更新後: {new_when}",
    ]
    if recurrence_line:
        lines.append(recurrence_line)
    lines.extend(
        [
            f"path: {match.get('path') or ''}",
            "",
            f"原文: {source_text}",
            "",
            "按「確認修改」會直接更新這筆行程。",
            "按「改送 Claude」會把原句直接送去 AI。",
        ]
    )
    return ButtonResponse(
        "\n".join(lines),
        buttons=[
            Button("確認修改", "brain:schedule_update_confirm"),
            Button("改送 Claude", "brain:schedule_send_agent"),
            Button("取消", "brain:cancel"),
        ],
    )


def _schedule_occurrences_response(
    chat_id: int,
    store: ChatStateStore,
    settings: Settings,
    *,
    period: str,
    limit: int,
) -> str:
    title, items = list_schedule_occurrences(settings, period=period, limit=limit)
    store.set_last_schedule_results(chat_id, items)
    lines = [title, ""]
    if not items:
        lines.append("- 目前沒有符合條件的行程")
        return "\n".join(lines)
    for item in items:
        recurrence_note = f" ({item.get('recurrence')})" if item.get("recurrence") else ""
        lines.append(f"- {item.get('date')} {item.get('time')} | {item.get('title')}{recurrence_note}")
        lines.append(f"  {item.get('path')}")
    return "\n".join(lines)


def _set_schedule_confirm_flow(chat_id: int, store: ChatStateStore, parsed: dict[str, str]) -> None:
    flow = {"kind": FLOW_AWAIT_BRAIN_SCHEDULE_CONFIRM, **parsed}
    store.set_ui_flow(chat_id, flow)
    store.set_last_schedule_candidate(chat_id, flow)


async def _send_schedule_confirm_source_to_agent(
    chat_id: int,
    store: ChatStateStore,
    agents: AgentCoordinator,
) -> str:
    flow = store.get_ui_flow(chat_id)
    valid_kinds = {FLOW_AWAIT_BRAIN_SCHEDULE_CONFIRM, FLOW_AWAIT_BRAIN_SCHEDULE_DELETE_CONFIRM}
    valid_kinds.add(FLOW_AWAIT_BRAIN_SCHEDULE_UPDATE_CONFIRM)
    if not isinstance(flow, dict) or flow.get("kind") not in valid_kinds:
        flow = store.get_last_schedule_candidate(chat_id)
    if not isinstance(flow, dict) or flow.get("kind") not in valid_kinds:
        return "目前沒有可改送 Claude 的行程原文。請直接重新輸入原句。"
    source_text = str(flow.get("source_text") or "").strip()
    store.clear_ui_flow(chat_id)
    store.clear_last_schedule_candidate(chat_id)
    if not source_text:
        return "原始訊息遺失，無法送到 Claude。"
    return await handle_agent(chat_id, ClassifiedRequest(AGENT_REQUEST, None, source_text), store, agents)


def _document_import_error_message(source_name: str, exc: Exception) -> str:
    message = str(exc).strip()
    lowered = message.lower()
    if isinstance(exc, FileConversionException) and "markitdown[pdf]" in lowered:
        return (
            "文件已收到，但目前這個環境還沒有安裝 PDF 轉換依賴，所以無法匯入內容。\n"
            f"source_file: {source_name}\n"
            "needed: pip install markitdown[pdf]"
        )
    if isinstance(exc, MarkItDownException):
        details = message.splitlines()[0] if message else exc.__class__.__name__
        return (
            "文件已收到，但目前無法轉換這個檔案內容。\n"
            f"source_file: {source_name}\n"
            f"error: {details}"
        )
    raise exc


@dataclass(slots=True)
class ClassifiedRequest:
    kind: str
    command: str | None
    payload: str

    request_id: str | None = None


def heartbeat_status_key(request_id: str | None) -> str:
    clean = str(request_id or "").strip()
    if not clean:
        return "heartbeat"
    return f"heartbeat:{clean}"


def _status_event(
    chat_id: int,
    text: str,
    *,
    status_key: str = "heartbeat",
    replace: bool = False,
    request_id: str | None = None,
) -> AppEvent:
    return AppEvent(
        type="status",
        text=text,
        chat_id=chat_id,
        request_id=request_id,
        stream="inprocess",
        raw={"status_key": status_key, "replace": replace},
    )


@dataclass(slots=True)
class AutoDevOptions:
    goal: str | None
    profile: str | None
    config_path: str | None
    enable_commit: bool
    enable_push: bool
    enable_pr: bool
    disable_post_run: bool


def _command_payload(text: str) -> str:
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[1].strip()


def _resolved_payload(text: str, command: str | None) -> str:
    stripped = (text or "").strip()
    if command:
        if stripped.startswith("/"):
            return _command_payload(stripped)
        return stripped
    return _command_payload(stripped) if stripped.startswith("/") else stripped


def _extract_command_from_text(text: str) -> str | None:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    head = stripped.split(maxsplit=1)[0]
    token = head[1:]
    if not token:
        return None
    base = token.split("@", 1)[0].strip().lower()
    return base or None


def _split_payload(payload: str) -> list[str]:
    if not payload.strip():
        return []
    try:
        return shlex.split(payload, posix=True)
    except ValueError:
        return []


def _split_payload_windows(payload: str) -> list[str]:
    if not payload.strip():
        return []
    try:
        return shlex.split(payload, posix=False)
    except ValueError:
        return _split_payload(payload)


class _SilentArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _build_agent_parser() -> argparse.ArgumentParser:
    parser = _SilentArgumentParser(add_help=False)
    parser.add_argument("--profile")
    parser.add_argument("--config")
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--pr", action="store_true")
    parser.add_argument("--no-post-run", action="store_true")
    parser.add_argument("goal", nargs=argparse.REMAINDER)
    return parser


def _build_resume_parser() -> argparse.ArgumentParser:
    parser = _SilentArgumentParser(add_help=False)
    parser.add_argument("resume", nargs="?")
    parser.add_argument("--profile")
    parser.add_argument("--config")
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--pr", action="store_true")
    parser.add_argument("--no-post-run", action="store_true")
    return parser


def _build_schedule_parser() -> argparse.ArgumentParser:
    parser = _SilentArgumentParser(add_help=False)
    parser.add_argument("date")
    parser.add_argument("time")
    parser.add_argument("--profile")
    parser.add_argument("--config")
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--pr", action="store_true")
    parser.add_argument("--no-post-run", action="store_true")
    parser.add_argument("goal", nargs=argparse.REMAINDER)
    return parser


def _parse_agent_options(payload: str) -> tuple[AutoDevOptions | None, str | None]:
    parser = _build_agent_parser()
    try:
        parsed = parser.parse_args(_split_payload(payload))
    except (SystemExit, ValueError):
        return None, "Usage: /agent [--profile NAME] [--config PATH] [--commit] [--push] [--pr] [--no-post-run] <goal>"

    goal = " ".join(parsed.goal).strip()
    if not goal:
        return None, "Usage: /agent [--profile NAME] [--config PATH] [--commit] [--push] [--pr] [--no-post-run] <goal>"

    return (
        AutoDevOptions(
            goal=goal,
            profile=parsed.profile,
            config_path=parsed.config,
            enable_commit=bool(parsed.commit),
            enable_push=bool(parsed.push),
            enable_pr=bool(parsed.pr),
            disable_post_run=bool(parsed.no_post_run),
        ),
        None,
    )


def _parse_resume_options(payload: str) -> tuple[dict[str, AutoDevOptions | str] | None, str | None]:
    parser = _build_resume_parser()
    try:
        parsed = parser.parse_args(_split_payload(payload))
    except (SystemExit, ValueError):
        return None, "Usage: /agentresume [run_id_or_path] [--profile NAME] [--config PATH] [--commit] [--push] [--pr] [--no-post-run]"

    return (
        {
            "resume": (parsed.resume or "").strip(),
            "options": AutoDevOptions(
                goal=None,
                profile=parsed.profile,
                config_path=parsed.config,
                enable_commit=bool(parsed.commit),
                enable_push=bool(parsed.push),
                enable_pr=bool(parsed.pr),
                disable_post_run=bool(parsed.no_post_run),
            ),
        },
        None,
    )


def _parse_schedule_options(payload: str) -> tuple[dict[str, str | AutoDevOptions] | None, str | None]:
    parser = _build_schedule_parser()
    try:
        parsed = parser.parse_args(_split_payload(payload))
    except (SystemExit, ValueError):
        return None, "Usage: /schedule YYYY-MM-DD HH:MM [--profile NAME] [--config PATH] [--commit] [--push] [--pr] [--no-post-run] <goal>"

    goal = " ".join(parsed.goal).strip()
    if not goal:
        return None, "Usage: /schedule YYYY-MM-DD HH:MM [--profile NAME] [--config PATH] [--commit] [--push] [--pr] [--no-post-run] <goal>"

    try:
        run_at = datetime.strptime(f"{parsed.date} {parsed.time}", "%Y-%m-%d %H:%M").isoformat(timespec="minutes")
    except ValueError:
        return None, "Invalid schedule time. Use YYYY-MM-DD HH:MM"

    return (
        {
            "run_at": run_at,
            "options": AutoDevOptions(
                goal=goal,
                profile=parsed.profile,
                config_path=parsed.config,
                enable_commit=bool(parsed.commit),
                enable_push=bool(parsed.push),
                enable_pr=bool(parsed.pr),
                disable_post_run=bool(parsed.no_post_run),
            ),
        },
        None,
    )


def _parse_schedule_sync_options(payload: str) -> tuple[tuple[str, int, int] | None, str | None]:
    parts = payload.split()
    if not parts or parts[0].lower() != "sync":
        return None, None

    rest = parts[1:]
    if len(rest) > 3:
        return None, "Usage: /schedule sync [push|pull|both] [days] [limit]"

    mode = "both"
    days = 30
    limit = 200
    if rest and rest[0].lower() in {"push", "pull", "both"}:
        mode = rest.pop(0).lower()

    if rest:
        try:
            days = int(rest[0])
        except ValueError:
            return None, "Usage: /schedule sync [push|pull|both] [days] [limit]"
    if len(rest) >= 2:
        try:
            limit = int(rest[1])
        except ValueError:
            return None, "Usage: /schedule sync [push|pull|both] [days] [limit]"

    if days < 1 or days > 120:
        return None, "days must be between 1 and 120."
    if limit < 1 or limit > 500:
        return None, "limit must be between 1 and 500."
    return (mode, days, limit), None


def _sendmail_root_path() -> Path:
    return (Path.home() / "codex" / "sendmail").expanduser()


def _load_sendmail_env(sendmail_root: Path) -> dict[str, str]:
    env: dict[str, str] = dict(os.environ)
    env_file = sendmail_root / ".env"
    if not env_file.exists():
        return env
    loaded = dotenv_values(env_file)
    for key, value in loaded.items():
        if key and value is not None:
            env[str(key)] = str(value)
    return env


def _resolve_input_path(raw_path: str, *, project_path: str, settings: Settings) -> Path:
    from robot.security import validate_path_traversal, SecurityError

    candidate = Path(str(raw_path or "").strip()).expanduser()

    # Build allowed roots
    allowed_roots: list[Path] = []
    if project_path.strip():
        allowed_roots.append(Path(project_path).expanduser())
    allowed_roots.append(settings.project_root)
    allowed_roots.append(_sendmail_root_path())

    # If absolute path, validate it's within allowed roots
    if candidate.is_absolute():
        try:
            return validate_path_traversal(candidate, allowed_roots, must_exist=False)
        except SecurityError as exc:
            raise ValueError(f"Path validation failed: {exc}") from exc

    # For relative paths, try each root
    for root in allowed_roots:
        resolved = root / candidate
        try:
            validated = validate_path_traversal(resolved, allowed_roots, must_exist=False)
            if validated.exists():
                return validated
        except SecurityError:
            continue

    # Default to project root, but still validate
    default_path = settings.project_root / candidate
    try:
        return validate_path_traversal(default_path, allowed_roots, must_exist=False)
    except SecurityError as exc:
        raise ValueError(f"Path validation failed: {exc}") from exc


def _resolve_single_contact_target(store: ChatStateStore, target: str) -> tuple[str | None, str | None]:
    token = str(target or "").strip()
    if not token:
        return None, "recipient target is empty."
    resolved = store.resolve_contacts([token])
    ambiguous = resolved.get("ambiguous")
    if isinstance(ambiguous, dict) and token in ambiguous:
        keys = ambiguous.get(token)
        return None, f"ambiguous recipient: {token} -> {', '.join(str(item) for item in (keys or []))}"
    unresolved = resolved.get("unresolved")
    if isinstance(unresolved, list) and unresolved:
        return None, f"recipient not found in contacts: {token}"
    emails = resolved.get("emails")
    if not isinstance(emails, list) or not emails:
        return None, f"recipient resolve failed: {token}"
    if len(emails) > 1:
        return None, f"recipient resolved to multiple emails: {token}"
    return str(emails[0]), None


def _rewrite_mailcli_targets(store: ChatStateStore, args: list[str]) -> tuple[list[str] | None, str | None]:
    rewritten: list[str] = []
    target_flags = {"-t", "--to", "-c", "--cc", "-bc", "--bcc"}
    i = 0
    while i < len(args):
        token = str(args[i])
        rewritten.append(token)
        if token not in target_flags:
            i += 1
            continue
        if i + 1 >= len(args):
            return None, f"missing value for flag: {token}"
        raw_target = str(args[i + 1])
        email, error = _resolve_single_contact_target(store, raw_target)
        if error is not None:
            return None, error
        rewritten.append(str(email))
        i += 2
    return rewritten, None


def _rewrite_json_recipients_with_contacts(
    store: ChatStateStore,
    config: dict[str, object],
) -> tuple[dict[str, object] | None, str | None]:
    rewritten = dict(config)
    for field in ("to", "cc", "bcc"):
        value = rewritten.get(field)
        if value is None:
            continue
        if field == "to":
            email, error = _resolve_single_contact_target(store, str(value))
            if error is not None:
                return None, f"{field}: {error}"
            rewritten[field] = email
            continue

        targets: list[str] = []
        if isinstance(value, str):
            targets = [value]
        elif isinstance(value, list):
            targets = [str(item) for item in value if str(item).strip()]
        else:
            return None, f"{field}: must be string or list."
        resolved_targets: list[str] = []
        for item in targets:
            email, error = _resolve_single_contact_target(store, item)
            if error is not None:
                return None, f"{field}: {error}"
            resolved_targets.append(str(email))
        rewritten[field] = resolved_targets
    return rewritten, None


def _run_sendmail(
    settings: Settings,
    *,
    args: list[str],
) -> tuple[bool, str]:
    from robot.security import validate_command_args, sanitize_error_message, SecurityError

    sendmail_root = _sendmail_root_path()
    sendmail_script = sendmail_root / "sendmail.py"
    if not sendmail_root.exists():
        return False, f"sendmail root not found: {sendmail_root}"
    if not sendmail_script.exists():
        return False, f"sendmail script not found: {sendmail_script}"

    # Validate all arguments for security
    try:
        validated_args = validate_command_args(args)
    except SecurityError as exc:
        error_msg = sanitize_error_message(str(exc), settings.project_root)
        return False, f"sendmail argument validation failed: {error_msg}"

    command = [sys.executable, str(sendmail_script), *validated_args]
    env = _load_sendmail_env(sendmail_root)

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(settings.project_root),
            env=env,
        )
    except (FileNotFoundError, OSError) as exc:
        error_msg = sanitize_error_message(str(exc), settings.project_root)
        return False, f"sendmail execution failed: {error_msg}"
    except subprocess.TimeoutExpired:
        return False, "sendmail execution timed out after 120 seconds."

    stdout_text = (completed.stdout or "").strip()
    stderr_text = (completed.stderr or "").strip()

    # Sanitize output to avoid leaking sensitive info
    stdout_text = sanitize_error_message(stdout_text, settings.project_root)
    stderr_text = sanitize_error_message(stderr_text, settings.project_root)

    lines = [
        f"ok: {completed.returncode == 0}",
        f"return_code: {completed.returncode}",
        # Don't include full command in output (may contain sensitive data)
        "command: sendmail.py [args redacted]",
    ]
    if stdout_text:
        lines.append("stdout:")
        lines.append(stdout_text)
    if stderr_text:
        lines.append("stderr:")
        lines.append(stderr_text)
    return completed.returncode == 0, "\n".join(lines)


def classify_request(ctx: MessageContext) -> ClassifiedRequest:
    text = (ctx.text or "").strip()
    command = (ctx.command or "").strip().lower() or None
    if command and command.startswith("/"):
        command = command[1:]
    if command and "@" in command:
        command = command.split("@", 1)[0].strip() or None
    if command is None and text.startswith("/"):
        command = _extract_command_from_text(text)

    if command == "menu" or (command and command.startswith(MENU_COMMAND_PREFIX)):
        return ClassifiedRequest(COMMAND_REQUEST, command, "", ctx.request_id)
    if command == "brain" or (command and command.startswith(BRAIN_COMMAND_PREFIX)):
        return ClassifiedRequest(COMMAND_REQUEST, command, "", ctx.request_id)

    if command in COMMAND_NAMES:
        return ClassifiedRequest(COMMAND_REQUEST, command, _resolved_payload(text, command), ctx.request_id)
    if command in CONTROL_NAMES:
        return ClassifiedRequest(CONTROL_REQUEST, command, _resolved_payload(text, command), ctx.request_id)
    if command is not None:
        return ClassifiedRequest(COMMAND_REQUEST, command, _resolved_payload(text, command), ctx.request_id)
    if text.startswith("/"):
        return ClassifiedRequest(COMMAND_REQUEST, command, _command_payload(text), ctx.request_id)
    return ClassifiedRequest(AGENT_REQUEST, None, text, ctx.request_id)


def _status_text(chat_id: int, store: ChatStateStore, settings: Settings) -> str:
    state = store.get_chat_state(chat_id)
    queued_jobs = len(store.get_agent_queue(chat_id))
    scheduled_jobs = len(store.get_agent_schedules(chat_id))
    flow = store.get_ui_flow(chat_id)
    flow_kind = flow.get("kind") if isinstance(flow, dict) else None
    current_run = state["agent_current_run"] if isinstance(state["agent_current_run"], dict) else None
    last_run = state["agent_last_run"] if isinstance(state["agent_last_run"], dict) else None
    provider_timing = state.get("last_provider_timing") if isinstance(state.get("last_provider_timing"), dict) else {}
    teleapp_status_edit = "enabled"
    teleapp_raw_status = "enabled"
    risk_mode = bool(settings.codex_bypass_approvals_and_sandbox or settings.codex_skip_git_repo_check)
    return "\n".join(
        [
            "robot status",
            f"version: {VERSION}",
            f"provider: {state['provider']}",
            f"model: {state['model']}",
            f"project: {_project_display(state['project_name'], state['project_path'])}",
            f"path: {state['project_path']}",
            f"thread_id: {state['thread_id'] or '-'}",
            f"queued_jobs: {queued_jobs}",
            f"scheduled_jobs: {scheduled_jobs}",
            f"ui_flow: {flow_kind or '-'}",
            f"current_run: {current_run.get('kind') if current_run else '-'}",
            f"last_run_status: {last_run.get('status') if last_run else '-'}",
            f"provider_elapsed_seconds: {provider_timing.get('elapsed_seconds', '-')}",
            f"provider_return_code: {provider_timing.get('return_code', '-')}",
            f"provider_cancelled: {provider_timing.get('cancelled', '-')}",
            f"security_risk_mode: {'on' if risk_mode else 'off'}",
            f"codex_bypass_approvals_and_sandbox: {settings.codex_bypass_approvals_and_sandbox}",
            f"codex_skip_git_repo_check: {settings.codex_skip_git_repo_check}",
            f"ui_build: {UI_BUILD_TAG}",
            f"hosted_build: {HOSTED_BUILD_TAG}",
            f"runtime_commit: {_runtime_git_commit()}",
            f"teleapp_status_edit: {teleapp_status_edit}",
            f"teleapp_raw_status: {teleapp_raw_status}",
            "",
            "request classes:",
            "- command request: /provider /model /project /status /doctor /queue /schedules /agentstatus /agentprofiles",
            "- control request: /reset /newthread /restart /panic /run /agent /agentresume /schedule /clearschedule",
            "- agent request: plain text (provider runner)",
        ]
    )


def _help_text() -> str:
    return "\n".join(
        [
            "robot",
            "",
            "deterministic commands:",
            "general:",
            "/quick  /guide  /menu  /help",
            "/status  /doctor  /queue  /schedules",
            "/agentstatus  /agentprofiles [--config PATH]",
            "/contact list  /contact add <key> <email> <name>",
            "",
            "workspace:",
            "/provider [claude|codex|gemini]",
            "/model [name]  /models",
            "/project register [name] <path>",
            "/project list",
            "/project use <name|key>",
            "/project info <name|key>",
            "/project note <name|key> <text>",
            "/project doctor <name|key|all>",
            "/projects ... (legacy alias of /project ...)",
            "",
            "email (sendmail):",
            "/mailcli <sendmail-cli-args>",
            "/mailjson <config.json>",
            "/mailbatch <recipients.csv> <base_config.json>",
            "/mailmcp",
            "",
            "second brain:",
            "/brain  /brainread  /braininbox <text>  /brainweb <url>",
            "/brainsearch <query>  /brainorganize  /brainbatch  /brainbatchauto [limit]",
            "/brainproject <title>  /brainknowledge <title>  /brainresource <title>",
            "/brainschedule <title>  /braindecide <question>  /brainsummary",
            "/brainremind  /braindaily  /brainweekly",
            "/brainauto [on|off|status]",
            "/brainautodaily HH:MM",
            "/brainautoweekly <weekday 0-6> HH:MM",
            "/robotonly",
            "",
            "control commands:",
            "/reset",
            "/newthread",
            "/restart",
            "/panic",
            "/clearqueue",
            "/clearschedule (/clearschedules)",
            "/clearschedules",
            "/run <goal>",
            "/agent [--profile NAME] [--config PATH] [--commit] [--push] [--pr] [--no-post-run] <goal>",
            "/agentresume [run_id_or_path] [--profile NAME] [--config PATH] [--commit] [--push] [--pr] [--no-post-run]",
            "/schedule YYYY-MM-DD HH:MM [--profile NAME] [--config PATH] [--commit] [--push] [--pr] [--no-post-run] <goal>",
            "/schedule sync [push|pull|both] [days] [limit]",
            "",
            "agent requests:",
            "- normal text message (provider runner)",
            "",
            "note:",
            "- semantic shortcuts are disabled; use slash commands or Telegram buttons.",
        ]
    )


def _quick_text() -> str:
    return "\n".join(
        [
            "quick reference",
            "",
            "system setup:",
            "- /menu (主選單)",
            "- /provider [claude|codex|gemini]",
            "- /model [name] /models",
            "- /project register [name] <path>",
            "- /project list",
            "- /project use <name|key>",
            "",
            "daily commands:",
            "- /status",
            "- /mailjson <config.json>",
            "- /braininbox <text>",
            "- /brainsearch <query>",
            "- /brainbatchauto [limit]",
            "- /brainweb <url>",
            "- /brainschedule <title-or-natural-language>",
            "",
            "short daily flow:",
            "1. /braininbox <today idea>",
            "2. /brainbatchauto 5",
            "3. /braindaily",
            "",
            "more: /guide",
        ]
    )


def _guide_text() -> str:
    return "\n".join(
        [
            "features guide",
            "",
            "See these docs in repository root:",
            "- FEATURES_GUIDE.md (full guide: features, scenarios, examples)",
            "- QUICK_REFERENCE.md (one-page quick reference)",
            "",
            "most useful commands:",
            "- /quick",
            "- /help",
            "- /menu",
            "- /contact list /contact add <key> <email> <name>",
            "- /provider /model /project list",
            "- /project use <name|key>",
            "- /brain",
            "- /brainweb <url>",
            "- /brainbatchauto [limit]",
            "- /mailcli /mailjson /mailbatch /mailmcp",
        ]
    )


def _menu_text(chat_id: int, store: ChatStateStore) -> str:
    state = store.get_chat_state(chat_id)
    return "\n".join(
        [
            "robot menu",
            UI_BUILD_TAG,
            f"provider: {state['provider']}",
            f"model: {state['model']}",
            f"project: {_project_display(state['project_name'], state['project_path'])}",
            "",
            "menu actions:",
            "- status",
            "- provider",
            "- model",
            "- projects",
            "- cancel",
            "",
            "slash commands:",
            "- /status",
            "- /provider claude",
            "- /model gpt-5.4",
            "- /project list",
            "- /project use <name|key>",
            "",
            "其他自然語言訊息不會被選單吃掉，會直接送進 AI。",
        ]
    )


def _brain_text() -> str:
    return "\n".join(
        [
            "brain menu",
            UI_BUILD_TAG,
            "使用 TG 操作 secondbrain",
            "",
            "brain actions:",
            "- 寫入今日",
            "- Inbox",
            "- 讀今日",
            "- 搜尋",
            "- 整理",
            "- 批次整理",
            "- 自動批次整理",
            "- 專案",
            "- 知識卡",
            "- 資源",
            "- 行程",
            "- 摘要",
            "- 決策支援",
            "- 提醒",
            "- 每日摘要",
            "- 週摘要",
        ]
    )


def _brain_menu_response(chat_id: int, store: ChatStateStore) -> ButtonResponse:
    return ButtonResponse(
        _brain_text(),
        buttons=[
            Button("寫入今日", "brain:capture"),
            Button("Inbox", "brain:inbox"),
            Button("讀今日", "brain:read"),
            Button("搜尋", "brain:search"),
            Button("整理", "brain:organize"),
            Button("批次整理", "brain:batch"),
            Button("自動批次整理", "brain:batch_auto"),
            Button("專案", "brain:project"),
            Button("知識卡", "brain:knowledge"),
            Button("資源", "brain:resource"),
            Button("行程", "brain:schedule"),
            Button("摘要", "brain:summary"),
            Button("決策支援", "brain:decide"),
            Button("提醒", "brain:remind"),
            Button("每日摘要", "brain:daily"),
            Button("週摘要", "brain:weekly"),
            Button("取消", "brain:cancel"),
        ],
    )


async def _handle_brain_action(
    chat_id: int,
    command: str,
    settings: Settings,
    store: ChatStateStore,
    agents: AgentCoordinator,
):
    if command in {"brain", "brain:open"}:
        return _brain_menu_response(chat_id, store)

    if command == "brain:cancel":
        flow = store.get_ui_flow(chat_id)
        if isinstance(flow, dict) and flow.get("kind") == FLOW_AWAIT_BRAIN_SCHEDULE_CONFIRM:
            return await _send_schedule_confirm_source_to_agent(chat_id, store, agents)
        store.clear_ui_flow(chat_id)
        return "Brain menu canceled."

    if command == "brain:capture":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_CAPTURE})
        return "請輸入要寫入今日 daily note 的內容。輸入 /menu 可離開流程。"

    if command == "brain:inbox":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_INBOX})
        return "請輸入要存進 Inbox 的內容。輸入 /menu 可離開流程。"

    if command == "brain:read":
        body = read_daily(settings).strip()
        return body if body else "今日 daily note 目前是空的。"

    if command == "brain:search":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_SEARCH})
        return "請輸入要搜尋 secondbrain 的關鍵字。輸入 /menu 可離開流程。"

    if command == "brain:organize":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_ORGANIZE_TEXT})
        return "請先貼上你要整理的原始內容。輸入 /menu 可離開流程。"

    if command == "brain:batch":
        items = list_recent_notes(settings, "00 Inbox", limit=5) + list_recent_notes(settings, "01 Daily Notes", limit=5)
        items = items[:10]
        if not items:
            return "目前沒有可批次整理的 Inbox / Daily 筆記。"
        store.set_ui_flow(chat_id, {"kind": FLOW_BRAIN_BATCH_RESULTS, "results": items})
        return ButtonResponse(
            "選一篇最近的 Inbox / Daily 筆記來整理：",
            buttons=[Button(item, f"brain:batch_open:{idx}") for idx, item in enumerate(items)],
        )

    if command == "brain:batch_auto":
        summary = auto_organize_recent_notes(settings, limit=10)
        processed = int(summary.get("processed") or 0)
        if processed == 0:
            return "目前沒有可自動整理的 Inbox / Daily 筆記。"
        by_type = summary.get("by_type")
        items = summary.get("items")
        if not isinstance(by_type, dict):
            by_type = {}
        if not isinstance(items, list):
            items = []
        lines = [
            "自動批次整理完成：",
            f"- processed: {processed}",
            f"- created: {int(summary.get('created') or 0)}",
            f"- skipped: {int(summary.get('skipped') or 0)}",
            f"- failed: {int(summary.get('failed') or 0)}",
            "",
            "分類統計：",
            f"- project: {int(by_type.get('project') or 0)}",
            f"- knowledge: {int(by_type.get('knowledge') or 0)}",
            f"- resource: {int(by_type.get('resource') or 0)}",
        ]
        created_items = [item for item in items if isinstance(item, dict) and item.get("status") == "created"]
        if created_items:
            lines.append("")
            lines.append("新建立筆記：")
            for item in created_items[:10]:
                lines.append(f"- {item.get('source_path')} -> {item.get('path')} ({item.get('target')})")
        failed_items = [item for item in items if isinstance(item, dict) and item.get("status") == "failed"]
        if failed_items:
            lines.append("")
            lines.append("失敗項目：")
            for item in failed_items[:5]:
                lines.append(f"- {item.get('source_path')}: {item.get('error') or 'unknown error'}")
        return "\n".join(lines)

    if command == "brain:project":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_PROJECT})
        return "請輸入專案名稱，我會建立 project note。輸入 /menu 可離開流程。"

    if command == "brain:knowledge":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_KNOWLEDGE})
        return "請輸入知識卡標題，我會建立 knowledge note。輸入 /menu 可離開流程。"

    if command == "brain:resource":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_RESOURCE})
        return "請輸入 resource 標題，我會建立 resource note。輸入 /menu 可離開流程。"

    if command == "brain:schedule":
        return ButtonResponse(
            "行程選單",
            buttons=[
                Button("新增", "brain:schedule_new"),
                Button("今日", "brain:schedule_today"),
                Button("本週", "brain:schedule_week"),
                Button("下週", "brain:schedule_next_week"),
                Button("本月", "brain:schedule_month"),
                Button("列表", "brain:schedule_list"),
                Button("取消", "brain:cancel"),
            ],
        )

    if command == "brain:schedule_new":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_SCHEDULE_TITLE})
        return "請輸入行程標題，或直接輸入自然語言，例如：今天下午6點半要吃藥。輸入 /menu 可離開流程。"

    if command == "brain:schedule_today":
        return _schedule_occurrences_response(chat_id, store, settings, period="day", limit=50)

    if command == "brain:schedule_week":
        return _schedule_occurrences_response(chat_id, store, settings, period="week", limit=80)

    if command == "brain:schedule_next_week":
        return _schedule_occurrences_response(chat_id, store, settings, period="next_week", limit=80)

    if command == "brain:schedule_month":
        return _schedule_occurrences_response(chat_id, store, settings, period="month", limit=120)

    if command == "brain:schedule_list":
        return build_schedule_brief(settings, today_only=False, limit=10)

    if command == "brain:schedule_archive_past":
        archived = archive_past_due_schedule_notes(settings, limit=200)
        if not archived:
            return "目前沒有已過期且可封存的單次行程。"
        lines = ["已封存過期行程：", ""]
        for item in archived:
            when = " ".join(part for part in [item.get("date") or "", item.get("time") or ""] if part).strip()
            lines.append(f"- {when} | {item.get('title')}")
            lines.append(f"  from: {item.get('path')}")
            lines.append(f"  to: {item.get('archived_path')}")
        return "\n".join(lines)

    if command == "brain:schedule_confirm":
        flow = store.get_ui_flow(chat_id)
        if not isinstance(flow, dict) or flow.get("kind") != FLOW_AWAIT_BRAIN_SCHEDULE_CONFIRM:
            return "目前沒有待確認的行程。請重新開始。"
        title = str(flow.get("title") or "").strip()
        date_text = str(flow.get("date_text") or "").strip()
        time_text = str(flow.get("time_text") or "").strip()
        recurrence_type = str(flow.get("recurrence_type") or "").strip()
        recurrence_value = str(flow.get("recurrence_value") or "").strip()
        if not title:
            store.clear_ui_flow(chat_id)
            return "行程資料遺失，請重新開始。"
        path = create_schedule_note(
            settings,
            title,
            date_text=date_text,
            time_text=time_text,
            recurrence_type=recurrence_type,
            recurrence_value=recurrence_value,
        )
        body = read_note(settings, path).strip()
        store.clear_ui_flow(chat_id)
        store.clear_last_schedule_candidate(chat_id)
        return f"已建立 Schedule 筆記：{path}\n\n{body}"

    if command == "brain:schedule_send_agent":
        return await _send_schedule_confirm_source_to_agent(chat_id, store, agents)

    if command == "brain:schedule_delete_confirm":
        flow = store.get_ui_flow(chat_id)
        if not isinstance(flow, dict) or flow.get("kind") != FLOW_AWAIT_BRAIN_SCHEDULE_DELETE_CONFIRM:
            return "目前沒有待刪除確認的行程。請重新開始。"
        path = str(flow.get("path") or "").strip()
        if not path:
            store.clear_ui_flow(chat_id)
            store.clear_last_schedule_candidate(chat_id)
            return "行程路徑遺失，請重新開始。"
        archived_path = archive_schedule_note(settings, path)
        store.clear_ui_flow(chat_id)
        store.clear_last_schedule_candidate(chat_id)
        return f"已封存行程。\nfrom: {path}\nto: {archived_path}"

    if command == "brain:schedule_update_confirm":
        flow = store.get_ui_flow(chat_id)
        if not isinstance(flow, dict) or flow.get("kind") != FLOW_AWAIT_BRAIN_SCHEDULE_UPDATE_CONFIRM:
            return "目前沒有待確認修改的行程。請重新開始。"
        path = str(flow.get("path") or "").strip()
        if not path:
            store.clear_ui_flow(chat_id)
            store.clear_last_schedule_candidate(chat_id)
            return "行程路徑遺失，請重新開始。"
        update_schedule_note(
            settings,
            path,
            date_text=(flow.get("date_text") if "date_text" in flow else None),
            time_text=(flow.get("time_text") if "time_text" in flow else None),
            recurrence_type=(flow.get("recurrence_type") if "recurrence_type" in flow else None),
            recurrence_value=(flow.get("recurrence_value") if "recurrence_value" in flow else None),
        )
        body = read_note(settings, path).strip()
        store.clear_ui_flow(chat_id)
        store.clear_last_schedule_candidate(chat_id)
        return f"已更新 Schedule 筆記：{path}\n\n{body}"

    if command == "brain:summary":
        path = ensure_weekly_summary_note(settings)
        body = read_note(settings, path).strip()
        return f"已準備每週摘要筆記：{path}\n\n{body}"

    if command == "brain:decide":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_DECIDE})
        return "請輸入你要整理的判斷問題。輸入 /menu 可離開流程。"

    if command == "brain:remind":
        reminders = collect_brain_reminders(settings, limit=5)
        return "提醒：\n" + "\n".join(reminders)

    if command == "brain:daily":
        return build_daily_brief(settings)

    if command == "brain:weekly":
        return build_weekly_brief(settings, limit=10)

    if command.startswith("brain:open_note:"):
        raw_index = command.rsplit(":", 1)[1].strip()
        flow = store.get_ui_flow(chat_id)
        if not isinstance(flow, dict) or flow.get("kind") != FLOW_BRAIN_SEARCH_RESULTS:
            return "目前沒有可開啟的搜尋結果。請先搜尋。"
        results = flow.get("results")
        if not isinstance(results, list):
            return "搜尋結果已失效。請重新搜尋。"
        try:
            index = int(raw_index)
        except ValueError:
            return "無效的搜尋結果索引。"
        if index < 0 or index >= len(results):
            return "搜尋結果索引超出範圍。"
        path = str(results[index]).strip()
        body = read_note(settings, path).strip()
        return f"{path}\n\n{body}" if body else f"{path}\n\n這篇筆記目前是空的。"

    if command.startswith("brain:batch_open:"):
        raw_index = command.rsplit(":", 1)[1].strip()
        flow = store.get_ui_flow(chat_id)
        if not isinstance(flow, dict) or flow.get("kind") != FLOW_BRAIN_BATCH_RESULTS:
            return "目前沒有可用的批次整理結果。請先重新開啟批次整理。"
        results = flow.get("results")
        if not isinstance(results, list):
            return "批次整理結果已失效。請重新開始。"
        try:
            index = int(raw_index)
        except ValueError:
            return "無效的批次整理索引。"
        if index < 0 or index >= len(results):
            return "批次整理索引超出範圍。"
        path = str(results[index]).strip()
        source_text = read_note(settings, path).strip()
        store.set_ui_flow(
            chat_id,
            {
                "kind": FLOW_AWAIT_BRAIN_ORGANIZE_TARGET,
                "source_text": source_text,
                "source_path": path,
            },
        )
        return ButtonResponse(
            f"已載入：{path}\n要整理成哪一類？",
            buttons=[
                Button("專案", "brain:organize_target:project"),
                Button("知識卡", "brain:organize_target:knowledge"),
                Button("Resource", "brain:organize_target:resource"),
            ],
        )

    if command.startswith("brain:organize_target:"):
        target = command.rsplit(":", 1)[1].strip()
        flow = store.get_ui_flow(chat_id)
        if not isinstance(flow, dict) or flow.get("kind") != FLOW_AWAIT_BRAIN_ORGANIZE_TARGET:
            return "目前沒有待整理內容。請先重新開始整理流程。"
        source_text = str(flow.get("source_text") or "").strip()
        if not source_text:
            return "原始內容已遺失。請重新開始整理流程。"
        if target not in {"project", "knowledge", "resource"}:
            return "無效的整理目標。"
        store.set_ui_flow(
            chat_id,
            {
                "kind": FLOW_AWAIT_BRAIN_ORGANIZE_TITLE,
                "source_text": source_text,
                "target": target,
            },
        )
        labels = {
            "project": "專案",
            "knowledge": "知識卡",
            "resource": "資源",
        }
        return f"請輸入整理後的{labels[target]}標題。輸入 /menu 可離開流程。"

    return f"Unknown brain action: {command}"


def _main_menu_response(chat_id: int, store: ChatStateStore) -> ButtonResponse:
    return ButtonResponse(
        _menu_text(chat_id, store),
        buttons=[
            Button("狀態", "menu:status"),
            Button("Provider", "menu:provider"),
            Button("Model", "menu:model"),
            Button("Projects", "menu:projects"),
            Button("取消", "menu:cancel"),
        ],
    )


def _provider_menu_response(chat_id: int, store: ChatStateStore) -> str:
    state = store.get_chat_state(chat_id)
    store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_PROVIDER})
    provider_names = list(PROVIDER_LABELS.keys())
    lines = [f"Current provider: {state['provider']}", "", "可輸入的 provider:"]
    lines.extend(f"{index}. {name}" for index, name in enumerate(provider_names, start=1))
    lines.extend(
        [
            "",
            "可直接輸入編號或 provider 名稱，也可用 /provider <name>。",
            "輸入 /menu 返回主選單。",
            "其他自然語言會直接送進 AI。",
        ]
    )
    return "\n".join(lines)


def _model_menu_response(chat_id: int, store: ChatStateStore, settings: Settings) -> ButtonResponse:
    state = store.get_chat_state(chat_id)
    provider = str(state["provider"])
    models = SUPPORTED_MODELS.get(provider, [])
    choices = MODEL_CHOICES.get(provider, [(item, item) for item in models])
    default_model = models[0] if models else ""
    descriptions = MODEL_DESCRIPTIONS.get(provider, {})
    custom_models = settings.custom_models
    store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_MODEL})
    lines = [
        "Select Model",
        UI_BUILD_TAG,
        f"provider: {provider}",
        "",
        "按按鈕直接切換。",
        "",
    ]
    buttons: list[Button] = []
    # Build menu items: built-in choices + custom models
    menu_items: list[tuple[str, str]] = list(choices)
    if custom_models:
        menu_items.append(("---", "---"))  # separator
        for cm in custom_models:
            menu_items.append((cm, cm))
    for index, (item, label) in enumerate(menu_items, start=1):
        if item == "---":
            lines.append("--- custom models ---")
            continue
        tags: list[str] = []
        if item == default_model:
            tags.append("default")
        if item == state["model"]:
            tags.append("current")
        marker = f" ({', '.join(tags)})" if tags else ""
        description = descriptions.get(item)
        if description:
            lines.append(f"{index}. {item}{marker}  {description}")
        else:
            lines.append(f"{index}. {item}{marker}")
        buttons.append(Button(label, f"menu:set_model:{item}"))
    lines.extend(
        [
            "",
            "也可直接用 /model <name>",
            "輸入 /menu 返回主選單。",
        ]
    )
    return ButtonResponse("\n".join(lines), buttons=buttons)


def _resolve_model_selection(provider: str, text: str) -> str | None:
    normalized = text.strip()
    if not normalized:
        return None
    if normalized.lower().startswith("model "):
        normalized = normalized[6:].strip()
    models = SUPPORTED_MODELS.get(provider, [])
    if normalized.isdigit():
        index = int(normalized)
        if 1 <= index <= len(models[:8]):
            return models[index - 1]
        return None
    lowered = normalized.lower()
    lookup = {item.lower(): item for item in models}
    if lowered in lookup:
        return lookup[lowered]
    # Allow any text to pass through as model name (for custom/Chinese models like deepseek-chat, qwen-turbo, etc.)
    if normalized:
        return normalized
    return None


def _resolve_provider_selection(text: str) -> str | None:
    normalized = text.strip().lower()
    provider_names = list(PROVIDER_LABELS.keys())
    if not normalized:
        return None
    if normalized.startswith("provider "):
        normalized = normalized[9:].strip()
    if normalized.isdigit():
        index = int(normalized)
        if 1 <= index <= len(provider_names):
            return provider_names[index - 1]
        return None
    if normalized in provider_names:
        return normalized
    return None


def _projects_menu_response(chat_id: int, settings: Settings, store: ChatStateStore) -> ButtonResponse | str:
    state = store.get_chat_state(chat_id)
    workspaces = discover_project_workspaces(settings)
    if not workspaces:
        store.clear_ui_flow(chat_id)
        return "No projects discovered."

    store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_PROJECT})
    lines = [
        f"Current project: {_project_display(state['project_name'], state['project_path'])}",
        f"Available projects: {len(workspaces)}",
    ]
    buttons: list[Button] = []
    for workspace in workspaces:
        buttons.append(Button(f"{workspace.label} | {workspace.key}", workspace.key))
    lines.extend(
        [
            "",
            "可直接點藍色 project key 按鈕切換。",
            "可直接輸入編號、project key 或 label，或用 /project <key-or-label>。",
            "輸入 /menu 返回主選單。",
            "其他自然語言會直接送進 AI。",
        ]
    )
    return ButtonResponse("\n".join(lines), buttons=buttons)


def _projects_list_response(chat_id: int, settings: Settings, store: ChatStateStore) -> str:
    state = store.get_chat_state(chat_id)
    workspaces = discover_project_workspaces(settings)
    if not workspaces:
        return "No projects discovered."

    current_key = str(state.get("project_key") or "")
    current_path = str(state.get("project_path") or "")
    lines = [
        f"Current project: {_project_display(state['project_name'], state['project_path'])}",
        f"Available projects: {len(workspaces)}",
    ]
    for index, workspace in enumerate(workspaces, start=1):
        marker = ""
        if workspace.key == current_key or str(workspace.path) == current_path:
            marker = "  *current"
        lines.append(f"{index}. {workspace.label} | {workspace.key}{marker}")
    lines.extend(
        [
            "",
            "Use /project <key-or-label> or /projects <key-or-label> to switch.",
            "Use /project (or /projects) to open chooser buttons.",
        ]
    )
    return "\n".join(lines)


def _resolve_project_selection(settings: Settings, text: str):
    normalized = text.strip()
    if not normalized:
        return None
    lowered = normalized.lower()
    if lowered.startswith("project "):
        normalized = normalized[8:].strip()
        lowered = normalized.lower()
    workspaces = discover_project_workspaces(settings)
    if normalized.isdigit():
        index = int(normalized)
        if 1 <= index <= len(workspaces):
            return workspaces[index - 1]
        return None
    return find_workspace(settings, normalized)


def _handle_project_selection(chat_id: int, payload: str, settings: Settings, store: ChatStateStore) -> ButtonResponse | str:
    normalized = payload.strip()
    if not normalized:
        return _projects_menu_response(chat_id, settings, store)
    if normalized.lower() in {"list", "ls"}:
        store.clear_ui_flow(chat_id)
        return _projects_list_response(chat_id, settings, store)

    workspace = _resolve_project_selection(settings, normalized)
    if workspace is None:
        return (
            f"Project not found: {normalized}\n"
            "Use /project (or /projects) to open chooser, or /projects list for indexed list."
        )

    next_state = store.set_project(chat_id, workspace.key, workspace.label, str(workspace.path))
    store.clear_ui_flow(chat_id)
    return (
        f"Project updated.\nproject: {_project_display(next_state['project_name'], next_state['project_path'])}\npath: {next_state['project_path']}"
    )


def _render_project_registry_list(chat_id: int, settings: Settings, store: ChatStateStore) -> str:
    state = store.get_chat_state(chat_id)
    items, active_name = list_registered_projects(settings)
    if not items:
        return (
            "No registered projects.\n"
            "Use: /project register [name] <path>"
        )
    lines = [
        f"Current context: {_project_display(state['project_name'], state['project_path'])}",
        f"Registered projects: {len(items)}",
    ]
    for index, item in enumerate(items, start=1):
        name = str(item.get("name") or "-")
        key = str(item.get("key") or "-")
        path = str(item.get("path") or "-")
        status = project_status(item)
        recent = str(item.get("last_activity_at") or item.get("last_used_at") or item.get("updated_at") or "-")
        marker = "  *active" if name == active_name else ""
        lines.append(f"{index}. {name} | {key} | {status} | recent={recent}{marker}")
        lines.append(f"   {path}")
    return "\n".join(lines)


def _resolve_project_register_args(parts: list[str]) -> tuple[str, str] | None:
    if len(parts) < 2:
        return None
    if len(parts) == 2:
        candidate = Path(parts[1]).expanduser()
        name = candidate.name.strip() or "project"
        return name, parts[1]
    return parts[1], parts[2]


def _handle_project_command(chat_id: int, payload: str, settings: Settings, store: ChatStateStore) -> ButtonResponse | str:
    parts = _split_payload_windows(payload)
    if not parts:
        return _projects_menu_response(chat_id, settings, store)

    action = str(parts[0]).strip().lower()
    if action in {"list", "ls"}:
        store.clear_ui_flow(chat_id)
        return _render_project_registry_list(chat_id, settings, store)

    if action in {"register", "add"}:
        resolved = _resolve_project_register_args(parts)
        if resolved is None:
            return "Usage: /project register [name] <path>"
        name, path = resolved
        try:
            project = register_project(settings, name, path)
        except ValueError as exc:
            return f"Project register failed: {exc}"
        return (
            "Project registered.\n"
            f"name: {project.get('name')}\n"
            f"key: {project.get('key')}\n"
            f"path: {project.get('path')}"
        )

    if action in {"use", "select"}:
        if len(parts) != 2:
            return "Usage: /project use <name|key>"
        project = use_project(settings, parts[1])
        if project is None:
            return f"Project not found: {parts[1]}"
        next_state = store.set_project(
            chat_id,
            str(project.get("key") or ""),
            str(project.get("name") or ""),
            str(project.get("path") or ""),
        )
        return (
            "Project updated.\n"
            f"project: {_project_display(next_state['project_name'], next_state['project_path'])}\n"
            f"path: {next_state['project_path']}"
        )

    if action == "info":
        if len(parts) != 2:
            return "Usage: /project info <name|key>"
        project = get_project(settings, parts[1])
        if project is None:
            return f"Project not found: {parts[1]}"
        info = project_info(project)
        return "\n".join(
            [
                "project info",
                f"name: {info.get('name')}",
                f"key: {info.get('key')}",
                f"path: {info.get('path')}",
                f"status: {info.get('status')}",
                f"git_available: {info.get('git_available')}",
                f"is_git_repo: {info.get('is_git_repo')}",
                f"branch: {info.get('branch')}",
                f"dirty: {info.get('dirty')}",
                f"remote_origin: {info.get('remote_origin')}",
            ]
        )

    if action == "note":
        if len(parts) < 3:
            return "Usage: /project note <name|key> <text>"
        ref = parts[1]
        text = " ".join(parts[2:]).strip()
        try:
            result = add_project_note(settings, ref, text)
        except ValueError as exc:
            return f"Project note failed: {exc}"
        if result is None:
            return f"Project not found: {ref}"
        project, notes_path = result
        return (
            "Project note saved.\n"
            f"name: {project.get('name')}\n"
            f"path: {notes_path}"
        )

    if action == "doctor":
        target = parts[1] if len(parts) >= 2 else "all"
        if target.lower() == "all":
            items, _active = list_registered_projects(settings)
            if not items:
                return "No registered projects."
            lines: list[str] = []
            has_issue = False
            for index, item in enumerate(items):
                if index:
                    lines.append("")
                report = project_doctor(item)
                issues = report.get("issues") if isinstance(report.get("issues"), list) else []
                checks = report.get("checks") if isinstance(report.get("checks"), list) else []
                status = "ISSUE" if issues else "OK"
                lines.append(f"{item.get('name')}: {status}")
                for check in checks:
                    lines.append(f"  - {check}")
                for issue in issues:
                    lines.append(f"  - issue: {issue}")
                has_issue = has_issue or bool(issues)
            if has_issue:
                lines.append("")
                lines.append("doctor summary: issues found")
            return "\n".join(lines)

        project = get_project(settings, target)
        if project is None:
            return f"Project not found: {target}"
        report = project_doctor(project)
        issues = report.get("issues") if isinstance(report.get("issues"), list) else []
        checks = report.get("checks") if isinstance(report.get("checks"), list) else []
        status = "ISSUE" if issues else "OK"
        lines = [f"{project.get('name')}: {status}"]
        for check in checks:
            lines.append(f"  - {check}")
        for issue in issues:
            lines.append(f"  - issue: {issue}")
        return "\n".join(lines)

    if action == "current":
        project = active_project(settings)
        if project is None:
            return "No active project in registry."
        return (
            "active project\n"
            f"name: {project.get('name')}\n"
            f"key: {project.get('key')}\n"
            f"path: {project.get('path')}"
        )

    return _handle_project_selection(chat_id, payload, settings, store)


async def _handle_menu_action(
    chat_id: int,
    command: str,
    settings: Settings,
    store: ChatStateStore,
    agents: AgentCoordinator,
):
    if command in {"menu", "menu:open"}:
        return _main_menu_response(chat_id, store)

    if command == "menu:cancel":
        store.clear_ui_flow(chat_id)
        return "Menu canceled."

    if command == "menu:status":
        store.clear_ui_flow(chat_id)
        return _status_text(chat_id, store, settings)

    if command == "menu:provider":
        store.clear_ui_flow(chat_id)
        return _provider_menu_response(chat_id, store)

    if command.startswith("menu:set_provider:"):
        provider = command.split(":", 2)[2].strip().lower()
        if provider not in PROVIDER_LABELS:
            return f"Unknown provider: {provider}\nAvailable: {', '.join(PROVIDER_LABELS)}"
        next_state = store.set_provider(chat_id, provider)
        store.clear_ui_flow(chat_id)
        return (
            f"Provider updated.\nprovider: {next_state['provider']}\nmodel: {next_state['model']}\n\n"
            "輸入 /menu 可回到主選單，或直接輸入自然語言交給 AI。"
        )

    if command == "menu:model":
        return _model_menu_response(chat_id, store, settings)

    if command.startswith("menu:set_model:"):
        model = command.split(":", 2)[2].strip()
        if not model:
            return "Empty model name."
        if model == "custom":
            store.clear_ui_flow(chat_id)
            return (
                "Custom model selected.\n"
                "請使用 /model <實際模型名稱> 來設定自訂模型。\n"
                "例如: /model deepseek-chat, /model qwen-turbo, /model gpt-4o\n\n"
                "輸入 /menu 可回到主選單。"
            )
        next_state = store.set_model(chat_id, model)
        store.clear_ui_flow(chat_id)
        return (
            f"Model updated.\nprovider: {next_state['provider']}\nmodel: {next_state['model']}\n\n"
            "輸入 /menu 可回到主選單，或直接輸入自然語言交給 AI。"
        )

    if command.startswith("menu:set_project:"):
        project_ref = command.removeprefix("menu:set_project:").strip()
        if not project_ref:
            return "Empty project selection."
        workspace = _resolve_project_selection(settings, project_ref)
        if workspace is None:
            return (
                f"Project not found: {project_ref}\n"
                "Use /project (or /projects) to open chooser, or /projects list for indexed list."
            )
        next_state = store.set_project(chat_id, workspace.key, workspace.label, str(workspace.path))
        store.clear_ui_flow(chat_id)
        return (
            f"Project updated.\nproject: {_project_display(next_state['project_name'], next_state['project_path'])}\npath: {next_state['project_path']}\n\n"
            "輸入 /menu 可回到主選單，或直接輸入自然語言交給 AI。"
        )

    if command == "menu:projects":
        return _projects_menu_response(chat_id, settings, store)

    return f"Unknown menu action: {command}"


async def _handle_flow_input(
    chat_id: int,
    ctx: MessageContext,
    settings: Settings,
    store: ChatStateStore,
    agents: AgentCoordinator,
):
    flow = store.get_ui_flow(chat_id)
    if not isinstance(flow, dict):
        return None

    kind = str(flow.get("kind") or "").strip()
    text = (ctx.text or "").strip()
    if not text:
        return None

    # Let explicit slash commands continue through normal command routing.
    if text.startswith("/"):
        return None

    if kind == FLOW_AWAIT_MODEL:
        return "請直接按 model 按鈕切換，或用 /model <name>。輸入 /menu 返回主選單。"

    if kind == FLOW_AWAIT_PROVIDER:
        selected_provider = _resolve_provider_selection(text)
        if selected_provider is not None:
            return await _handle_menu_action(chat_id, f"menu:set_provider:{selected_provider}", settings, store, agents)
        return None

    if kind == FLOW_AWAIT_PROJECT:
        normalized = text.strip()
        workspace = _resolve_project_selection(settings, normalized)
        if workspace is not None:
            next_state = store.set_project(chat_id, workspace.key, workspace.label, str(workspace.path))
            store.clear_ui_flow(chat_id)
            return (
                f"Project updated.\nproject: {_project_display(next_state['project_name'], next_state['project_path'])}\npath: {next_state['project_path']}\n\n"
                "輸入 /menu 可回到主選單，或直接輸入自然語言交給 AI。"
            )
        return None

    if kind == FLOW_AWAIT_BRAIN_CAPTURE:
        path = append_to_daily(settings, text)
        store.clear_ui_flow(chat_id)
        return f"已寫入今日筆記。\npath: {path}"

    if kind == FLOW_AWAIT_BRAIN_INBOX:
        path = create_inbox_note(settings, text)
        store.clear_ui_flow(chat_id)
        return f"已建立 Inbox 筆記。\npath: {path}"

    if kind == FLOW_AWAIT_BRAIN_SEARCH:
        matches = search_vault(settings, text, limit=10)
        if not matches:
            store.clear_ui_flow(chat_id)
            return f"找不到與「{text}」相關的筆記。"
        store.set_ui_flow(chat_id, {"kind": FLOW_BRAIN_SEARCH_RESULTS, "results": matches[:10]})
        return ButtonResponse(
            f"搜尋結果：{text}",
            buttons=[Button(item, f"brain:open_note:{idx}") for idx, item in enumerate(matches[:10])],
        )

    if kind == FLOW_AWAIT_BRAIN_ORGANIZE_TEXT:
        store.set_ui_flow(
            chat_id,
            {
                "kind": FLOW_AWAIT_BRAIN_ORGANIZE_TARGET,
                "source_text": text,
            },
        )
        return ButtonResponse(
            "要把這段內容整理成哪一類？",
            buttons=[
                Button("專案", "brain:organize_target:project"),
                Button("知識卡", "brain:organize_target:knowledge"),
                Button("Resource", "brain:organize_target:resource"),
            ],
        )

    if kind == FLOW_AWAIT_BRAIN_PROJECT:
        path = create_project_note(settings, text)
        body = read_note(settings, path).strip()
        store.clear_ui_flow(chat_id)
        return f"已建立 Project 筆記：{path}\n\n{body}"

    if kind == FLOW_AWAIT_BRAIN_KNOWLEDGE:
        path = create_knowledge_note(settings, text)
        body = read_note(settings, path).strip()
        store.clear_ui_flow(chat_id)
        return f"已建立 Knowledge 筆記：{path}\n\n{body}"

    if kind == FLOW_AWAIT_BRAIN_RESOURCE:
        path = create_resource_note(settings, text)
        body = read_note(settings, path).strip()
        store.clear_ui_flow(chat_id)
        return f"已建立 Resource 筆記：{path}\n\n{body}"

    if kind == FLOW_AWAIT_BRAIN_SCHEDULE_TITLE:
        parsed = parse_natural_language_schedule(text)
        if parsed is not None:
            _set_schedule_confirm_flow(chat_id, store, parsed)
            return _schedule_confirm_response(parsed)
        store.set_ui_flow(
            chat_id,
            {
                "kind": FLOW_AWAIT_BRAIN_SCHEDULE_DATE,
                "title": text,
            },
        )
        return f"行程標題已記下：{text}\n請輸入日期，例如 2026-04-11。若暫時不填可輸入 skip。"

    if kind == FLOW_AWAIT_BRAIN_SCHEDULE_DATE:
        title = str(flow.get("title") or "").strip()
        if not title:
            store.clear_ui_flow(chat_id)
            return "行程流程資料遺失，請重新開始。"
        date_text = "" if text.lower() in {"skip", "略過", "none", "-"} else text
        store.set_ui_flow(
            chat_id,
            {
                "kind": FLOW_AWAIT_BRAIN_SCHEDULE_TIME,
                "title": title,
                "date_text": date_text,
            },
        )
        return "請輸入時間，例如 14:30。若暫時不填可輸入 skip。"

    if kind == FLOW_AWAIT_BRAIN_SCHEDULE_TIME:
        title = str(flow.get("title") or "").strip()
        if not title:
            store.clear_ui_flow(chat_id)
            return "行程流程資料遺失，請重新開始。"
        date_text = str(flow.get("date_text") or "").strip()
        time_text = "" if text.lower() in {"skip", "略過", "none", "-"} else text
        path = create_schedule_note(settings, title, date_text=date_text, time_text=time_text)
        body = read_note(settings, path).strip()
        store.clear_ui_flow(chat_id)
        return f"已建立 Schedule 筆記：{path}\n\n{body}"

    if kind == FLOW_AWAIT_BRAIN_ORGANIZE_TITLE:
        flow = store.get_ui_flow(chat_id)
        if not isinstance(flow, dict):
            return "整理流程已失效，請重新開始。"
        source_text = str(flow.get("source_text") or "").strip()
        target = str(flow.get("target") or "").strip()
        if not source_text or target not in {"project", "knowledge", "resource"}:
            return "整理流程資料不完整，請重新開始。"
        if target == "project":
            path = create_project_note_from_text(settings, text, source_text)
            label = "Project"
        elif target == "knowledge":
            path = create_knowledge_note_from_text(settings, text, source_text)
            label = "Knowledge"
        else:
            path = create_resource_note_from_text(settings, text, source_text)
            label = "Resource"
        body = read_note(settings, path).strip()
        store.clear_ui_flow(chat_id)
        return f"已整理成 {label} 筆記：{path}\n\n{body}"

    if kind == FLOW_AWAIT_BRAIN_DECIDE:
        related_paths, brief = build_decision_support_brief(settings, text, limit=5)
        path = create_decision_note_from_brief(settings, text, brief, related_notes=related_paths)
        store.clear_ui_flow(chat_id)
        return f"{brief}\n\n已建立決策支援筆記：{path}"

    return None


async def handle_request(ctx: MessageContext, settings: Settings, store: ChatStateStore, agents: AgentCoordinator) -> str:
    text = (ctx.text or "").strip()
    command = (ctx.command or "").strip().lower()
    if command.startswith("/"):
        command = command[1:]
    if "@" in command:
        command = command.split("@", 1)[0].strip()

    if ctx.document is not None and not command:
        from robot.security import sanitize_file_size, SecurityError

        local_path = str(ctx.document.local_path or "").strip()
        if not local_path:
            return "文件已收到，但目前沒有可讀取的本機路徑。請重新上傳後再試。"

        # Add file size check
        try:
            sanitize_file_size(Path(local_path), max_size_mb=50)
        except SecurityError as exc:
            return f"文件大小驗證失敗: {exc}"

        title = (ctx.caption or "").strip()
        source_name = str(ctx.document.file_name or Path(local_path).name)
        if not title:
            file_name = str(ctx.document.file_name or "").strip()
            title = Path(file_name).stem if file_name else Path(local_path).stem
        try:
            note_path, extracted = import_markitdown_resource(settings, Path(local_path), title=title)
        except (FileConversionException, MarkItDownException) as exc:
            return _document_import_error_message(source_name, exc)
        preview = extracted.strip().replace("\r\n", "\n")
        if len(preview) > 500:
            preview = preview[:500].rstrip() + "..."
        return (
            "已匯入文件到 secondbrain。\n"
            f"path: {note_path}\n"
            f"source_file: {source_name}\n\n"
            f"{preview or '(No extracted text)'}"
        )

    if command == "menu":
        store.clear_ui_flow(ctx.chat_id)
        return _main_menu_response(ctx.chat_id, store)
    if command == "model":
        return _model_menu_response(ctx.chat_id, store, settings)
    if command == "brain":
        store.clear_ui_flow(ctx.chat_id)
        return _brain_menu_response(ctx.chat_id, store)

    # Non-blocking rule: plain text should always reach the agent for content flows.
    # Keep numeric/text selection for settings flows (model/provider/project).
    active_flow = store.get_ui_flow(ctx.chat_id)
    if text and not command and isinstance(active_flow, dict):
        flow_kind = str(active_flow.get("kind") or "").strip()
        allowed_flow_kinds = {FLOW_AWAIT_MODEL, FLOW_AWAIT_PROVIDER, FLOW_AWAIT_PROJECT}
        if flow_kind not in allowed_flow_kinds:
            store.clear_ui_flow(ctx.chat_id)

    flow_response = await _handle_flow_input(ctx.chat_id, ctx, settings, store, agents)
    if flow_response is not None:
        return flow_response

    request = classify_request(ctx)
    if request.kind == COMMAND_REQUEST:
        return await handle_command(ctx.chat_id, request, settings, store, agents)
    if request.kind == CONTROL_REQUEST:
        return await handle_control(ctx.chat_id, request, store, agents)
    return await handle_agent(ctx.chat_id, request, store, agents)


async def handle_command(chat_id: int, request: ClassifiedRequest, settings: Settings, store: ChatStateStore, agents: AgentCoordinator) -> str:
    if request.command == "menu" or (request.command and request.command.startswith(MENU_COMMAND_PREFIX)):
        return await _handle_menu_action(chat_id, request.command, settings, store, agents)
    if request.command == "brain" or (request.command and request.command.startswith(BRAIN_COMMAND_PREFIX)):
        return await _handle_brain_action(chat_id, request.command, settings, store, agents)

    state = store.get_chat_state(chat_id)

    # Support inline project key callbacks (data is just "proj-xxxxxxxxxxxx").
    if request.command and request.command.startswith("proj-"):
        workspace = _resolve_project_selection(settings, request.command)
        if workspace is not None:
            next_state = store.set_project(chat_id, workspace.key, workspace.label, str(workspace.path))
            store.clear_ui_flow(chat_id)
            return (
                f"Project updated.\nproject: {_project_display(next_state['project_name'], next_state['project_path'])}\npath: {next_state['project_path']}\n\n"
                "輸入 /menu 可回到主選單，或直接輸入自然語言交給 AI。"
            )

    if request.command in {"start", "help"}:
        return _help_text()
    if request.command == "quick":
        return _quick_text()
    if request.command == "guide":
        return _guide_text()

    if request.command == "about":
        return "robot\nteleapp-based Telegram task router\nOnly agent requests are sent to providers."

    if request.command == "status":
        return _status_text(chat_id, store, settings)

    if request.command == "doctor":
        return build_doctor_report(settings)

    if request.command in {"contact", "contacts"}:
        parts = _split_payload(request.payload)
        usage = "\n".join(
            [
                "contact usage:",
                "- /contact list",
                "- /contact show <key>",
                "- /contact add <key> <email> <name>",
                "- /contact remove <key>",
                "- /contact alias <key> add <alias>",
                "- /contact resolve <target1> [target2] ...",
            ]
        )
        if not parts:
            return usage
        action = str(parts[0]).strip().lower()

        if action == "list":
            contacts = store.list_contacts()
            lines = [f"address book contacts: {len(contacts)}"]
            if not contacts:
                lines.append("- (empty)")
                return "\n".join(lines)
            for item in contacts:
                aliases = item.get("aliases") if isinstance(item.get("aliases"), list) else []
                alias_text = ", ".join(str(alias) for alias in aliases) if aliases else "-"
                lines.append(
                    f"- {item.get('key')} | {item.get('name')} | {item.get('email')} | aliases: {alias_text}"
                )
            return "\n".join(lines)

        if action == "show":
            if len(parts) != 2:
                return "Usage: /contact show <key>"
            contact = store.get_contact(parts[1])
            if contact is None:
                return f"Contact not found: {parts[1]}"
            aliases = contact.get("aliases") if isinstance(contact.get("aliases"), list) else []
            return "\n".join(
                [
                    "contact",
                    f"key: {contact.get('key')}",
                    f"name: {contact.get('name')}",
                    f"email: {contact.get('email')}",
                    f"aliases: {', '.join(str(alias) for alias in aliases) if aliases else '-'}",
                    f"note: {contact.get('note') or '-'}",
                ]
            )

        if action == "add":
            if len(parts) < 4:
                return "Usage: /contact add <key> <email> <name>"
            key = str(parts[1]).strip()
            email = str(parts[2]).strip()
            name = " ".join(str(item) for item in parts[3:]).strip()
            if not name:
                return "Usage: /contact add <key> <email> <name>"
            try:
                contact = store.upsert_contact(key=key, email=email, name=name)
            except ValueError as exc:
                return f"Contact add failed: {exc}"
            return "\n".join(
                [
                    "Contact saved.",
                    f"key: {contact.get('key')}",
                    f"name: {contact.get('name')}",
                    f"email: {contact.get('email')}",
                ]
            )

        if action in {"remove", "rm", "del", "delete"}:
            if len(parts) != 2:
                return "Usage: /contact remove <key>"
            removed = store.remove_contact(parts[1])
            if not removed:
                return f"Contact not found: {parts[1]}"
            return f"Contact removed: {parts[1]}"

        if action == "alias":
            if len(parts) < 4:
                return "Usage: /contact alias <key> add <alias>"
            key = str(parts[1]).strip()
            subaction = str(parts[2]).strip().lower()
            alias = " ".join(str(item) for item in parts[3:]).strip()
            if subaction != "add" or not alias:
                return "Usage: /contact alias <key> add <alias>"
            try:
                contact = store.add_contact_alias(key, alias)
            except ValueError as exc:
                return f"Contact alias failed: {exc}"
            aliases = contact.get("aliases") if isinstance(contact.get("aliases"), list) else []
            return "\n".join(
                [
                    "Contact alias updated.",
                    f"key: {contact.get('key')}",
                    f"aliases: {', '.join(str(item) for item in aliases) if aliases else '-'}",
                ]
            )

        if action == "resolve":
            targets = [str(item).strip() for item in parts[1:] if str(item).strip()]
            if not targets:
                return "Usage: /contact resolve <target1> [target2] ..."
            result = store.resolve_contacts(targets)
            emails = result.get("emails") if isinstance(result.get("emails"), list) else []
            unresolved = result.get("unresolved") if isinstance(result.get("unresolved"), list) else []
            ambiguous = result.get("ambiguous") if isinstance(result.get("ambiguous"), dict) else {}
            lines = [
                "contact resolve",
                f"targets: {len(targets)}",
                f"emails: {', '.join(str(item) for item in emails) if emails else '-'}",
            ]
            if unresolved:
                lines.append(f"unresolved: {', '.join(str(item) for item in unresolved)}")
            if ambiguous:
                lines.append("ambiguous:")
                for token, keys in sorted(ambiguous.items()):
                    if isinstance(keys, list):
                        lines.append(f"- {token}: {', '.join(str(key) for key in keys)}")
            return "\n".join(lines)

        return usage

    if request.command == "mailcli":
        parts = _split_payload_windows(request.payload)
        if not parts:
            return "Usage: /mailcli <sendmail-cli-args>"
        rewritten, error = _rewrite_mailcli_targets(store, parts)
        if rewritten is None:
            return f"mailcli recipient resolve failed.\n{error}"
        ok, report = _run_sendmail(settings, args=rewritten)
        return ("mailcli sent.\n" if ok else "mailcli failed.\n") + report

    if request.command == "mailjson":
        parts = _split_payload_windows(request.payload)
        if len(parts) != 1:
            return "Usage: /mailjson <config.json>"
        config_path = _resolve_input_path(
            parts[0],
            project_path=str(state.get("project_path") or ""),
            settings=settings,
        )
        if not config_path.exists():
            return f"mailjson file not found: {config_path}"
        try:
            parsed = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return f"mailjson parse failed: {exc}"
        if not isinstance(parsed, dict):
            return "mailjson config must be a JSON object."
        rewritten_json, error = _rewrite_json_recipients_with_contacts(store, parsed)
        if rewritten_json is None:
            return f"mailjson recipient resolve failed.\n{error}"
        resolved_path = settings.state_home / f"mailjson_resolved_chat{chat_id}.json"
        try:
            resolved_path.write_text(
                json.dumps(rewritten_json, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            return f"mailjson write failed: {exc}"
        ok, report = _run_sendmail(settings, args=[str(resolved_path)])
        return ("mailjson sent.\n" if ok else "mailjson failed.\n") + report

    if request.command == "mailbatch":
        parts = _split_payload_windows(request.payload)
        if len(parts) != 2:
            return "Usage: /mailbatch <recipients.csv> <base_config.json>"
        csv_path = _resolve_input_path(
            parts[0],
            project_path=str(state.get("project_path") or ""),
            settings=settings,
        )
        json_path = _resolve_input_path(
            parts[1],
            project_path=str(state.get("project_path") or ""),
            settings=settings,
        )
        if not csv_path.exists():
            return f"mailbatch csv not found: {csv_path}"
        if not json_path.exists():
            return f"mailbatch base json not found: {json_path}"
        ok, report = _run_sendmail(
            settings,
            args=["batch", str(csv_path), str(json_path)],
        )
        return ("mailbatch sent.\n" if ok else "mailbatch failed.\n") + report

    if request.command == "mailmcp":
        sendmail_root = _sendmail_root_path()
        sendmail_script = sendmail_root / "sendmail.py"
        mcp_server = sendmail_root / "sendmail_mcp" / "server.py"
        env_file = sendmail_root / ".env"
        env_values = dotenv_values(env_file) if env_file.exists() else {}
        gmail_user = str(env_values.get("GMAIL_USER") or "")
        gmail_password = str(env_values.get("GMAIL_APP_PASSWORD") or "")
        env_ready = bool(gmail_user and gmail_password)
        return "\n".join(
            [
                "mailmcp status",
                f"sendmail_root: {sendmail_root}",
                f"sendmail_root_exists: {sendmail_root.exists()}",
                f"sendmail_script_exists: {sendmail_script.exists()}",
                f"mcp_server_exists: {mcp_server.exists()}",
                f"env_file_exists: {env_file.exists()}",
                f"env_ready: {env_ready}",
            ]
        )

    if request.command == "provider":
        payload = request.payload.strip().lower()
        if not payload:
            return _provider_menu_response(chat_id, store)
        selected_provider = _resolve_provider_selection(payload)
        if selected_provider is None:
            return (
                f"Unknown provider selection: {payload}\n"
                "Use /provider to open the provider chooser."
            )
        next_state = store.set_provider(chat_id, selected_provider)
        return f"Provider updated.\nprovider: {next_state['provider']}\nmodel: {next_state['model']}"

    if request.command == "models":
        provider = str(state["provider"])
        lines = [f"Models for {provider}:"]
        lines.extend(f"- {item}" for item in SUPPORTED_MODELS.get(provider, []))
        if settings.custom_models:
            lines.append("--- custom models ---")
            lines.extend(f"- {item}" for item in settings.custom_models)
        return "\n".join(lines)

    if request.command == "model":
        payload = request.payload.strip()
        if not payload:
            return _model_menu_response(chat_id, store, settings)
        selected_model = _resolve_model_selection(str(state["provider"]), payload)
        if selected_model is None:
            return (
                f"Unknown model selection: {payload}\n"
                "Use /model to open the model chooser, or /models to list available models."
            )
        next_state = store.set_model(chat_id, selected_model)
        return f"Model updated.\nprovider: {next_state['provider']}\nmodel: {next_state['model']}"

    if request.command in {"project", "projects"}:
        return _handle_project_command(chat_id, request.payload, settings, store)

    if request.command == "queue":
        return agents.queue_overview(chat_id)

    if request.command == "schedules":
        return agents.schedule_overview(chat_id)

    if request.command == "agentstatus":
        current = state.get("agent_current_run") if isinstance(state.get("agent_current_run"), dict) else None
        if current:
            return "\n".join(
                [
                    "agent status",
                    f"state: running",
                    f"kind: {current.get('kind')}",
                    f"goal: {current.get('goal') or '<resume>'}",
                    f"run_id: {current.get('run_id') or '-'}",
                    f"project: {_project_display(current.get('project_name'), current.get('project_path'))}",
                    f"path: {current.get('project_path') or '-'}",
                    f"queue_pending: {len(store.get_agent_queue(chat_id))}",
                ]
            )
        queue = store.get_agent_queue(chat_id)
        if queue:
            next_job = queue[0]
            return "\n".join(
                [
                    "agent status",
                    "state: queued",
                    f"kind: {next_job.get('kind')}",
                    f"goal: {next_job.get('goal') or '<resume>'}",
                    f"run_id: {next_job.get('run_id') or '-'}",
                    f"project: {_project_display(next_job.get('project_name'), next_job.get('project_path'))}",
                    f"path: {next_job.get('project_path') or '-'}",
                    f"queue_pending: {len(queue)}",
                ]
            )
        last = state.get("agent_last_run") if isinstance(state.get("agent_last_run"), dict) else None
        if last:
            return "\n".join(
                [
                    "agent status",
                    "state: idle",
                    f"last_status: {last.get('status')}",
                    f"last_kind: {last.get('kind')}",
                    f"last_run_id: {last.get('run_id') or '-'}",
                    f"project: {_project_display(last.get('project_name'), last.get('project_path'))}",
                    f"path: {last.get('project_path') or '-'}",
                    f"elapsed_seconds: {last.get('elapsed_seconds')}",
                ]
            )
        return "agent status\nstate: idle\nno current or historical run."

    if request.command == "agentprofiles":
        payload = request.payload.strip()
        config_path = None
        if payload:
            parser = _SilentArgumentParser(add_help=False)
            parser.add_argument("--config")
            try:
                parsed = parser.parse_args(_split_payload(payload))
                config_path = parsed.config
            except (SystemExit, ValueError):
                return "Usage: /agentprofiles [--config PATH]"
        return await agents.auto_dev_profiles(chat_id, config_path=config_path)

    if request.command == "brainread":
        body = read_daily(settings).strip()
        return body if body else "今日 daily note 目前是空的。"

    if request.command == "braininbox":
        payload = request.payload.strip()
        if not payload:
            return "Usage: /braininbox <text>"
        path = create_inbox_note(settings, payload)
        return f"已建立 Inbox 筆記。\npath: {path}"

    if request.command == "brainweb":
        payload = request.payload.strip()
        if not payload:
            return "Usage: /brainweb <url>"
        try:
            path, title, excerpt, summary_points, tags = capture_web_to_daily(settings, payload, max_chars=2500)
        except ValueError as exc:
            return f"網址格式錯誤：{exc}"
        except OSError as exc:
            return f"抓取網頁失敗：{exc}"
        summary_lines = "\n".join(f"- {item}" for item in summary_points[:3]) if summary_points else "- (none)"
        tags_line = ", ".join(tags) if tags else "(none)"
        preview = excerpt[:300].rstrip()
        if len(excerpt) > 300:
            preview += "..."
        return (
            "已寫入今日筆記（網頁收錄）。\n"
            f"path: {path}\n"
            f"title: {title}\n"
            f"tags: {tags_line}\n\n"
            "摘要重點：\n"
            f"{summary_lines}\n\n"
            f"{preview}"
        )

    if request.command == "brainsearch":
        payload = request.payload.strip()
        if not payload:
            return "Usage: /brainsearch <query>"
        matches = search_vault(settings, payload, limit=10)
        if not matches:
            return f"找不到與「{payload}」相關的筆記。"
        store.set_ui_flow(chat_id, {"kind": FLOW_BRAIN_SEARCH_RESULTS, "results": matches[:10]})
        return ButtonResponse(
            f"搜尋結果：{payload}",
            buttons=[Button(item, f"brain:open_note:{idx}") for idx, item in enumerate(matches[:10])],
        )

    if request.command == "brainorganize":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_ORGANIZE_TEXT})
        return "請先貼上你要整理的原始內容。輸入 /menu 可離開流程。"

    if request.command == "brainbatch":
        return await _handle_brain_action(chat_id, "brain:batch", settings, store, agents)

    if request.command == "brainbatchauto":
        payload = request.payload.strip()
        if not payload:
            return await _handle_brain_action(chat_id, "brain:batch_auto", settings, store, agents)
        try:
            limit = int(payload)
        except ValueError:
            return "Usage: /brainbatchauto [limit]"
        bounded_limit = max(1, min(limit, 50))
        summary = auto_organize_recent_notes(settings, limit=bounded_limit)
        processed = int(summary.get("processed") or 0)
        if processed == 0:
            return "目前沒有可自動整理的 Inbox / Daily 筆記。"
        by_type = summary.get("by_type")
        items = summary.get("items")
        if not isinstance(by_type, dict):
            by_type = {}
        if not isinstance(items, list):
            items = []
        lines = [
            f"自動批次整理完成 (limit={bounded_limit})：",
            f"- processed: {processed}",
            f"- created: {int(summary.get('created') or 0)}",
            f"- skipped: {int(summary.get('skipped') or 0)}",
            f"- failed: {int(summary.get('failed') or 0)}",
            "",
            "分類統計：",
            f"- project: {int(by_type.get('project') or 0)}",
            f"- knowledge: {int(by_type.get('knowledge') or 0)}",
            f"- resource: {int(by_type.get('resource') or 0)}",
        ]
        created_items = [item for item in items if isinstance(item, dict) and item.get("status") == "created"]
        if created_items:
            lines.append("")
            lines.append("新建立筆記：")
            for item in created_items[:10]:
                lines.append(f"- {item.get('source_path')} -> {item.get('path')} ({item.get('target')})")
        failed_items = [item for item in items if isinstance(item, dict) and item.get("status") == "failed"]
        if failed_items:
            lines.append("")
            lines.append("失敗項目：")
            for item in failed_items[:5]:
                lines.append(f"- {item.get('source_path')}: {item.get('error') or 'unknown error'}")
        return "\n".join(lines)

    if request.command == "brainproject":
        payload = request.payload.strip()
        if not payload:
            return "Usage: /brainproject <title>"
        path = create_project_note(settings, payload)
        return f"已建立 Project 筆記。\npath: {path}"

    if request.command == "brainknowledge":
        payload = request.payload.strip()
        if not payload:
            return "Usage: /brainknowledge <title>"
        path = create_knowledge_note(settings, payload)
        return f"已建立 Knowledge 筆記。\npath: {path}"

    if request.command == "brainresource":
        payload = request.payload.strip()
        if not payload:
            return "Usage: /brainresource <title>"
        path = create_resource_note(settings, payload)
        return f"已建立 Resource 筆記。\npath: {path}"

    if request.command == "brainschedule":
        payload = request.payload.strip()
        if not payload:
            store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_SCHEDULE_TITLE})
            return "請輸入行程標題，或直接輸入自然語言，例如：今天下午6點半要吃藥。輸入 /menu 可離開流程。"
        parsed = parse_natural_language_schedule(payload)
        if parsed is not None:
            _set_schedule_confirm_flow(chat_id, store, parsed)
            return _schedule_confirm_response(parsed)
        store.set_ui_flow(
            chat_id,
            {
                "kind": FLOW_AWAIT_BRAIN_SCHEDULE_DATE,
                "title": payload,
            },
        )
        return f"行程標題已記下：{payload}\n請輸入日期，例如 2026-04-11。若暫時不填可輸入 skip。"

    if request.command == "braindecide":
        payload = request.payload.strip()
        if not payload:
            return "Usage: /braindecide <question>"
        related_paths, brief = build_decision_support_brief(settings, payload, limit=5)
        path = create_decision_note_from_brief(settings, payload, brief, related_notes=related_paths)
        return f"{brief}\n\n已建立決策支援筆記：{path}"

    if request.command == "brainsummary":
        path = ensure_weekly_summary_note(settings)
        return f"已準備每週摘要筆記。\npath: {path}"

    if request.command == "brainremind":
        reminders = collect_brain_reminders(settings, limit=5)
        return "提醒：\n" + "\n".join(reminders)

    if request.command == "braindaily":
        return build_daily_brief(settings)

    if request.command == "brainweekly":
        return build_weekly_brief(settings, limit=10)

    if request.command == "brainauto":
        payload = request.payload.strip().lower()
        if payload in {"", "status"}:
            automation = store.get_brain_automation(chat_id)
            return "\n".join(
                [
                    "brain auto",
                    f"enabled: {automation.get('enabled')}",
                    f"daily_time: {automation.get('daily_time')}",
                    f"weekly_day: {automation.get('weekly_day')}",
                    f"weekly_time: {automation.get('weekly_time')}",
                    f"last_daily_date: {automation.get('last_daily_date') or '-'}",
                    f"last_weekly_key: {automation.get('last_weekly_key') or '-'}",
                ]
            )
        if payload == "on":
            automation = store.update_brain_automation(chat_id, enabled=True)
            return f"brain auto enabled.\ndaily_time: {automation.get('daily_time')}\nweekly_time: {automation.get('weekly_time')}"
        if payload == "off":
            store.update_brain_automation(chat_id, enabled=False)
            return "brain auto disabled."
        return "Usage: /brainauto [on|off|status]"

    if request.command == "brainautodaily":
        payload = request.payload.strip()
        try:
            datetime.strptime(payload, "%H:%M")
        except ValueError:
            return "Usage: /brainautodaily HH:MM"
        store.update_brain_automation(chat_id, daily_time=payload)
        return f"brain daily automation updated.\ndaily_time: {payload}"

    if request.command == "brainautoweekly":
        parts = request.payload.strip().split()
        if len(parts) != 2:
            return "Usage: /brainautoweekly <weekday 0-6> HH:MM"
        weekday_raw, time_raw = parts
        try:
            weekday = int(weekday_raw)
        except ValueError:
            return "Usage: /brainautoweekly <weekday 0-6> HH:MM"
        if weekday < 0 or weekday > 6:
            return "Weekday must be 0-6, where 0 is Monday."
        try:
            datetime.strptime(time_raw, "%H:%M")
        except ValueError:
            return "Usage: /brainautoweekly <weekday 0-6> HH:MM"
        store.update_brain_automation(chat_id, weekly_day=weekday, weekly_time=time_raw)
        return f"brain weekly automation updated.\nweekly_day: {weekday}\nweekly_time: {time_raw}"

    if request.command == "robotonly":
        return "\n".join(
            [
                "robot-only",
                "instance: robot-hosted",
                f"ui_build: {UI_BUILD_TAG}",
                f"hosted_build: {HOSTED_BUILD_TAG}",
                "fingerprint: robot-only-2026-04-11-a",
            ]
        )

    if request.command == "robots":
        from robot.coordinator import RobotCoordinator
        coordinator = RobotCoordinator(settings.state_home, settings.robot_id)
        robots = coordinator.get_all_robots(timeout_seconds=60.0)
        if not robots:
            return "No active robots found."

        lines = [f"Active robots: {len(robots)}\n"]
        for robot in robots:
            age = time.time() - robot.last_heartbeat
            status_icon = "🟢" if age < 30 else "🟡" if age < 60 else "🔴"
            lines.append(
                f"{status_icon} {robot.robot_id}\n"
                f"  status: {robot.status}\n"
                f"  provider: {robot.current_provider or '-'}\n"
                f"  model: {robot.current_model or '-'}\n"
                f"  chats: {robot.active_chats} | queue: {robot.queue_size}\n"
                f"  last_seen: {int(age)}s ago\n"
            )
        return "".join(lines)

    if request.command == "robotstatus":
        from robot.coordinator import RobotCoordinator
        coordinator = RobotCoordinator(settings.state_home, settings.robot_id)

        target_id = request.payload.strip() if request.payload else settings.robot_id
        robot = coordinator.get_robot_status(target_id)

        if robot is None:
            return f"Robot not found: {target_id}"

        age = time.time() - robot.last_heartbeat
        status_icon = "🟢" if age < 30 else "🟡" if age < 60 else "🔴"

        lines = [
            f"{status_icon} Robot Status: {robot.robot_id}\n",
            f"status: {robot.status}",
            f"provider: {robot.current_provider or '-'}",
            f"model: {robot.current_model or '-'}",
            f"active_chats: {robot.active_chats}",
            f"queue_size: {robot.queue_size}",
            f"last_heartbeat: {int(age)}s ago",
        ]

        if robot.metadata:
            lines.append("\nmetadata:")
            for key, value in robot.metadata.items():
                lines.append(f"  {key}: {value}")

        return "\n".join(lines)

    return f"Unknown command: /{request.command}\nUse /help."


async def handle_control(
    chat_id: int,
    request: ClassifiedRequest,
    store: ChatStateStore,
    agents: AgentCoordinator,
) -> str | AppEvent:
    calendar_settings = getattr(agents, "_settings", None)
    if request.command in {"reset", "newthread"}:
        store.clear_thread_id(chat_id)
        return "Thread state cleared for the current provider."
    if request.command == "restart":
        return "Restart is managed by teleapp supervisor. Use Telegram command /restart."
    if request.command == "panic":
        stop_sent = agents.stop(chat_id)
        summary = store.panic_clear_agent_runtime(chat_id)
        return "\n".join(
            [
                "Panic cleanup applied.",
                f"stop_signal_sent: {stop_sent}",
                f"cleared_current_run: {summary['had_current_run']}",
                f"cleared_queue_jobs: {summary['queued_jobs']}",
                f"cleared_scheduled_jobs: {summary['scheduled_jobs']}",
            ]
        )
    if request.command == "clearqueue":
        agents.clear_queue(chat_id)
        return "Queued agent jobs cleared."
    if request.command in {"clearschedule", "clearschedules"}:
        existing_schedules = store.get_agent_schedules(chat_id)
        agents.clear_schedules(chat_id)
        if not isinstance(calendar_settings, Settings) or not calendar_settings.google_calendar_enabled:
            return "Scheduled agent jobs cleared."

        target_event_ids: list[str] = []
        for item in existing_schedules:
            event_id = str(item.get("gcal_event_id") or "").strip()
            if event_id:
                target_event_ids.append(event_id)
        deleted = 0
        delete_errors = 0
        for event_id in target_event_ids:
            try:
                if delete_google_calendar_schedule_event(calendar_settings, event_id=event_id):
                    deleted += 1
            except Exception:
                delete_errors += 1
        return "\n".join(
            [
                "Scheduled agent jobs cleared.",
                f"google_events_targeted: {len(target_event_ids)}",
                f"google_events_deleted: {deleted}",
                f"google_delete_errors: {delete_errors}",
            ]
        )
    if request.command in {"continue", "next"}:
        current = store.get_chat_state(chat_id).get("agent_current_run")
        if isinstance(current, dict):
            return (
                "An agent run is already active.\n"
                f"goal: {current.get('goal') or '<resume>'}\n"
                f"project: {_project_display(current.get('project_name'), current.get('project_path'))}\n"
                f"path: {current.get('project_path') or '-'}"
            )
        queue = store.get_agent_queue(chat_id)
        if queue:
            next_job = queue[0]
            return (
                "Next queued job:\n"
                f"goal: {next_job.get('goal') or '<resume>'}\n"
                f"project: {_project_display(next_job.get('project_name'), next_job.get('project_path'))}\n"
                f"path: {next_job.get('project_path') or '-'}"
            )
        return "No active or queued agent job.\nUse /run <goal> or /agent <goal>."
    if request.command == "stop":
        if agents.stop(chat_id):
            return "Stop signal sent to the running provider subprocess."
        if agents.is_running(chat_id):
            return "A run is active, but there is no live subprocess handle to stop."
        return "No running agent job."
    if request.command == "restart_hint":
        return "Use /reset to clear the current provider thread, then /run <goal> to start fresh."
    if request.command == "run":
        goal = request.payload.strip()
        if not goal:
            return "Usage: /run <goal>"
        status_key = heartbeat_status_key(request.request_id)
        _job_id, position, started = agents.enqueue(
            chat_id,
            goal,
            source=request.command,
            request_id=request.request_id,
            status_key=status_key,
        )
        state = store.get_chat_state(chat_id)
        queue_waiting = max(0, int(position) - 1)
        if started:
            return _status_event(
                chat_id,
                "Provider run started.\n"
                f"goal: {goal}\n"
                f"project: {_project_display(state['project_name'], state['project_path'])}\n"
                f"path: {state['project_path']}\n"
                f"queue_waiting: {queue_waiting}\n"
                "elapsed: 00:00\n"
                "heartbeat: starting (first update within 1 second)",
                status_key=status_key,
                request_id=request.request_id,
            )
        return (
            "Provider run queued.\n"
            f"goal: {goal}\n"
            f"project: {_project_display(state['project_name'], state['project_path'])}\n"
            f"path: {state['project_path']}\n"
            f"queue_position: {position}\n"
            "elapsed: 00:00\n"
            "hint: use /queue to check waiting jobs"
        )
    if request.command == "agent":
        options, error = _parse_agent_options(request.payload)
        if options is None:
            return error or "Usage: /agent ..."
        assert options.goal is not None
        status_key = heartbeat_status_key(request.request_id)
        _job_id, run_id, position, started = agents.enqueue_auto_dev(
            chat_id,
            options.goal,
            source="agent",
            profile=options.profile,
            config_path=options.config_path,
            enable_commit=options.enable_commit,
            enable_push=options.enable_push,
            enable_pr=options.enable_pr,
            disable_post_run=options.disable_post_run,
            request_id=request.request_id,
            status_key=status_key,
        )
        state = store.get_chat_state(chat_id)
        queue_waiting = max(0, int(position) - 1)
        if started:
            return _status_event(
                chat_id,
                "Auto-dev run started.\n"
                f"goal: {options.goal}\n"
                f"project: {_project_display(state['project_name'], state['project_path'])}\n"
                f"path: {state['project_path']}\n"
                f"queue_waiting: {queue_waiting}\n"
                f"run_id: {run_id}\n"
                "elapsed: 00:00\n"
                "heartbeat: starting (first update within 1 second)",
                status_key=status_key,
                request_id=request.request_id,
            )
        return (
            "Auto-dev run queued.\n"
            f"goal: {options.goal}\n"
            f"project: {_project_display(state['project_name'], state['project_path'])}\n"
            f"path: {state['project_path']}\n"
            f"queue_position: {position}\n"
            f"run_id: {run_id}\n"
            "elapsed: 00:00\n"
            "hint: use /queue to check waiting jobs"
        )
    if request.command == "agentresume":
        parsed, error = _parse_resume_options(request.payload)
        if parsed is None:
            return error or "Usage: /agentresume ..."
        resume_target = str(parsed.get("resume") or "").strip()
        options = parsed.get("options")
        assert isinstance(options, AutoDevOptions)
        if not resume_target:
            state = store.get_chat_state(chat_id)
            last = state.get("agent_last_run") if isinstance(state.get("agent_last_run"), dict) else None
            resume_target = str(last.get("run_id") or "").strip() if last else ""
        if not resume_target:
            return "No prior run_id found. Use /agentresume <run_id_or_path>."

        status_key = heartbeat_status_key(request.request_id)
        _job_id, run_id, position, started = agents.resume_auto_dev(
            chat_id,
            resume_target=resume_target,
            source="agentresume",
            profile=options.profile,
            config_path=options.config_path,
            enable_commit=options.enable_commit,
            enable_push=options.enable_push,
            enable_pr=options.enable_pr,
            disable_post_run=options.disable_post_run,
            request_id=request.request_id,
            status_key=status_key,
        )
        state = store.get_chat_state(chat_id)
        queue_waiting = max(0, int(position) - 1)
        if started:
            return _status_event(
                chat_id,
                "Auto-dev resume started.\n"
                f"goal: <resume>\n"
                f"project: {_project_display(state['project_name'], state['project_path'])}\n"
                f"path: {state['project_path']}\n"
                f"queue_waiting: {queue_waiting}\n"
                f"run_id: {run_id}\n"
                f"resume: {resume_target}\n"
                "elapsed: 00:00\n"
                "heartbeat: starting (first update within 1 second)",
                status_key=status_key,
                request_id=request.request_id,
            )
        return (
            "Auto-dev resume queued.\n"
            f"goal: <resume>\n"
            f"project: {_project_display(state['project_name'], state['project_path'])}\n"
            f"path: {state['project_path']}\n"
            f"queue_position: {position}\n"
            f"run_id: {run_id}\n"
            f"resume: {resume_target}\n"
            "elapsed: 00:00\n"
            "hint: use /queue to check waiting jobs"
        )
    if request.command == "schedule":
        sync_options, sync_error = _parse_schedule_sync_options(request.payload.strip())
        if sync_options is not None:
            if not isinstance(calendar_settings, Settings) or not calendar_settings.google_calendar_enabled:
                return "Google Calendar sync is disabled. Set ROBOT_GOOGLE_CALENDAR_ENABLED=1 first."
            mode, days, limit = sync_options
            schedules = store.get_agent_schedules(chat_id)
            state = store.get_chat_state(chat_id)
            state_defaults = {
                "project_name": state.get("project_name"),
                "project_display": _project_display(state.get("project_name"), state.get("project_path")),
                "project_path": state.get("project_path"),
            }
            try:
                updated, report = sync_schedule_jobs_with_google(
                    calendar_settings,
                    chat_id=chat_id,
                    schedules=schedules,
                    mode=mode,
                    days=days,
                    limit=limit,
                    state_defaults=state_defaults,
                )
            except Exception as exc:
                return f"Schedule sync failed.\n{exc}"
            store.set_agent_schedules(chat_id, updated)
            lines = [
                "Schedule sync completed.",
                f"mode: {report.get('mode', mode)}",
                f"days: {days}",
                f"limit: {limit}",
                f"local_before: {report.get('local_before', 0)}",
                f"local_after: {report.get('local_after', len(updated))}",
                f"pushed_created: {report.get('pushed_created', 0)}",
                f"pushed_updated: {report.get('pushed_updated', 0)}",
                f"push_errors: {report.get('push_errors', 0)}",
                f"pulled_created: {report.get('pulled_created', 0)}",
                f"pulled_updated: {report.get('pulled_updated', 0)}",
                f"pull_errors: {report.get('pull_errors', 0)}",
            ]
            errors = report.get("errors")
            if isinstance(errors, list) and errors:
                lines.append("errors:")
                for item in errors[:10]:
                    lines.append(f"- {item}")
            return "\n".join(lines)
        if sync_error is not None:
            return sync_error

        parsed, error = _parse_schedule_options(request.payload)
        if parsed is None:
            return error or "Usage: /schedule ..."
        options = parsed["options"]
        assert isinstance(options, AutoDevOptions)
        run_at = str(parsed["run_at"])
        assert options.goal is not None
        status_key = heartbeat_status_key(request.request_id or run_at)
        _job_id, run_id, count = agents.schedule_auto_dev(
            chat_id,
            options.goal,
            run_at,
            source="schedule",
            profile=options.profile,
            config_path=options.config_path,
            enable_commit=options.enable_commit,
            enable_push=options.enable_push,
            enable_pr=options.enable_pr,
            disable_post_run=options.disable_post_run,
            request_id=request.request_id,
            status_key=status_key,
        )

        gcal_lines: list[str] = []
        if isinstance(calendar_settings, Settings) and calendar_settings.google_calendar_enabled:
            schedules = store.get_agent_schedules(chat_id)
            target_idx = -1
            for idx, item in enumerate(schedules):
                if str(item.get("job_id") or "").strip() == str(_job_id).strip():
                    target_idx = idx
                    break
            if target_idx >= 0:
                target_job = dict(schedules[target_idx])
                try:
                    event_id, created = upsert_google_calendar_schedule_event(
                        calendar_settings,
                        chat_id=chat_id,
                        schedule_job=target_job,
                    )
                    target_job["gcal_event_id"] = event_id
                    target_job["gcal_last_synced_at"] = datetime.now().isoformat(timespec="seconds")
                    target_job.pop("gcal_sync_error", None)
                    schedules[target_idx] = target_job
                    store.set_agent_schedules(chat_id, schedules)
                    gcal_lines.extend(
                        [
                            f"google_calendar_sync: {'created' if created else 'updated'}",
                            f"gcal_event_id: {event_id}",
                        ]
                    )
                except Exception as exc:
                    target_job["gcal_sync_error"] = str(exc)
                    schedules[target_idx] = target_job
                    store.set_agent_schedules(chat_id, schedules)
                    gcal_lines.extend(
                        [
                            "google_calendar_sync: failed",
                            f"gcal_error: {exc}",
                        ]
                    )

        state = store.get_chat_state(chat_id)
        lines = [
            "Scheduled auto-dev run.",
            f"goal: {options.goal}",
            f"project: {_project_display(state['project_name'], state['project_path'])}",
            f"path: {state['project_path']}",
            f"run_id: {run_id}",
            f"run_at: {run_at}",
            f"scheduled_count: {count}",
        ]
        lines.extend(gcal_lines)
        return "\n".join(lines)
    return f"Unknown control command: /{request.command}"


async def handle_agent(chat_id: int, request: ClassifiedRequest, store: ChatStateStore, agents: AgentCoordinator) -> str:
    prompt = request.payload.strip()
    if not prompt:
        return "空白訊息，沒有可送給 AI 的內容。請輸入文字或使用 /help。"
    status_key = heartbeat_status_key(request.request_id)
    _job_id, position, started = agents.enqueue(
        chat_id,
        prompt,
        source="message",
        request_id=request.request_id,
        status_key=status_key,
    )
    state = store.get_chat_state(chat_id)
    queue_waiting = max(0, int(position) - 1)
    if started:
        return _status_event(
            chat_id,
            "Provider run started.\n"
            f"goal: {prompt}\n"
            f"project: {_project_display(state['project_name'], state['project_path'])}\n"
            f"path: {state['project_path']}\n"
            f"queue_waiting: {queue_waiting}\n"
            "elapsed: 00:00\n"
            "heartbeat: starting (first update within 1 second)",
            status_key=status_key,
            request_id=request.request_id,
        )
    return (
        "Provider run queued.\n"
        f"goal: {prompt}\n"
        f"project: {_project_display(state['project_name'], state['project_path'])}\n"
        f"path: {state['project_path']}\n"
        f"queue_position: {position}\n"
        "elapsed: 00:00\n"
        "hint: use /queue to check waiting jobs"
    )



