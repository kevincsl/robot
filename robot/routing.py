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
from teleapp import Button, ButtonResponse, DocumentResponse
from teleapp.context import MessageContext
from teleapp.protocol import AppEvent

from robot.agents import AgentCoordinator
from robot import i18n
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
from robot.config import PROVIDER_LABELS, Settings, VERSION, normalize_model
from robot.diagnostics import build_doctor_report
from robot.display_mode import (
    CODE_DISPLAY_SMART,
    DISPLAY_MODE_DEVELOPER,
    DISPLAY_MODE_USER,
    code_display_mode_label,
    configure_templates_for_locale,
    display_mode_label,
    format_display_mode_changed,
    format_display_mode_status,
    format_run_queued,
    format_run_started,
    normalize_code_display_mode,
    normalize_display_mode,
    resolve_display_mode_switch_text,
)
from robot.security import PERMISSION_MODES
from robot.google_calendar import (
    delete_google_calendar_schedule_event,
    sync_schedule_jobs_with_google,
    upsert_google_calendar_schedule_event,
)
from robot.model_catalog import get_model_catalog, validate_selected_model
from robot.projects import (
    add_projects_root,
    discover_project_workspaces,
    find_workspace,
    format_project_with_branch,
    list_projects_roots,
    remove_projects_root,
)
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


@dataclass(frozen=True)
class _SelectableModelOption:
    value: str
    description: str | None = None
    section: str = "provider"

COMMAND_NAMES = {
    # ── General ────────────────────────────────────────────────────
    "start",
    "help",
    "quick",
    "guide",
    "about",
    "menu",
    # ── Status / Diagnostics ───────────────────────────────────────
    "status",
    "status_robot",
    "status_teleapp",
    "doctor",
    # ── Control ────────────────────────────────────────────────────
    "reset",
    "panic",
    "restart",
    "newthread",
    "clearqueue",
    "clearschedule",
    "clearschedules",
    "lock",
    "unlock",
    "debug",
    # ── Agent / Task ───────────────────────────────────────────────
    "run",
    "agent",
    "agentstatus",
    "agentprofiles",
    "agentresume",
    "resume",
    "queue",
    "schedule",
    "schedules",
    "cron",
    # ── Display Mode ───────────────────────────────────────────────
    "mode",
    "usermode",
    "devmode",
    "developermode",
    "display_mode",
    "display_mode_user",
    "display_mode_dev",
    "display_normal",
    "display_smart",
    "display_copy_code",
    "display",
    "lang",
    "lang_zh",
    "lang_zhcn",
    "lang_zhhk",
    "lang_en",
    "lang_ja",
    "lang_ko",
    # ── Provider ───────────────────────────────────────────────────
    "provider",
    "provider_codex",
    "provider_claude",
    "provider_gemini",
    # ── Model ─────────────────────────────────────────────────────
    "model",
    "models",
    "model_codex",
    "model_claude",
    "model_gemini",
    # ── Project ────────────────────────────────────────────────────
    "project",
    "projects",
    "project_list",
    "project_switch",
    # ── Brain ─────────────────────────────────────────────────────
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
    # ── Brain (new /cmd_arg style) ─────────────────────────────────
    "brain_add",
    "brain_add_work",
    "brain_search",
    "brain_search_work",
    "brain_list",
    "brain_summary",
    "brain_batch",
    "brain_batch_auto",
    "brain_daily",
    "brain_decide",
    "brain_inbox",
    "brain_knowledge",
    "brain_organize",
    "brain_project",
    "brain_remind",
    "brain_resource",
    "brain_url",
    "brain_weekly",
    "brain_auto",
    # ── Mail ───────────────────────────────────────────────────────
    "mailcli",
    "mailjson",
    "mailbatch",
    "mailmcp",
    "mail",
    "mail_send",
    "mail_list",
    "mail_contacts",
    # ── Contact ────────────────────────────────────────────────────
    "contact",
    "contacts",
    # ── Multi-Robot ────────────────────────────────────────────────
    "robotonly",
    "robot",
    "robots",
    "robotstatus",
    # ── Developer Tools ────────────────────────────────────────────
    "compact",
    "compact_status",
    "release_check",
    "dependencies_check",
}

CONTROL_NAMES = {
    "reset",
    "panic",
    "restart",
    "clearqueue",
    "clearschedule",
    "clearschedules",
}


SECOND_LEVEL_COMMANDS = {
    "provider": ("provider_codex", "provider_claude", "provider_gemini"),
    "model": ("model_codex", "model_claude", "model_gemini"),
    "display_mode": ("display_mode_user", "display_mode_dev"),
    "brain": (
        "brain_add",
        "brain_inbox",
        "brain_list",
        "brain_search",
        "brain_organize",
        "brain_batch",
        "brain_batch_auto",
        "brain_project",
        "brain_knowledge",
        "brain_resource",
        "brain_summary",
        "brain_decide",
        "brain_remind",
        "brain_daily",
        "brain_weekly",
    ),
}


BRAIN_SLASH_ALIASES = {
    "brain_add": "brain:capture",
    "brain_inbox": "brain:inbox",
    "brain_list": "brain:read",
    "brain_search": "brain:search",
    "brain_organize": "brain:organize",
    "brain_batch": "brain:batch",
    "brain_batch_auto": "brain:batch_auto",
    "brain_project": "brain:project",
    "brain_knowledge": "brain:knowledge",
    "brain_resource": "brain:resource",
    "brain_summary": "brain:summary",
    "brain_decide": "brain:decide",
    "brain_remind": "brain:remind",
    "brain_daily": "brain:daily",
    "brain_weekly": "brain:weekly",
    "brain_add_work": "brain:capture",
    "brain_search_work": "brain:search",
    "brain_url": "brainweb",
    "brain_auto": "brainauto",
}

def _command_menu_text(command: str, items: tuple[str, ...]) -> str:
    lines = [f"{command} 可輸入:"]
    lines.extend(f"{index}. /{item}" for index, item in enumerate(items, start=1))
    return "\n".join(lines)

MENU_COMMAND_PREFIX = "menu:"
BRAIN_COMMAND_PREFIX = "brain:"
UI_BUILD_TAG = "ui-build:2026-05-01-a"
HOSTED_BUILD_TAG = "hosted-build:2026-05-01-a"
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
FLOW_AWAIT_FILE_ACTION = "await_file_action"
FLOW_BRAIN_SEARCH_RESULTS = "brain_search_results"
FLOW_BRAIN_BATCH_RESULTS = "brain_batch_results"

MENU_BUTTONS_CONFIG_NAME = "menu_buttons.json"
DEFAULT_MENU_BUTTONS: dict[str, list[tuple[str, str]]] = {
    DISPLAY_MODE_USER: [
        ("", "menu:status"),
        ("Projects", "menu:projects"),
        ("", "menu:cancel"),
    ],
    DISPLAY_MODE_DEVELOPER: [
        ("", "menu:status"),
        ("Provider", "menu:provider"),
        ("Model", "menu:model"),
        ("Projects", "menu:projects"),
        ("", "menu:cancel"),
    ],
}


def _build_menu_buttons(specs: list[tuple[str, str]]) -> list[Button]:
    return [Button(label or i18n.tr("menu." + data.split(":")[1]), data) for label, data in specs]


def _default_menu_buttons(display_mode: str) -> list[Button]:
    specs = DEFAULT_MENU_BUTTONS.get(display_mode) or DEFAULT_MENU_BUTTONS[DISPLAY_MODE_DEVELOPER]
    return _build_menu_buttons(specs)


def _load_menu_buttons(settings: Settings, display_mode: str) -> list[Button]:
    config_path = settings.project_root / MENU_BUTTONS_CONFIG_NAME
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_menu_buttons(display_mode)

    if not isinstance(payload, dict):
        return _default_menu_buttons(display_mode)

    raw_buttons = payload.get(display_mode)
    if not isinstance(raw_buttons, list):
        return _default_menu_buttons(display_mode)

    specs: list[tuple[str, str]] = []
    for item in raw_buttons:
        if not isinstance(item, dict):
            continue
        label = str(item.get("text") or "").strip()
        data = str(item.get("data") or "").strip()
        if label and data:
            specs.append((label, data))

    return _build_menu_buttons(specs) if specs else _default_menu_buttons(display_mode)


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
    t = i18n.tr
    return ButtonResponse(
        "\n".join(
            [
                t("brain_schedule.confirm_create_question"),
                "",
                f"{t('menu.schedule_label')}: {parsed['title']}",
                f"{t('menu.date_label')}: {parsed['date_text']}",
                f"{t('menu.time_label')}: {parsed['time_text']}",
                "",
                f"{t('menu.source_label')}: {parsed['source_text']}",
                "",
                t("brain_schedule.confirm_create_hint"),
                t("brain_schedule.send_to_claude_hint_1"),
                t("brain_schedule.send_to_claude_hint_2"),
                t("brain_schedule.send_to_claude_hint_3"),
            ]
        ),
        buttons=[
            Button(i18n.tr("menu.confirm_create"), "brain:schedule_confirm"),
            Button(i18n.tr("menu.send_to_claude"), "brain:schedule_send_agent"),
            Button(i18n.tr("menu.cancel"), "brain:cancel"),
        ],
    )


def _schedule_delete_confirm_response(match: dict[str, str], source_text: str) -> ButtonResponse:
    t = i18n.tr
    recurrence_label = str(match.get("recurrence") or "").strip()
    recurrence = " ".join(
        part for part in [recurrence_label, match.get("time") or ""] if part
    ).strip()
    when = recurrence or " ".join(part for part in [match.get("date") or "", match.get("time") or ""] if part).strip() or t("menu.no_time_scheduled")
    warning_line = t("brain_schedule.recurring_delete_notice") if recurrence_label else t("brain_schedule.single_delete_notice")
    return ButtonResponse(
        "\n".join(
            [
                t("brain_schedule.confirm_delete_question"),
                "",
                f"{t('menu.schedule_label')}: {match.get('title') or ''}",
                f"{t('menu.time_label')}: {when}",
                f"path: {match.get('path') or ''}",
                "",
                f"{t('menu.source_label')}: {source_text}",
                "",
                warning_line,
                t("brain_schedule.confirm_delete_hint"),
                t("brain_schedule.send_to_claude_hint_1"),
            ]
        ),
        buttons=[
            Button(i18n.tr("menu.confirm_delete"), "brain:schedule_delete_confirm"),
            Button(i18n.tr("menu.send_to_claude"), "brain:schedule_send_agent"),
            Button(i18n.tr("menu.cancel"), "brain:cancel"),
        ],
    )


def _schedule_update_confirm_response(match: dict[str, str], updates: dict[str, str], source_text: str) -> ButtonResponse:
    t = i18n.tr
    current_when = " ".join(part for part in [match.get("date") or "", match.get("time") or ""] if part).strip() or t("menu.no_time_scheduled")
    new_when = " ".join(part for part in [updates.get("date_text") or "", updates.get("time_text") or ""] if part).strip() or current_when
    recurrence_type = (updates.get("recurrence_type") or "").strip()
    recurrence_value = (updates.get("recurrence_value") or "").strip()
    recurrence_line = ""
    if recurrence_type == "daily":
        recurrence_line = f"{t('menu.recurrence_weekly_label')}: {t('menu.recurrence_daily')}"
    elif recurrence_type == "weekly":
        days = t("menu.recurrence_weekly_days")
        try:
            weekday = int(recurrence_value)
        except ValueError:
            weekday = -1
        recurrence_line = f"{t('menu.recurrence_weekly_label')}: {days[weekday] if 0 <= weekday < len(days) else t('menu.recurrence_weekly_label')}"
    elif recurrence_type == "monthly":
        recurrence_line = f"{t('menu.recurrence_monthly')}{recurrence_value}{t('menu.date_label')}" if recurrence_value else t("menu.recurrence_monthly")
    elif recurrence_type == "":
        recurrence_line = t("menu.recurrence_once")
    lines = [
        t("brain_schedule.confirm_update_question"),
        "",
        f"{t('menu.schedule_label')}: {match.get('title') or ''}",
        f"{t('menu.current_label')}: {current_when}",
        f"{t('menu.updated_label')}: {new_when}",
    ]
    if recurrence_line:
        lines.append(recurrence_line)
    lines.extend(
        [
            f"path: {match.get('path') or ''}",
            "",
            f"{t('menu.source_label')}: {source_text}",
            "",
            t("brain_schedule.confirm_update_hint"),
            t("brain_schedule.send_to_claude_hint_1"),
        ]
    )
    return ButtonResponse(
        "\n".join(lines),
        buttons=[
            Button(i18n.tr("menu.confirm_update"), "brain:schedule_update_confirm"),
            Button(i18n.tr("menu.send_to_claude"), "brain:schedule_send_agent"),
            Button(i18n.tr("menu.cancel"), "brain:cancel"),
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
        return i18n.tr("schedule.no_resend_candidate")
    source_text = str(flow.get("source_text") or "").strip()
    store.clear_ui_flow(chat_id)
    store.clear_last_schedule_candidate(chat_id)
    if not source_text:
        return i18n.tr("errors.source_text_lost")
    return await handle_agent(chat_id, ClassifiedRequest(AGENT_REQUEST, None, source_text), store, agents)


def _document_import_error_message(source_name: str, exc: Exception) -> str:
    t = i18n.tr
    message = str(exc).strip()
    lowered = message.lower()
    if isinstance(exc, FileConversionException) and "markitdown[pdf]" in lowered:
        return (
            f"{t('errors.file_no_local_path').split('.')[0]}，這個環境還沒有安裝 PDF 轉換依賴，無法匯入內容。\n"
            f"source_file: {source_name}\n"
            "needed: pip install markitdown[pdf]"
        )
    if isinstance(exc, MarkItDownException):
        details = message.splitlines()[0] if message else exc.__class__.__name__
        return (
            f"{t('errors.file_no_local_path').split('.')[0]}，無法轉換這個檔案內容。\n"
            f"source_file: {source_name}\n"
            f"error: {details}"
        )
    raise exc



def _wants_pdf_export(text: str) -> bool:
    lowered = (text or "").lower().strip()
    compact = lowered.replace(" ", "")
    has_pdf = "pdf" in compact
    has_convert = any(token in compact for token in ("轉存", "轉成", "轉換", "convert", "to", "傳給我", "給我", "send"))
    return has_pdf and has_convert


def _convert_image_to_pdf(local_path: Path) -> Path:
    suffix = local_path.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
        raise ValueError("unsupported_input")
    try:
        from PIL import Image
    except Exception as exc:
        raise RuntimeError("missing_pillow") from exc

    output_path = local_path.with_suffix(".pdf")
    if output_path.exists():
        output_path = output_path.with_name(f"{local_path.stem}-{int(time.time())}.pdf")

    image = Image.open(local_path)
    try:
        image.convert("RGB").save(output_path, "PDF", resolution=100.0)
    finally:
        with contextlib.suppress(Exception):
            image.close()
    return output_path


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
    replace: bool = True,
    request_id: str | None = None,
    typing: str | None = None,
) -> AppEvent:
    raw = {"status_key": status_key, "replace": replace}
    if typing is not None:
        raw["typing"] = typing
    return AppEvent(
        type="status",
        text=text,
        chat_id=chat_id,
        request_id=request_id,
        stream="inprocess",
        raw=raw,
    )


def _noop_event(chat_id: int, *, request_id: str | None = None) -> AppEvent:
    return AppEvent(
        type="noop",
        text="",
        chat_id=chat_id,
        request_id=request_id,
        stream="inprocess",
        raw={},
    )


def _parse_display_mode_selection(text: str | None) -> str | None:
    normalized = resolve_display_mode_switch_text(text)
    if normalized is not None:
        return normalized
    raw = str(text or "").strip().lower()
    if raw in {"user", "developer", "dev", "superuser"}:
        if raw in {"developer", "dev"}:
            return DISPLAY_MODE_DEVELOPER
        if raw == "superuser":
            return "superuser"
        return DISPLAY_MODE_USER
    return None


def _set_display_mode_response(chat_id: int, store: ChatStateStore, mode: str) -> str:
    if mode == "superuser":
        store.set_permission_mode(chat_id, "superuser")
        perm_mode = "superuser"
        # display_mode stays unchanged; show a different confirmation
        lines = [f"Permission mode switched to superuser (unrestricted).", i18n.tr("menu.current_mode_label", mode="superuser")]
        return "\n".join(lines)
    store.set_display_mode(chat_id, mode)
    store.set_permission_mode(chat_id, mode)
    next_state = store.get_chat_state(chat_id)
    normalized = normalize_display_mode(str(next_state.get("display_mode") or mode))
    perm_mode = next_state.get("permission_mode") or mode
    return "\n".join(
        [
            format_display_mode_changed(normalized),
            i18n.tr("menu.current_mode_label", mode=display_mode_label(normalized)),
            f"[permission mode: {perm_mode}]",
        ]
    )


def _set_code_display_mode_response(chat_id: int, store: ChatStateStore, mode: str) -> str:
    normalized = normalize_code_display_mode(mode)
    store.set_code_display_mode(chat_id, normalized)
    return "\n".join(
        [
            "COPY CODE 顯示模式已更新。",
            f"mode: {code_display_mode_label(normalized)}",
            "normal: 一般文字照舊",
            "smart: 只有原本 code block 顯示 COPY CODE",
            "copy_code: 一般輸出整段包成 COPY CODE",
            "(相容舊參數: all)",
        ]
    )


def _code_display_usage(store: ChatStateStore, chat_id: int) -> str:
    current = code_display_mode_label(store.get_code_display_mode(chat_id))
    return "\n".join(
        [
            "COPY CODE 顯示模式：",
            f"current: {current}",
            "用法:",
            "- /display_normal",
            "- /display_smart",
            "- /display_copy_code",
            "- /display <normal|smart|copy_code>",
            "- /display normal",
            "- /display smart",
            "- /display copy_code",
        ]
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
        if stripped.lower() == command.lower():
            return ""
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

    if command in CONTROL_NAMES:
        return ClassifiedRequest(CONTROL_REQUEST, command, _resolved_payload(text, command), ctx.request_id)
    if command in COMMAND_NAMES:
        return ClassifiedRequest(COMMAND_REQUEST, command, _resolved_payload(text, command), ctx.request_id)
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
    runtime_model = provider_timing.get("model") or "not_run_yet"
    teleapp_status_edit = "enabled"
    teleapp_raw_status = "enabled"
    risk_mode = bool(settings.codex_bypass_approvals_and_sandbox or settings.codex_skip_git_repo_check)
    return "\n".join(
        [
            "robot status",
            f"version: {VERSION}",
            f"display_mode: {state.get('display_mode') or DISPLAY_MODE_DEVELOPER}",
            f"code_display_mode: {state.get('code_display_mode') or CODE_DISPLAY_SMART}",
            f"provider: {state['provider']}",
            f"model: {state['model']}",
            f"runtime_model: {runtime_model}",
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
            "- command request: /provider /model /project /status /cron /agentstatus /agentprofiles",
            "- control request: /reset /restart /panic",
            "- agent request: plain text (provider runner)",
            "- /provider_codex /provider_claude /provider_gemini (direct switch)",
            "- /model_codex /model_claude /model_gemini (list models)",
            "- /display_mode_user /display_mode_dev (mode switch)",
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
            "/mode [user|developer]",
            "/display [normal|smart|copy_code]",
            "/display_normal  /display_smart  /display_copy_code",
            "/project register [name] <path>",
            "/project list",
            "/project use <name|key>",
            "/project info <name|key>",
            "/project note <name|key> <text>",
            "/project doctor <name|key|all>",
            "/project roots list|add <path>|remove <path>",
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
            "- /mode [user|developer]",
            "- /display [normal|smart|copy_code]",
            "- /display_normal /display_smart /display_copy_code",
            "- /project register [name] <path>",
            "- /project list",
            "- /project use <name|key>",
            "- /project roots list|add <path>|remove <path>",
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
            "- /mode [user|developer]",
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
            "- project management",
            "- cancel",
            "",
            "slash commands:",
            "- /status",
            "- /provider claude",
            "- /model gpt-5.4",
            "- /project list",
            "- /project use <name|key>",
            "",
            i18n.tr("menu.note_mode_hint"),
        ]
    )


def _brain_text() -> str:
    return "\n".join(
        [
            "brain menu",
            UI_BUILD_TAG,
            i18n.tr("menu.tg_secondbrain_hint"),
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
            Button(i18n.tr("menu.brain_write_today"), "brain:capture"),
            Button(i18n.tr("menu.brain_inbox"), "brain:inbox"),
            Button(i18n.tr("menu.brain_read_today"), "brain:read"),
            Button(i18n.tr("menu.brain_search"), "brain:search"),
            Button(i18n.tr("menu.brain_organize"), "brain:organize"),
            Button(i18n.tr("menu.brain_batch"), "brain:batch"),
            Button(i18n.tr("menu.brain_batch_auto"), "brain:batch_auto"),
            Button(i18n.tr("menu.brain_project"), "brain:project"),
            Button(i18n.tr("menu.brain_knowledge"), "brain:knowledge"),
            Button(i18n.tr("menu.brain_resource"), "brain:resource"),
            Button(i18n.tr("menu.brain_schedule"), "brain:schedule"),
            Button(i18n.tr("menu.brain_summary"), "brain:summary"),
            Button(i18n.tr("menu.brain_decide"), "brain:decide"),
            Button(i18n.tr("menu.brain_remind"), "brain:remind"),
            Button(i18n.tr("menu.brain_daily"), "brain:daily"),
            Button(i18n.tr("menu.brain_weekly"), "brain:weekly"),
            Button(i18n.tr("menu.cancel"), "brain:cancel"),
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
        store.clear_ui_flow(chat_id)
        return _command_menu_text("brain", SECOND_LEVEL_COMMANDS["brain"])

    if command == "brain:cancel":
        flow = store.get_ui_flow(chat_id)
        if isinstance(flow, dict) and flow.get("kind") == FLOW_AWAIT_BRAIN_SCHEDULE_CONFIRM:
            return await _send_schedule_confirm_source_to_agent(chat_id, store, agents)
        store.clear_ui_flow(chat_id)
        return i18n.tr("menu.brain_menu_canceled")

    if command == "brain:capture":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_CAPTURE})
        return i18n.tr("menu.capture_prompt")

    if command == "brain:inbox":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_INBOX})
        return i18n.tr("menu.inbox_prompt")

    if command == "brain:read":
        body = read_daily(settings).strip()
        return body if body else i18n.tr("menu.daily_note_empty")

    if command == "brain:search":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_SEARCH})
        return i18n.tr("menu.search_prompt")

    if command == "brain:organize":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_ORGANIZE_TEXT})
        return i18n.tr("menu.organize_source_placeholder")

    if command == "brain:batch":
        items = list_recent_notes(settings, "00 Inbox", limit=5) + list_recent_notes(settings, "01 Daily Notes", limit=5)
        items = items[:10]
        if not items:
            return i18n.tr("menu.no_batch_results")
        store.set_ui_flow(chat_id, {"kind": FLOW_BRAIN_BATCH_RESULTS, "results": items})
        return ButtonResponse(
            i18n.tr("menu.batch_note_list"),
            buttons=[Button(item, f"brain:batch_open:{idx}") for idx, item in enumerate(items)],
        )

    if command == "brain:batch_auto":
        summary = auto_organize_recent_notes(settings, limit=10)
        processed = int(summary.get("processed") or 0)
        if processed == 0:
            return i18n.tr("menu.no_auto_batch_results")
        by_type = summary.get("by_type")
        items = summary.get("items")
        if not isinstance(by_type, dict):
            by_type = {}
        if not isinstance(items, list):
            items = []
        lines = [
            i18n.tr("menu.auto_batch_done"),
            f"- processed: {processed}",
            f"- created: {int(summary.get('created') or 0)}",
            f"- skipped: {int(summary.get('skipped') or 0)}",
            f"- failed: {int(summary.get('failed') or 0)}",
            "",
            i18n.tr("menu.batch_stats"),
            f"- project: {int(by_type.get('project') or 0)}",
            f"- knowledge: {int(by_type.get('knowledge') or 0)}",
            f"- resource: {int(by_type.get('resource') or 0)}",
        ]
        created_items = [item for item in items if isinstance(item, dict) and item.get("status") == "created"]
        if created_items:
            lines.append("")
            lines.append(i18n.tr("brain_schedule.new_note_title"))
            for item in created_items[:10]:
                lines.append(f"- {item.get('source_path')} -> {item.get('path')} ({item.get('target')})")
        failed_items = [item for item in items if isinstance(item, dict) and item.get("status") == "failed"]
        if failed_items:
            lines.append("")
            lines.append(i18n.tr("errors.fail_items"))
            for item in failed_items[:5]:
                lines.append(f"- {item.get('source_path')}: {item.get('error') or 'unknown error'}")
        return "\n".join(lines)

    if command == "brain:project":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_PROJECT})
        return i18n.tr("brain_schedule.enter_project_name")

    if command == "brain:knowledge":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_KNOWLEDGE})
        return i18n.tr("brain_schedule.enter_knowledge_title")

    if command == "brain:resource":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_RESOURCE})
        return i18n.tr("brain_schedule.enter_resource_title")

    if command == "brain:schedule":
        return ButtonResponse(
            i18n.tr("menu.schedule_menu"),
            buttons=[
                Button(i18n.tr("menu.schedule_new"), "brain:schedule_new"),
                Button(i18n.tr("menu.schedule_today"), "brain:schedule_today"),
                Button(i18n.tr("menu.schedule_week"), "brain:schedule_week"),
                Button(i18n.tr("menu.schedule_next_week"), "brain:schedule_next_week"),
                Button(i18n.tr("menu.schedule_month"), "brain:schedule_month"),
                Button(i18n.tr("menu.schedule_list"), "brain:schedule_list"),
                Button(i18n.tr("menu.cancel"), "brain:cancel"),
            ],
        )

    if command == "brain:schedule_new":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_SCHEDULE_TITLE})
        return i18n.tr("menu.schedule_prompt")

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
            return i18n.tr("menu.no_expired_schedules")
        lines = [i18n.tr("menu.archived_schedules"), ""]
        for item in archived:
            when = " ".join(part for part in [item.get("date") or "", item.get("time") or ""] if part).strip()
            lines.append(f"- {when} | {item.get('title')}")
            lines.append(f"  from: {item.get('path')}")
            lines.append(f"  to: {item.get('archived_path')}")
        return "\n".join(lines)

    if command == "brain:schedule_confirm":
        flow = store.get_ui_flow(chat_id)
        if not isinstance(flow, dict) or flow.get("kind") != FLOW_AWAIT_BRAIN_SCHEDULE_CONFIRM:
            return i18n.tr("schedule.no_pending")
        title = str(flow.get("title") or "").strip()
        date_text = str(flow.get("date_text") or "").strip()
        time_text = str(flow.get("time_text") or "").strip()
        recurrence_type = str(flow.get("recurrence_type") or "").strip()
        recurrence_value = str(flow.get("recurrence_value") or "").strip()
        if not title:
            store.clear_ui_flow(chat_id)
            return i18n.tr("menu.schedule_data_lost")
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
        return i18n.tr("brain_schedule.created_schedule_note", path=path, body=body)

    if command == "brain:schedule_send_agent":
        return await _send_schedule_confirm_source_to_agent(chat_id, store, agents)

    if command == "brain:schedule_delete_confirm":
        flow = store.get_ui_flow(chat_id)
        if not isinstance(flow, dict) or flow.get("kind") != FLOW_AWAIT_BRAIN_SCHEDULE_DELETE_CONFIRM:
            return i18n.tr("schedule.no_pending_delete")
        path = str(flow.get("path") or "").strip()
        if not path:
            store.clear_ui_flow(chat_id)
            store.clear_last_schedule_candidate(chat_id)
            return i18n.tr("errors.generic")
        archived_path = archive_schedule_note(settings, path)
        store.clear_ui_flow(chat_id)
        store.clear_last_schedule_candidate(chat_id)
        return i18n.tr("menu.schedule_archived", from_path=path, to_path=archived_path)

    if command == "brain:schedule_update_confirm":
        flow = store.get_ui_flow(chat_id)
        if not isinstance(flow, dict) or flow.get("kind") != FLOW_AWAIT_BRAIN_SCHEDULE_UPDATE_CONFIRM:
            return i18n.tr("schedule.no_pending_update")
        path = str(flow.get("path") or "").strip()
        if not path:
            store.clear_ui_flow(chat_id)
            store.clear_last_schedule_candidate(chat_id)
            return i18n.tr("errors.generic")
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
        return i18n.tr("brain_schedule.updated_schedule_note", path=path, body=body)

    if command == "brain:summary":
        path = ensure_weekly_summary_note(settings)
        body = read_note(settings, path).strip()
        return i18n.tr("brain_schedule.created_weekly_summary_note", path=path, body=body)

    if command == "brain:decide":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_DECIDE})
        return i18n.tr("brain_schedule.enter_decision_question")

    if command == "brain:remind":
        reminders = collect_brain_reminders(settings, limit=5)
        return i18n.tr("menu.reminders_label") + "\n" + "\n".join(reminders)

    if command == "brain:daily":
        return build_daily_brief(settings)

    if command == "brain:weekly":
        return build_weekly_brief(settings, limit=10)

    if command.startswith("brain:open_note:"):
        raw_index = command.rsplit(":", 1)[1].strip()
        flow = store.get_ui_flow(chat_id)
        if not isinstance(flow, dict) or flow.get("kind") != FLOW_BRAIN_SEARCH_RESULTS:
            return i18n.tr("menu.no_search_results")
        results = flow.get("results")
        if not isinstance(results, list):
            return i18n.tr("errors.search_results_expired")
        try:
            index = int(raw_index)
        except ValueError:
            return i18n.tr("errors.invalid_search_index")
        if index < 0 or index >= len(results):
            return i18n.tr("errors.search_index_out_of_range")
        path = str(results[index]).strip()
        body = read_note(settings, path).strip()
        return f"{path}\n\n{body}" if body else f"{path}\n\n這篇筆記目前是空的。"

    if command.startswith("brain:batch_open:"):
        raw_index = command.rsplit(":", 1)[1].strip()
        flow = store.get_ui_flow(chat_id)
        if not isinstance(flow, dict) or flow.get("kind") != FLOW_BRAIN_BATCH_RESULTS:
            return i18n.tr("errors.batch_results_unavailable")
        results = flow.get("results")
        if not isinstance(results, list):
            return i18n.tr("errors.batch_results_expired")
        try:
            index = int(raw_index)
        except ValueError:
            return i18n.tr("errors.invalid_batch_index")
        if index < 0 or index >= len(results):
            return i18n.tr("errors.batch_index_out_of_range")
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
            i18n.tr("menu.organize_loaded", path=path),
            buttons=[
                Button(i18n.tr("organize.project_label"), "brain:organize_target:project"),
                Button(i18n.tr("organize.knowledge_label"), "brain:organize_target:knowledge"),
                Button(i18n.tr("menu.brain_resource"), "brain:organize_target:resource"),
            ],
        )

    if command.startswith("brain:organize_target:"):
        target = command.rsplit(":", 1)[1].strip()
        flow = store.get_ui_flow(chat_id)
        if not isinstance(flow, dict) or flow.get("kind") != FLOW_AWAIT_BRAIN_ORGANIZE_TARGET:
            return i18n.tr("errors.organize_no_pending")
        source_text = str(flow.get("source_text") or "").strip()
        if not source_text:
            return i18n.tr("errors.organize_source_lost")
        if target not in {"project", "knowledge", "resource"}:
            return i18n.tr("errors.invalid_organize_target")
        store.set_ui_flow(
            chat_id,
            {
                "kind": FLOW_AWAIT_BRAIN_ORGANIZE_TITLE,
                "source_text": source_text,
                "target": target,
            },
        )
        labels = {
            "project": i18n.tr("organize.project_label"),
            "knowledge": i18n.tr("organize.knowledge_label"),
            "resource": i18n.tr("organize.resource_label"),
        }
        return i18n.tr("organize.enter_title", label=labels[target])

    return f"Unknown brain action: {command}"


def _main_menu_response(chat_id: int, store: ChatStateStore, settings: Settings) -> ButtonResponse:
    display_mode = store.get_display_mode(chat_id)
    buttons = _load_menu_buttons(settings, display_mode)
    return ButtonResponse(
        _menu_text(chat_id, store),
        buttons=buttons,
    )


def _provider_menu_response(chat_id: int, store: ChatStateStore) -> str:
    state = store.get_chat_state(chat_id)
    store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_PROVIDER})
    return "\n".join([f"Current provider: {state['provider']}", _command_menu_text("provider", SECOND_LEVEL_COMMANDS["provider"])])


def _invalid_model_message(provider: str, model: str) -> str:
    return (
        f"Model not available for {provider}: {model}\n"
        "Use /models to view available models, then choose again with /model <name>."
    )


def _model_menu_response(chat_id: int, store: ChatStateStore, settings: Settings) -> ButtonResponse:
    state = store.get_chat_state(chat_id)
    provider = str(state["provider"])
    catalog = get_model_catalog(settings, provider)
    default_model = _default_model_name(provider, settings)
    options = _selectable_model_options(settings, provider, catalog)
    store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_MODEL})
    lines = [
        "Select Model",
        UI_BUILD_TAG,
        f"provider: {provider}",
        f"source: {catalog.source}",
        "",
        i18n.tr("menu.provider_switch_hint"),
        "",
    ]
    if catalog.note:
        lines.extend([f"note: {catalog.note}", ""])
    buttons: list[Button] = []
    current_section = "provider"
    for index, option in enumerate(options, start=1):
        if option.section != current_section:
            lines.append(i18n.tr("menu.custom_models_section"))
            current_section = option.section
        tags: list[str] = []
        if option.value == default_model:
            tags.append("default")
        if option.value == state["model"]:
            tags.append("current")
        marker = f" ({', '.join(tags)})" if tags else ""
        if option.description:
            lines.append(f"{index}. {option.value}{marker}  {option.description}")
        else:
            lines.append(f"{index}. {option.value}{marker}")
        buttons.append(Button(option.value, f"menu:set_model:{option.value}"))
    lines.extend(
        [
            "",
            f"/model <name> {i18n.tr('menu.model_menu_hint').split('。')[0]}",
            i18n.tr("menu.input_model_name"),
        ]
    )
    return ButtonResponse("\n".join(lines), buttons=buttons)


def _default_model_name(provider: str, settings: Settings) -> str:
    if provider == settings.default_provider:
        return normalize_model(provider, settings.default_model)
    return normalize_model(provider, None)


def _selectable_model_options(
    settings: Settings,
    provider: str,
    catalog=None,
) -> list[_SelectableModelOption]:
    resolved_catalog = catalog or get_model_catalog(settings, provider)
    options = [
        _SelectableModelOption(value=item.name, description=item.description, section="provider")
        for item in resolved_catalog.items
    ]
    options.append(
        _SelectableModelOption(
            value="custom",
            description=i18n.tr("menu.custom_model_hint"),
            section="provider",
        )
    )
    options.extend(
        _SelectableModelOption(value=item, description=None, section="custom")
        for item in settings.custom_models
    )
    return options


def _resolve_model_selection(provider: str, text: str, settings: Settings) -> str | None:
    normalized = text.strip()
    if not normalized:
        return None
    if normalized.lower().startswith("model "):
        normalized = normalized[6:].strip()
    models = _selectable_model_options(settings, provider)
    if normalized.isdigit():
        index = int(normalized)
        if 1 <= index <= len(models):
            return models[index - 1].value
        return None
    lowered = normalized.lower()
    lookup = {item.value.lower(): item.value for item in models}
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

    registered_items, _active_name = list_registered_projects(settings)
    registered_by_key: dict[str, str] = {}
    registered_by_path: dict[str, str] = {}
    for item in registered_items:
        name = str(item.get("name") or "").strip()
        key = str(item.get("key") or "").strip()
        path = str(item.get("path") or "").strip()
        if key and name:
            registered_by_key[key] = name
        if path and name:
            registered_by_path[path] = name

    store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_PROJECT})
    status_lines: list[str] = []
    registered_count = 0
    lines = [
        f"Current project: {_project_display(state['project_name'], state['project_path'])}",
        f"Available projects: {len(workspaces)}",
    ]
    buttons: list[Button] = []
    for workspace in workspaces:
        workspace_path = str(workspace.path)
        registered_name = registered_by_key.get(workspace.key) or registered_by_path.get(workspace_path)
        if registered_name:
            registered_count += 1
            status_lines.append(f"- {workspace.label} | {workspace.key} | registered ({registered_name})")
        else:
            status_lines.append(f"- {workspace.label} | {workspace.key} | unregistered")
        buttons.append(Button(f"Use: {workspace.label}", workspace.key))
        if not registered_name:
            buttons.append(Button(f"Register: {workspace.label}", f"menu:projects:register:{workspace.key}"))
    lines.append(f"Registered in list: {registered_count}/{len(workspaces)}")
    lines.extend(["", *status_lines])
    lines.extend(
        [
            "",
            i18n.tr("menu.project_menu_hint"),
        ]
    )
    return ButtonResponse("\n".join(lines), buttons=buttons)


def _project_matches_chat_context(item: dict[str, object], state: dict[str, object]) -> bool:
    state_key = str(state.get("project_key") or "").strip()
    state_path = str(state.get("project_path") or "").strip()
    state_name = str(state.get("project_name") or "").strip()

    item_key = str(item.get("key") or "").strip()
    item_path = str(item.get("path") or "").strip()
    item_name = str(item.get("name") or "").strip()

    if state_key and item_key and item_key == state_key:
        return True
    if state_path and item_path and item_path == state_path:
        return True
    if state_name and item_name and item_name == state_name:
        return True
    return False


def _project_management_menu_response(chat_id: int, settings: Settings, store: ChatStateStore) -> ButtonResponse:
    state = store.get_chat_state(chat_id)
    items, active_name = list_registered_projects(settings)
    lines = [
        "Project management",
        f"Current context: {_project_display(state['project_name'], state['project_path'])}",
        f"Registered projects: {len(items)}",
        "",
        i18n.tr("menu.recommended_flow"),
        "1) /project register [name] <path>",
        "2) /project use <name|key>",
        "3) /project info <name|key>",
        "4) /project roots add <path> / remove <path>",
        "",
        i18n.tr("menu.available_buttons"),
    ]
    buttons: list[Button] = [
        Button("List", "menu:projects:list"),
        Button("Discover", "menu:projects:discover"),
        Button("Roots", "menu:projects:roots"),
    ]
    has_chat_project = bool(state.get("project_key") or state.get("project_path") or state.get("project_name"))
    for item in items[:5]:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        is_active = _project_matches_chat_context(item, state)
        if not is_active and not has_chat_project:
            is_active = name == active_name
        marker = " *" if is_active else ""
        buttons.append(Button(f"Use {name}{marker}", f"menu:projects:use:{name}"))
    buttons.append(Button("Back", "menu:open"))
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
    has_chat_project = bool(state.get("project_key") or state.get("project_path") or state.get("project_name"))
    for index, item in enumerate(items, start=1):
        name = str(item.get("name") or "-")
        key = str(item.get("key") or "-")
        path = str(item.get("path") or "-")
        status = project_status(item)
        recent = str(item.get("last_activity_at") or item.get("last_used_at") or item.get("updated_at") or "-")
        is_active = _project_matches_chat_context(item, state)
        if not is_active and not has_chat_project:
            is_active = name == active_name
        marker = "  *active" if is_active else ""
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
    if action in {"discover", "scan"}:
        return _projects_menu_response(chat_id, settings, store)

    if action in {"list", "ls"}:
        store.clear_ui_flow(chat_id)
        return _render_project_registry_list(chat_id, settings, store)

    if action == "roots":
        if len(parts) < 2:
            return "Usage: /project roots list|add <path>|remove <path>"
        roots_action = str(parts[1]).strip().lower()
        if roots_action in {"list", "ls"}:
            roots = list_projects_roots(settings)
            if not roots:
                return "No scan roots configured."
            lines = [f"Scan roots: {len(roots)}"]
            for index, root in enumerate(roots, start=1):
                lines.append(f"{index}. {root}")
            return "\n".join(lines)
        if roots_action in {"add", "register"}:
            if len(parts) < 3:
                return "Usage: /project roots add <path>"
            roots = add_projects_root(settings, parts[2])
            return "\n".join(
                [
                    "Scan root added.",
                    f"path: {Path(parts[2]).expanduser().resolve()}",
                    f"total_roots: {len(roots)}",
                ]
            )
        if roots_action in {"remove", "rm", "delete"}:
            if len(parts) < 3:
                return "Usage: /project roots remove <path>"
            removed, roots = remove_projects_root(settings, parts[2])
            status = "Scan root removed." if removed else "Scan root not found in dynamic roots."
            return "\n".join(
                [
                    status,
                    f"path: {Path(parts[2]).expanduser().resolve()}",
                    f"total_roots: {len(roots)}",
                ]
            )
        return "Usage: /project roots list|add <path>|remove <path>"

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
        state = store.get_chat_state(chat_id)
        current_name = str(state.get("project_name") or "").strip()
        current_key = str(state.get("project_key") or "").strip()
        current_path = str(state.get("project_path") or "").strip()
        if current_name or current_key or current_path:
            return (
                "active project\n"
                f"name: {current_name or '-'}\n"
                f"key: {current_key or '-'}\n"
                f"path: {current_path or '-'}"
            )
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
        return _main_menu_response(chat_id, store, settings)

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
            + i18n.tr("menu.model_select_hint")
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
                + i18n.tr("menu.invalid_custom_model")
            )
        provider = str(store.get_chat_state(chat_id)["provider"])
        _is_catalog_model, validation_error = validate_selected_model(settings, provider, model)
        if validation_error:
            return validation_error
        next_state = store.set_model(chat_id, model)
        store.clear_ui_flow(chat_id)
        return (
            f"Model updated.\nprovider: {next_state['provider']}\nmodel: {next_state['model']}\n\n"
            + i18n.tr("menu.model_select_hint")
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
            + i18n.tr("menu.model_select_hint")
        )

    if command == "menu:projects":
        store.clear_ui_flow(chat_id)
        return _project_management_menu_response(chat_id, settings, store)

    if command == "menu:projects:list":
        store.clear_ui_flow(chat_id)
        return _handle_project_command(chat_id, "list", settings, store)

    if command == "menu:projects:discover":
        return _projects_menu_response(chat_id, settings, store)

    if command == "menu:projects:roots":
        return _handle_project_command(chat_id, "roots list", settings, store)

    if command.startswith("menu:projects:use:"):
        name = command.removeprefix("menu:projects:use:").strip()
        if not name:
            return "Empty project selection."
        store.clear_ui_flow(chat_id)
        return _handle_project_command(chat_id, f"use {name}", settings, store)

    if command.startswith("menu:projects:register:"):
        key = command.removeprefix("menu:projects:register:").strip()
        if not key:
            return "Empty project key."
        workspaces = discover_project_workspaces(settings)
        workspace = next((w for w in workspaces if w.key == key), None)
        if workspace is None:
            return f"Project not found: {key}"
        try:
            project = register_project(settings, workspace.label, str(workspace.path))
            return (
                i18n.tr("menu.project_registered", label=workspace.label) + "\n"
                f"key: {project.get('key')}\n"
                f"path: {project.get('path')}"
            )
        except ValueError as exc:
            return i18n.tr("errors.register_failed", exc=exc)

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
        return i18n.tr("menu.use_model_button")

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
                + i18n.tr("menu.model_select_hint")
            )
        return None

    if kind == FLOW_AWAIT_BRAIN_CAPTURE:
        path = append_to_daily(settings, text)
        store.clear_ui_flow(chat_id)
        return i18n.tr("menu.file_imported", path=path)

    if kind == FLOW_AWAIT_BRAIN_INBOX:
        path = create_inbox_note(settings, text)
        store.clear_ui_flow(chat_id)
        return i18n.tr("menu.inbox_created", path=path)

    if kind == FLOW_AWAIT_BRAIN_SEARCH:
        matches = search_vault(settings, text, limit=10)
        if not matches:
            store.clear_ui_flow(chat_id)
            return i18n.tr("brain.no_results", text=text)
        store.set_ui_flow(chat_id, {"kind": FLOW_BRAIN_SEARCH_RESULTS, "results": matches[:10]})
        return ButtonResponse(
            i18n.tr("brain.search_results_header", text=text),
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
            i18n.tr("organize.pick_type"),
            buttons=[
                Button(i18n.tr("organize.project_label"), "brain:organize_target:project"),
                Button(i18n.tr("organize.knowledge_label"), "brain:organize_target:knowledge"),
                Button(i18n.tr("organize.resource_label"), "brain:organize_target:resource"),
            ],
        )

    if kind == FLOW_AWAIT_BRAIN_PROJECT:
        path = create_project_note(settings, text)
        body = read_note(settings, path).strip()
        store.clear_ui_flow(chat_id)
        return i18n.tr("brain_schedule.created_project_note", path=path, body=body)

    if kind == FLOW_AWAIT_BRAIN_KNOWLEDGE:
        path = create_knowledge_note(settings, text)
        body = read_note(settings, path).strip()
        store.clear_ui_flow(chat_id)
        return i18n.tr("brain_schedule.created_knowledge_note", path=path, body=body)

    if kind == FLOW_AWAIT_BRAIN_RESOURCE:
        path = create_resource_note(settings, text)
        body = read_note(settings, path).strip()
        store.clear_ui_flow(chat_id)
        return i18n.tr("brain_schedule.created_resource_note", path=path, body=body)

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
        return i18n.tr("schedule.title_remembered", title=text) + "\n" + i18n.tr("schedule.enter_date")

    if kind == FLOW_AWAIT_BRAIN_SCHEDULE_DATE:
        title = str(flow.get("title") or "").strip()
        if not title:
            store.clear_ui_flow(chat_id)
            return i18n.tr("errors.generic")
        date_text = "" if text.lower() in i18n.tr_tokens("menu.detect_skip_tokens") else text
        store.set_ui_flow(
            chat_id,
            {
                "kind": FLOW_AWAIT_BRAIN_SCHEDULE_TIME,
                "title": title,
                "date_text": date_text,
            },
        )
        return i18n.tr("schedule.enter_time")

    if kind == FLOW_AWAIT_BRAIN_SCHEDULE_TIME:
        title = str(flow.get("title") or "").strip()
        if not title:
            store.clear_ui_flow(chat_id)
            return i18n.tr("errors.generic")
        date_text = str(flow.get("date_text") or "").strip()
        time_text = "" if text.lower() in i18n.tr_tokens("menu.detect_skip_tokens") else text
        path = create_schedule_note(settings, title, date_text=date_text, time_text=time_text)
        body = read_note(settings, path).strip()
        store.clear_ui_flow(chat_id)
        return i18n.tr("brain_schedule.created_schedule_note", path=path, body=body)

    if kind == FLOW_AWAIT_BRAIN_ORGANIZE_TITLE:
        flow = store.get_ui_flow(chat_id)
        if not isinstance(flow, dict):
            return i18n.tr("errors.organize_flow_expired")
        source_text = str(flow.get("source_text") or "").strip()
        target = str(flow.get("target") or "").strip()
        if not source_text or target not in {"project", "knowledge", "resource"}:
            return i18n.tr("errors.organize_flow_incomplete")
        if target == "project":
            path = create_project_note_from_text(settings, text, source_text)
            label = i18n.tr("organize.project_label")
        elif target == "knowledge":
            path = create_knowledge_note_from_text(settings, text, source_text)
            label = i18n.tr("organize.knowledge_label")
        else:
            path = create_resource_note_from_text(settings, text, source_text)
            label = i18n.tr("organize.resource_label")
        body = read_note(settings, path).strip()
        store.clear_ui_flow(chat_id)
        return i18n.tr("brain_schedule.organized_note", label=label, path=path, body=body)

    if kind == FLOW_AWAIT_FILE_ACTION:
        local_path = str(flow.get("local_path") or "").strip()
        source_name = str(flow.get("source_name") or "").strip()
        title = str(flow.get("title") or "").strip()
        if not local_path:
            store.clear_ui_flow(chat_id)
            return i18n.tr("menu.file_processing_error")
        if not source_name:
            source_name = Path(local_path).name
        if not title:
            title = Path(source_name).stem if source_name else Path(local_path).stem

        lowered = text.lower()
        should_import = any(token in lowered for token in i18n.tr_tokens("menu.detect_import_tokens"))
        if should_import:
            try:
                note_path, extracted = import_markitdown_resource(settings, Path(local_path), title=title)
            except (FileConversionException, MarkItDownException) as exc:
                store.clear_ui_flow(chat_id)
                return _document_import_error_message(source_name, exc)

            preview = extracted.strip().replace("\r\n", "\n")
            if len(preview) > 500:
                preview = preview[:500].rstrip() + "..."
            store.clear_ui_flow(chat_id)
            return (
                i18n.tr("document.imported_to_secondbrain") + "\n"
                f"path: {note_path}\n"
                f"source_file: {source_name}\n\n"
                f"{preview or '(No extracted text)'}"
            )

        if _wants_pdf_export(text):
            try:
                output_path = _convert_image_to_pdf(Path(local_path))
            except ValueError:
                store.clear_ui_flow(chat_id)
                return (
                    i18n.tr("document.image_to_pdf_only") + "\n"
                    f"source_file: {source_name}"
                )
            except RuntimeError:
                store.clear_ui_flow(chat_id)
                return i18n.tr("document.pdf_missing_dependency")
            except Exception as exc:
                store.clear_ui_flow(chat_id)
                return (
                    i18n.tr("errors.pdf_convert_failed") + "\n"
                    f"source_file: {source_name}\n"
                    f"error: {exc.__class__.__name__}: {exc}"
                )

            store.clear_ui_flow(chat_id)
            return DocumentResponse(
                text=i18n.tr("document.pdf_converted"),
                file_path=str(output_path),
                caption=f"source_file: {source_name}",
            )

        store.clear_ui_flow(chat_id)
        return await handle_agent(
            chat_id,
            ClassifiedRequest(
                AGENT_REQUEST,
                None,
                "\n".join(
                    [
                        f"source_file: {source_name}",
                        f"local_path: {local_path}",
                        f"user_request: {text}",
                    ]
                ),
            ),
            store,
            agents,
        )

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

    # Load user's locale preference
    i18n.set_locale(store.get_locale(ctx.chat_id))

    if ctx.document is not None and not command:
        from robot.security import sanitize_file_size, SecurityError

        local_path = str(ctx.document.local_path or "").strip()
        if not local_path:
            return i18n.tr("errors.file_no_local_path")

        try:
            sanitize_file_size(Path(local_path), max_size_mb=50)
        except SecurityError as exc:
            return i18n.tr("errors.file_size_failed", exc=exc)

        title = (ctx.caption or "").strip()
        source_name = str(ctx.document.file_name or Path(local_path).name)
        if not title:
            file_name = str(ctx.document.file_name or "").strip()
            title = Path(file_name).stem if file_name else Path(local_path).stem
        store.set_ui_flow(
            ctx.chat_id,
            {
                "kind": FLOW_AWAIT_FILE_ACTION,
                "local_path": local_path,
                "source_name": source_name,
                "title": title,
                "mime_type": str(ctx.document.mime_type or "").strip(),
            },
        )
        return i18n.tr("menu.file_received_prompt", name=source_name)

    if command == "menu":
        store.clear_ui_flow(ctx.chat_id)
        return _main_menu_response(ctx.chat_id, store, settings)
    if command == "model":
        return _model_menu_response(ctx.chat_id, store, settings)
    if command == "brain":
        store.clear_ui_flow(ctx.chat_id)
        return _command_menu_text("brain", SECOND_LEVEL_COMMANDS["brain"])

    if text and not command:
        requested_mode = _parse_display_mode_selection(text)
        if requested_mode is not None:
            return _set_display_mode_response(ctx.chat_id, store, requested_mode)

    # Non-blocking rule: plain text should always reach the agent for content flows.
    # Keep numeric/text selection for settings flows (model/provider/project).
    active_flow = store.get_ui_flow(ctx.chat_id)
    if text and not command and isinstance(active_flow, dict):
        flow_kind = str(active_flow.get("kind") or "").strip()
        allowed_flow_kinds = {FLOW_AWAIT_MODEL, FLOW_AWAIT_PROVIDER, FLOW_AWAIT_PROJECT, FLOW_AWAIT_FILE_ACTION}
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
    if request.command in BRAIN_SLASH_ALIASES:
        return await _handle_brain_action(chat_id, BRAIN_SLASH_ALIASES[request.command], settings, store, agents)
    if request.command == "brain" or (request.command and request.command.startswith(BRAIN_COMMAND_PREFIX)):
        return await _handle_brain_action(chat_id, request.command, settings, store, agents)

    state = store.get_chat_state(chat_id)

    # Load user's locale preference
    i18n.set_locale(store.get_locale(chat_id))

    # Support inline project key callbacks (data is just "proj-xxxxxxxxxxxx").
    if request.command and request.command.startswith("proj-"):
        workspace = _resolve_project_selection(settings, request.command)
        if workspace is not None:
            next_state = store.set_project(chat_id, workspace.key, workspace.label, str(workspace.path))
            store.clear_ui_flow(chat_id)
            return (
                f"Project updated.\nproject: {_project_display(next_state['project_name'], next_state['project_path'])}\npath: {next_state['project_path']}\n\n"
                + i18n.tr("menu.model_select_hint")
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

    if request.command == "status_robot":
        lines = [
            "robot status",
            f"version: {VERSION}",
            f"commit: {_runtime_git_commit()}",
            f"display_mode: {state.get('display_mode') or DISPLAY_MODE_DEVELOPER}",
            f"code_display_mode: {state.get('code_display_mode') or CODE_DISPLAY_SMART}",
            f"provider: {state['provider']}",
            f"model: {state['model']}",
            f"project: {_project_display(state['project_name'], state['project_path'])}",
            f"thread_id: {state['thread_id'] or '-'}",
            f"queued_jobs: {len(store.get_agent_queue(chat_id))}",
            f"scheduled_jobs: {len(store.get_agent_schedules(chat_id))}",
        ]
        current = state.get("agent_current_run") if isinstance(state.get("agent_current_run"), dict) else None
        if current:
            lines.append(f"running: {current.get('goal') or '<resume>'} ({current.get('kind')})")
        last = state.get("agent_last_run") if isinstance(state.get("agent_last_run"), dict) else None
        if last:
            lines.append(f"last_run: {last.get('status') or '-'}")
        return "\n".join(lines)

    if request.command == "status_teleapp":
        try:
            teleapp_version = __import__("teleapp").__version__
        except Exception:
            teleapp_version = "unknown"
        try:
            from telegram import __version__ as tg_version
        except Exception:
            tg_version = "unknown"
        risk_mode = bool(settings.codex_bypass_approvals_and_sandbox or settings.codex_skip_git_repo_check)
        lines = [
            "teleapp status",
            f"teleapp_version: {teleapp_version}",
            f"telegram_bot_version: {tg_version}",
            f"ui_build: {UI_BUILD_TAG}",
            f"hosted_build: {HOSTED_BUILD_TAG}",
            f"security_risk_mode: {'on' if risk_mode else 'off'}",
        ]
        return "\n".join(lines)

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

    if request.command == "mail_send":
        return "Usage: /mailcli <sendmail-cli-args>"

    if request.command == "mail_list":
        return "mail commands:\n/mailcli <sendmail-cli-args>\n/mailjson <config.json>\n/mailbatch <recipients.csv> <base_config.json>\n/mailmcp"

    if request.command == "mail_contacts":
        return await handle_command(chat_id, ClassifiedRequest(COMMAND_REQUEST, "contact", "list", request.request_id), settings, store, agents)

    if request.command == "project_list":
        return _handle_project_command(chat_id, "list", settings, store)

    if request.command == "project_switch":
        payload = request.payload.strip()
        if not payload:
            return "Usage: /project_switch <name|key>"
        return _handle_project_command(chat_id, f"use {payload}", settings, store)

    if request.command == "compact_status":
        return "compact status\nworkflow: /compact\nscript: scripts/skills/compress_context.py"

    if request.command == "release_check":
        return "release check\nversion: {version}\ncommit: {commit}".format(version=VERSION, commit=_runtime_git_commit())

    if request.command == "dependencies_check":
        return build_doctor_report(settings)

    if request.command in {"provider_codex", "provider_claude", "provider_gemini"}:
        selected_provider = request.command.split("_", 1)[1]
        next_state = store.set_provider(chat_id, selected_provider)
        return f"Provider updated.\nprovider: {next_state['provider']}\nmodel: {next_state['model']}"

    if request.command == "provider":
        payload = request.payload.strip().lower()
        if not payload:
            return _provider_menu_response(chat_id, store)
        selected_provider = _resolve_provider_selection(payload)
        if selected_provider is None:
            return (
                f"Unknown provider selection: {payload}\n"
                "Use /provider to open the provider chooser, or /provider_codex /provider_claude /provider_gemini."
            )
        next_state = store.set_provider(chat_id, selected_provider)
        return f"Provider updated.\nprovider: {next_state['provider']}\nmodel: {next_state['model']}"

    if request.command == "models":
        provider = str(state["provider"])
        catalog = get_model_catalog(settings, provider)
        default_model = _default_model_name(provider, settings)
        lines = [
            f"Models for {provider}:",
            f"current: {state['model']}",
            f"source: {catalog.source}",
        ]
        if catalog.note:
            lines.append(f"note: {catalog.note}")
        lines.append("")
        for item in catalog.items:
            tags: list[str] = []
            if item.name == default_model:
                tags.append("default")
            if item.name == state["model"]:
                tags.append("current")
            marker = f" ({', '.join(tags)})" if tags else ""
            if item.description:
                lines.append(f"- {item.name}{marker}  {item.description}")
            else:
                lines.append(f"- {item.name}{marker}")
        if settings.custom_models:
            if catalog.items:
                lines.append("")
            lines.append("--- custom models ---")
            lines.extend(f"- {item}" for item in settings.custom_models)
        return "\n".join(lines)

    if request.command in {"mode", "display_mode"}:
        payload = request.payload.strip()
        if not payload:
            return _command_menu_text("display_mode", SECOND_LEVEL_COMMANDS["display_mode"])
        requested_mode = _parse_display_mode_selection(payload)
        if requested_mode is None:
            return "Unknown mode selection.\nUse /display_mode_user or /display_mode_dev."
        return _set_display_mode_response(chat_id, store, requested_mode)

    if request.command == "display":
        payload = request.payload.strip()
        if not payload:
            return _code_display_usage(store, chat_id)
        return _set_code_display_mode_response(chat_id, store, payload)

    if request.command == "display_mode_user":
        return _set_display_mode_response(chat_id, store, DISPLAY_MODE_USER)

    if request.command == "display_mode_dev":
        return _set_display_mode_response(chat_id, store, DISPLAY_MODE_DEVELOPER)

    if request.command in {"display_normal", "display_smart", "display_copy_code"}:
        mode = request.command.split("_", 1)[1]
        if mode == "copy_code":
            mode = "all"
        return _set_code_display_mode_response(chat_id, store, mode)

    if request.command in {"usermode", "devmode", "developermode"}:
        perm = DISPLAY_MODE_USER if request.command == "usermode" else DISPLAY_MODE_DEVELOPER
        store.set_display_mode(chat_id, perm)
        store.set_permission_mode(chat_id, perm)
        return _set_display_mode_response(chat_id, store, perm)

    if request.command in {"lang_zh", "lang_en", "lang_ja", "lang_ko", "lang_zhcn", "lang_zhhk"}:
        locale_map = {"lang_zh": "zh", "lang_en": "en", "lang_ja": "ja", "lang_ko": "ko", "lang_zhcn": "zh-cn", "lang_zhhk": "zh-hk"}
        locale = locale_map[request.command]
        supported = {"zh": "繁體中文", "zh-cn": "簡體中文", "zh-hk": "繁體（香港）", "en": "English", "ja": "日本語", "ko": "한국어"}
        store.set_locale(chat_id, locale)
        i18n.set_locale(locale)
        configure_templates_for_locale(locale)
        return i18n.tr("menu.lang_switched", name=supported[locale])

    if request.command == "lang":
        payload = request.payload.strip()
        supported = {"zh", "zh-cn", "zh-hk", "en", "ja", "ko"}
        names = {"zh": "繁體中文", "zh-cn": "簡體中文", "zh-hk": "繁體（香港）", "en": "English", "ja": "日本語", "ko": "한국語"}
        if not payload:
            current = store.get_locale(chat_id)
            lines = [i18n.tr("menu.lang_current", name=names.get(current, current))]
            lines.append("")
            lines.append(i18n.tr("menu.lang_available"))
            for lc in sorted(supported):
                marker = " ✅" if lc == current else ""
                cmd = "lang_" + lc.replace("-", "")  # lang_zhcn, lang_zhhk
                lines.append(f"  /{cmd} → {names[lc]}{marker}")
            return "\n".join(lines)
        if payload not in supported:
            return i18n.tr("menu.lang_unsupported", payload=payload, list=", ".join(sorted(supported)))
        store.set_locale(chat_id, payload)
        i18n.set_locale(payload)
        configure_templates_for_locale(payload)
        return i18n.tr("menu.lang_switched", name=names[payload])

    if request.command == "model":
        payload = request.payload.strip()
        if not payload:
            return _model_menu_response(chat_id, store, settings)
        selected_model = _resolve_model_selection(str(state["provider"]), payload, settings)
        if selected_model is None:
            return (
                f"Unknown model selection: {payload}\n"
                "Use /model to open the model chooser, or /models to list available models."
            )
        _is_catalog_model, validation_error = validate_selected_model(settings, str(state["provider"]), selected_model)
        if validation_error:
            return validation_error
        next_state = store.set_model(chat_id, selected_model)
        return f"Model updated.\nprovider: {next_state['provider']}\nmodel: {next_state['model']}"

    if request.command in {"model_codex", "model_claude", "model_gemini"}:
        provider = request.command.split("_", 1)[1]
        catalog = get_model_catalog(settings, provider)
        default_model = _default_model_name(provider, settings)
        current_model = str(state["model"]) if state["provider"] == provider else None
        lines = [
            f"Models for {provider}:",
            f"current: {current_model or '-'}",
            f"default: {default_model}",
            "",
        ]
        for item in catalog.items:
            marker = " ←" if item.name == current_model else (" (default)" if item.name == default_model else "")
            desc = f"  {item.description}" if item.description else ""
            lines.append(f"- {item.name}{marker}{desc}")
        if settings.custom_models:
            lines.append("")
            lines.append("--- custom models ---")
            lines.extend(f"- {item}" for item in settings.custom_models)
        return "\n".join(lines)


    if request.command in {"project", "projects"}:
        return _handle_project_command(chat_id, request.payload, settings, store)

    if request.command == "queue":
        return agents.queue_overview(chat_id)

    if request.command == "schedules":
        return agents.schedule_overview(chat_id)

    if request.command == "cron":
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
        return body if body else i18n.tr("menu.daily_note_empty")

    if request.command == "braininbox":
        payload = request.payload.strip()
        if not payload:
            return "Usage: /braininbox <text>"
        path = create_inbox_note(settings, payload)
        return i18n.tr("menu.inbox_created", path=path)

    if request.command == "brainweb":
        payload = request.payload.strip()
        if not payload:
            return "Usage: /brainweb <url>"
        try:
            path, title, excerpt, summary_points, tags = capture_web_to_daily(settings, payload, max_chars=2500)
        except ValueError as exc:
            return i18n.tr("errors.url_format_error", exc=exc)
        except OSError as exc:
            return i18n.tr("errors.fetch_failed", exc=exc)
        summary_lines = "\n".join(f"- {item}" for item in summary_points[:3]) if summary_points else "- (none)"
        tags_line = ", ".join(tags) if tags else "(none)"
        preview = excerpt[:300].rstrip()
        if len(excerpt) > 300:
            preview += "..."
        return (
            i18n.tr("menu.web_capture_done", path=path) + "\n"
            + f"title: {title}\n"
            + f"tags: {tags_line}\n\n"
            + i18n.tr("menu.web_summary") + "\n"
            + f"{summary_lines}\n\n"
            + f"{preview}"
        )

    if request.command == "brainsearch":
        payload = request.payload.strip()
        if not payload:
            return "Usage: /brainsearch <query>"
        matches = search_vault(settings, payload, limit=10)
        if not matches:
            return i18n.tr("brain.no_results", text=payload)
        store.set_ui_flow(chat_id, {"kind": FLOW_BRAIN_SEARCH_RESULTS, "results": matches[:10]})
        return ButtonResponse(
            i18n.tr("brain.search_results_header", text=payload),
            buttons=[Button(item, f"brain:open_note:{idx}") for idx, item in enumerate(matches[:10])],
        )

    if request.command == "brainorganize":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_ORGANIZE_TEXT})
        return i18n.tr("organize.enter_source_text")

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
            return i18n.tr("menu.no_auto_batch")
        by_type = summary.get("by_type")
        items = summary.get("items")
        if not isinstance(by_type, dict):
            by_type = {}
        if not isinstance(items, list):
            items = []
        lines = [
            i18n.tr("menu.auto_batch_complete", limit=bounded_limit),
            f"- processed: {processed}",
            f"- created: {int(summary.get('created') or 0)}",
            f"- skipped: {int(summary.get('skipped') or 0)}",
            f"- failed: {int(summary.get('failed') or 0)}",
            "",
            i18n.tr("menu.batch_stats"),
            f"- project: {int(by_type.get('project') or 0)}",
            f"- knowledge: {int(by_type.get('knowledge') or 0)}",
            f"- resource: {int(by_type.get('resource') or 0)}",
        ]
        created_items = [item for item in items if isinstance(item, dict) and item.get("status") == "created"]
        if created_items:
            lines.append("")
            lines.append(i18n.tr("brain_schedule.new_note_title"))
            for item in created_items[:10]:
                lines.append(f"- {item.get('source_path')} -> {item.get('path')} ({item.get('target')})")
        failed_items = [item for item in items if isinstance(item, dict) and item.get("status") == "failed"]
        if failed_items:
            lines.append("")
            lines.append(i18n.tr("errors.fail_items"))
            for item in failed_items[:5]:
                lines.append(f"- {item.get('source_path')}: {item.get('error') or 'unknown error'}")
        return "\n".join(lines)

    if request.command == "brainproject":
        payload = request.payload.strip()
        if not payload:
            return "Usage: /brainproject <title>"
        path = create_project_note(settings, payload)
        return i18n.tr("menu.project_note_created", path=path)

    if request.command == "brainknowledge":
        payload = request.payload.strip()
        if not payload:
            return "Usage: /brainknowledge <title>"
        path = create_knowledge_note(settings, payload)
        return i18n.tr("menu.knowledge_note_created", path=path)

    if request.command == "brainresource":
        payload = request.payload.strip()
        if not payload:
            return "Usage: /brainresource <title>"
        path = create_resource_note(settings, payload)
        return i18n.tr("menu.resource_note_created", path=path)

    if request.command == "brainschedule":
        payload = request.payload.strip()
        if not payload:
            store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_SCHEDULE_TITLE})
            return i18n.tr("menu.schedule_prompt")
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
        return i18n.tr("menu.schedule_title_remembered", title=payload)

    if request.command == "braindecide":
        payload = request.payload.strip()
        if not payload:
            return "Usage: /braindecide <question>"
        related_paths, brief = build_decision_support_brief(settings, payload, limit=5)
        path = create_decision_note_from_brief(settings, payload, brief, related_notes=related_paths)
        return f"{brief}\n\n已建立決策支援筆記：{path}"

    if request.command == "brainsummary":
        path = ensure_weekly_summary_note(settings)
        return i18n.tr("menu.weekly_summary_done", path=path)

    if request.command == "brainremind":
        reminders = collect_brain_reminders(settings, limit=5)
        return i18n.tr("menu.reminders_label") + "\n" + "\n".join(reminders)

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
        display_mode = str(state.get("display_mode") or DISPLAY_MODE_DEVELOPER)
        project_display = _project_display(state["project_name"], state["project_path"])
        queue_waiting = max(0, int(position) - 1)
        if started:
            return _status_event(
                chat_id,
                format_run_started(
                    display_mode,
                    kind="provider",
                    goal=goal,
                    project=project_display,
                    path=str(state["project_path"]),
                    queue_waiting=queue_waiting,
                    elapsed="00:00",
                ),
                status_key=status_key,
                request_id=request.request_id,
                typing="active",
            )
        queued_text = format_run_queued(
            display_mode,
            kind="provider",
            goal=goal,
            project=project_display,
            path=str(state["project_path"]),
            position=int(position),
            elapsed="00:00",
        )
        if normalize_display_mode(display_mode) == DISPLAY_MODE_USER:
            return _status_event(
                chat_id,
                queued_text,
                status_key=status_key,
                request_id=request.request_id,
                typing="active",
            )
        return queued_text
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
        display_mode = str(state.get("display_mode") or DISPLAY_MODE_DEVELOPER)
        project_display = _project_display(state["project_name"], state["project_path"])
        queue_waiting = max(0, int(position) - 1)
        if started:
            return _status_event(
                chat_id,
                format_run_started(
                    display_mode,
                    kind="auto_dev",
                    goal=str(options.goal),
                    project=project_display,
                    path=str(state["project_path"]),
                    queue_waiting=queue_waiting,
                    elapsed="00:00",
                ),
                status_key=status_key,
                request_id=request.request_id,
                typing="active",
            )
        queued_text = format_run_queued(
            display_mode,
            kind="auto_dev",
            goal=str(options.goal),
            project=project_display,
            path=str(state["project_path"]),
            position=int(position),
            elapsed="00:00",
        )
        if normalize_display_mode(display_mode) == DISPLAY_MODE_USER:
            return _status_event(
                chat_id,
                queued_text,
                status_key=status_key,
                request_id=request.request_id,
                typing="active",
            )
        return queued_text
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
        display_mode = str(state.get("display_mode") or DISPLAY_MODE_DEVELOPER)
        project_display = _project_display(state["project_name"], state["project_path"])
        queue_waiting = max(0, int(position) - 1)
        if started:
            return _status_event(
                chat_id,
                format_run_started(
                    display_mode,
                    kind="auto_dev",
                    goal="<resume>",
                    project=project_display,
                    path=str(state["project_path"]),
                    queue_waiting=queue_waiting,
                    elapsed="00:00",
                ),
                status_key=status_key,
                request_id=request.request_id,
                typing="active",
            )
        queued_text = format_run_queued(
            display_mode,
            kind="auto_dev",
            goal="<resume>",
            project=project_display,
            path=str(state["project_path"]),
            position=int(position),
            elapsed="00:00",
        )
        if normalize_display_mode(display_mode) == DISPLAY_MODE_USER:
            return _status_event(
                chat_id,
                queued_text,
                status_key=status_key,
                request_id=request.request_id,
                typing="active",
            )
        return queued_text
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
        return i18n.tr("errors.blank_message")
    status_key = heartbeat_status_key(request.request_id)
    _job_id, position, started = agents.enqueue(
        chat_id,
        prompt,
        source="message",
        request_id=request.request_id,
        status_key=status_key,
    )
    state = store.get_chat_state(chat_id)
    display_mode = str(state.get("display_mode") or DISPLAY_MODE_DEVELOPER)
    project_display = _project_display(state["project_name"], state["project_path"])
    queue_waiting = max(0, int(position) - 1)
    if started:
        return _status_event(
            chat_id,
            format_run_started(
                display_mode,
                kind="provider",
                goal=prompt,
                project=project_display,
                path=str(state["project_path"]),
                queue_waiting=queue_waiting,
                elapsed="00:00",
            ),
            status_key=status_key,
            request_id=request.request_id,
            typing="active",
        )
    queued_text = format_run_queued(
        display_mode,
        kind="provider",
        goal=prompt,
        project=project_display,
        path=str(state["project_path"]),
        position=int(position),
        elapsed="00:00",
    )
    if normalize_display_mode(display_mode) == DISPLAY_MODE_USER:
        return _status_event(
            chat_id,
            queued_text,
            status_key=status_key,
            request_id=request.request_id,
            typing="active",
        )
    return queued_text
