from __future__ import annotations

import argparse
import shlex
from dataclasses import dataclass
from datetime import datetime

from teleapp import Button, ButtonResponse
from teleapp.context import MessageContext

from robot.agents import AgentCoordinator
from robot.brain import (
    append_to_daily,
    build_decision_support_brief,
    create_decision_note,
    create_decision_note_from_brief,
    create_inbox_note,
    create_knowledge_note,
    create_knowledge_note_from_text,
    create_project_note,
    create_project_note_from_text,
    create_resource_note,
    create_resource_note_from_text,
    ensure_weekly_summary_note,
    list_recent_notes,
    read_daily,
    read_note,
    search_vault,
)
from robot.config import MODEL_CHOICES, MODEL_DESCRIPTIONS, PROVIDER_LABELS, SUPPORTED_MODELS, Settings, VERSION
from robot.diagnostics import build_doctor_report
from robot.projects import discover_project_workspaces, find_workspace
from robot.state import ChatStateStore

COMMAND_REQUEST = "command"
CONTROL_REQUEST = "control"
AGENT_REQUEST = "agent"

COMMAND_NAMES = {
    "start",
    "help",
    "about",
    "status",
    "doctor",
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
    "brainsearch",
    "braindecide",
    "brainsummary",
    "brainproject",
    "brainknowledge",
    "brainresource",
    "brainorganize",
    "brainbatch",
}

CONTROL_NAMES = {
    "reset",
    "newthread",
    "restart",
    "clearqueue",
    "clearschedules",
    "run",
    "agent",
    "agentresume",
    "schedule",
}

COMMON_CONTROL_PHRASES = {
    "continue": "continue",
    "continue?": "continue",
    "go on": "continue",
    "next": "next",
    "next step": "next",
    "stop": "stop",
    "restart": "restart_hint",
    "start over": "restart_hint",
    "繼續": "continue",
    "繼續嗎": "continue",
    "??": "continue",
    "???": "continue",
    "下一步": "next",
    "停止": "stop",
    "停": "stop",
    "重來": "restart_hint",
    "重?": "restart_hint",
    "重新開始": "restart_hint",
    "重新?始": "restart_hint",
}

MENU_TRIGGERS = {"menu", "選單"}
MODEL_TRIGGERS = {"model", "模型"}
BRAIN_TRIGGERS = {"brain", "第二大腦", "筆記"}
MENU_COMMAND_PREFIX = "menu:"
BRAIN_COMMAND_PREFIX = "brain:"
FLOW_AWAIT_MODEL = "await_model"
FLOW_AWAIT_PROVIDER = "await_provider"
FLOW_AWAIT_PROJECT = "await_project"
FLOW_AWAIT_MENU_ACTION = "await_menu_action"
FLOW_AWAIT_BRAIN_ACTION = "await_brain_action"
FLOW_AWAIT_BRAIN_CAPTURE = "await_brain_capture"
FLOW_AWAIT_BRAIN_INBOX = "await_brain_inbox"
FLOW_AWAIT_BRAIN_SEARCH = "await_brain_search"
FLOW_AWAIT_BRAIN_DECIDE = "await_brain_decide"
FLOW_AWAIT_BRAIN_PROJECT = "await_brain_project"
FLOW_AWAIT_BRAIN_KNOWLEDGE = "await_brain_knowledge"
FLOW_AWAIT_BRAIN_RESOURCE = "await_brain_resource"
FLOW_AWAIT_BRAIN_ORGANIZE_TEXT = "await_brain_organize_text"
FLOW_AWAIT_BRAIN_ORGANIZE_TARGET = "await_brain_organize_target"
FLOW_AWAIT_BRAIN_ORGANIZE_TITLE = "await_brain_organize_title"
FLOW_BRAIN_SEARCH_RESULTS = "brain_search_results"
FLOW_BRAIN_BATCH_RESULTS = "brain_batch_results"


@dataclass(slots=True)
class ClassifiedRequest:
    kind: str
    command: str | None
    payload: str


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


def _build_agent_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--profile")
    parser.add_argument("--config")
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--pr", action="store_true")
    parser.add_argument("--no-post-run", action="store_true")
    parser.add_argument("goal", nargs=argparse.REMAINDER)
    return parser


def _build_resume_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("resume", nargs="?")
    parser.add_argument("--profile")
    parser.add_argument("--config")
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--pr", action="store_true")
    parser.add_argument("--no-post-run", action="store_true")
    return parser


def _build_schedule_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
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
    except SystemExit:
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
    except SystemExit:
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
    except SystemExit:
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
        return ClassifiedRequest(COMMAND_REQUEST, command, "")
    if command == "brain" or (command and command.startswith(BRAIN_COMMAND_PREFIX)):
        return ClassifiedRequest(COMMAND_REQUEST, command, "")

    lowered = text.lower()
    phrase_control = COMMON_CONTROL_PHRASES.get(lowered) or COMMON_CONTROL_PHRASES.get(text)
    if phrase_control is not None:
        return ClassifiedRequest(CONTROL_REQUEST, phrase_control, text)
    if command in COMMAND_NAMES:
        return ClassifiedRequest(COMMAND_REQUEST, command, _command_payload(text))
    if command in CONTROL_NAMES:
        return ClassifiedRequest(CONTROL_REQUEST, command, _command_payload(text))
    if text.startswith("/"):
        return ClassifiedRequest(COMMAND_REQUEST, command, _command_payload(text))
    return ClassifiedRequest(AGENT_REQUEST, None, text)


def _status_text(chat_id: int, store: ChatStateStore) -> str:
    state = store.get_chat_state(chat_id)
    current_run = state["agent_current_run"] if isinstance(state["agent_current_run"], dict) else {}
    last_run = state["agent_last_run"] if isinstance(state["agent_last_run"], dict) else {}
    return "\n".join(
        [
            "robot status",
            f"version: {VERSION}",
            f"provider: {state['provider']}",
            f"model: {state['model']}",
            f"project: {state['project_name']}",
            f"path: {state['project_path']}",
            f"thread_id: {state['thread_id'] or '-'}",
            f"current_run: {current_run.get('job_id', '-')}",
            f"last_run: {last_run.get('job_id', '-')}",
            "",
            "request classes:",
            "- command request: /provider /model /project /status /doctor /queue /schedules /agentstatus /agentprofiles",
            "- control request: /reset /newthread /restart /run /agent /agentresume /schedule",
            "- agent request: plain text (provider runner)",
        ]
    )


def _help_text() -> str:
    return "\n".join(
        [
            "robot",
            "",
            "deterministic commands:",
            "/provider [codex|gemini|copilot]",
            "/model [name]",
            "/models",
            "/projects",
            "/project [key-or-label]",
            "/status",
            "/doctor",
            "/queue",
            "/schedules",
            "/agentstatus",
            "/agentprofiles [--config PATH]",
            "/menu",
            "/brain",
            "/brainread",
            "/braininbox <text>",
            "/brainsearch <query>",
            "/brainorganize",
            "/brainbatch",
            "/brainproject <title>",
            "/brainknowledge <title>",
            "/brainresource <title>",
            "/braindecide <question>",
            "/brainsummary",
            "",
            "control commands:",
            "/reset",
            "/newthread",
            "/restart",
            "/clearqueue",
            "/clearschedules",
            "/run <goal>",
            "/agent [--profile NAME] [--config PATH] [--commit] [--push] [--pr] [--no-post-run] <goal>",
            "/agentresume [run_id_or_path] [--profile NAME] [--config PATH] [--commit] [--push] [--pr] [--no-post-run]",
            "/schedule YYYY-MM-DD HH:MM [--profile NAME] [--config PATH] [--commit] [--push] [--pr] [--no-post-run] <goal>",
            "",
            "agent requests:",
            "- normal text message (provider runner)",
            "",
            "common low-token control phrases:",
            "- continue / next / stop / restart",
            "- 繼續 / 下一步 / 停止 / 重來",
        ]
    )


def _menu_text(chat_id: int, store: ChatStateStore) -> str:
    state = store.get_chat_state(chat_id)
    return "\n".join(
        [
            "robot menu",
            f"provider: {state['provider']}",
            f"model: {state['model']}",
            f"project: {state['project_name']}",
            "",
            "文字操作:",
            "- status",
            "- provider",
            "- model",
            "- projects",
            "- cancel",
            "",
            "也可直接用斜線指令:",
            "- /status",
            "- /provider codex",
            "- /model gpt-5.4",
            "- /project <key-or-label>",
            "",
            "其他自然語言訊息不會被選單吃掉，會直接送進 AI。",
        ]
    )


def _brain_text() -> str:
    return "\n".join(
        [
            "brain menu",
            "使用 TG 操作 secondbrain",
            "",
            "可用功能：",
            "- 寫入今日",
            "- Inbox",
            "- 讀今日",
            "- 搜尋",
            "- 整理",
            "- 批次整理",
            "- 專案",
            "- 知識卡",
            "- Resource",
            "- 每週摘要",
            "- 決策支援",
        ]
    )


def _brain_menu_response(chat_id: int, store: ChatStateStore) -> ButtonResponse:
    store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_ACTION})
    return ButtonResponse(
        _brain_text(),
        buttons=[
            Button("寫入今日", "brain:capture"),
            Button("Inbox", "brain:inbox"),
            Button("讀今日", "brain:read"),
            Button("搜尋", "brain:search"),
            Button("整理", "brain:organize"),
            Button("批次整理", "brain:batch"),
            Button("專案", "brain:project"),
            Button("知識卡", "brain:knowledge"),
            Button("Resource", "brain:resource"),
            Button("每週摘要", "brain:summary"),
            Button("決策支援", "brain:decide"),
            Button("Cancel", "brain:cancel"),
        ],
    )


async def _handle_brain_action(chat_id: int, command: str, settings: Settings, store: ChatStateStore):
    if command in {"brain", "brain:open"}:
        return _brain_menu_response(chat_id, store)

    if command == "brain:cancel":
        store.clear_ui_flow(chat_id)
        return "Brain menu canceled."

    if command == "brain:capture":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_CAPTURE})
        return "請輸入要寫入今日 daily note 的內容。輸入 cancel 可離開。"

    if command == "brain:inbox":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_INBOX})
        return "請輸入要存進 Inbox 的內容。輸入 cancel 可離開。"

    if command == "brain:read":
        body = read_daily(settings).strip()
        return body if body else "今日 daily note 目前是空的。"

    if command == "brain:search":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_SEARCH})
        return "請輸入要搜尋 secondbrain 的關鍵字。輸入 cancel 可離開。"

    if command == "brain:organize":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_ORGANIZE_TEXT})
        return "請先貼上你要整理的原始內容。輸入 cancel 可離開。"

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

    if command == "brain:project":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_PROJECT})
        return "請輸入專案名稱，我會建立 project note。輸入 cancel 可離開。"

    if command == "brain:knowledge":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_KNOWLEDGE})
        return "請輸入知識卡標題，我會建立 knowledge note。輸入 cancel 可離開。"

    if command == "brain:resource":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_RESOURCE})
        return "請輸入 resource 標題，我會建立 resource note。輸入 cancel 可離開。"

    if command == "brain:summary":
        path = ensure_weekly_summary_note(settings)
        body = read_note(settings, path).strip()
        return f"已準備每週摘要筆記：{path}\n\n{body}"

    if command == "brain:decide":
        store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_BRAIN_DECIDE})
        return "請輸入你要整理的判斷問題。輸入 cancel 可離開。"

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
            "resource": "Resource",
        }
        return f"請輸入整理後的{labels[target]}標題。輸入 cancel 可離開。"

    return f"Unknown brain action: {command}"


def _main_menu_response(chat_id: int, store: ChatStateStore) -> ButtonResponse:
    store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_MENU_ACTION})
    return ButtonResponse(
        _menu_text(chat_id, store),
        buttons=[
            Button("Status", "menu:status"),
            Button("Provider", "menu:provider"),
            Button("Model", "menu:model"),
            Button("Projects", "menu:projects"),
            Button("Cancel", "menu:cancel"),
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
            "可直接輸入編號或 provider 名稱，或用 /provider <name>。",
            "輸入 menu 返回主選單，輸入 cancel 離開。",
            "其他自然語言會直接送進 AI。",
        ]
    )
    return "\n".join(lines)


def _model_menu_response(chat_id: int, store: ChatStateStore) -> ButtonResponse:
    state = store.get_chat_state(chat_id)
    provider = str(state["provider"])
    models = SUPPORTED_MODELS.get(provider, [])
    choices = MODEL_CHOICES.get(provider, [(item, item) for item in models])
    default_model = models[0] if models else ""
    descriptions = MODEL_DESCRIPTIONS.get(provider, {})
    store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_MODEL})
    lines = [
        "Select Model",
        f"provider: {provider}",
        "",
        "按按鈕直接切換。",
        "",
    ]
    buttons: list[Button] = []
    for index, (item, label) in enumerate(choices[:8], start=1):
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
            "輸入 cancel 離開。",
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
    if normalized.startswith(("gpt-", "o", "claude-", "gemini-")):
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


def _projects_menu_response(chat_id: int, settings: Settings, store: ChatStateStore) -> str:
    state = store.get_chat_state(chat_id)
    workspaces = discover_project_workspaces(settings)
    store.set_ui_flow(chat_id, {"kind": FLOW_AWAIT_PROJECT})
    lines = [f"Current project: {state['project_name']}", "", "Available projects:"]
    for index, workspace in enumerate(workspaces, start=1):
        lines.append(f"{index}. {workspace.label} | {workspace.key}")
    lines.extend(
        [
            "",
            "可直接輸入編號、project key 或 label，或用 /project <key-or-label>。",
            "輸入 menu 返回主選單，輸入 cancel 離開。",
            "其他自然語言會直接送進 AI。",
        ]
    )
    return "\n".join(lines) if workspaces else "No projects discovered."


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
        return _status_text(chat_id, store)

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
            "輸入 menu 可回到主選單，或直接輸入自然語言交給 AI。"
        )

    if command == "menu:model":
        return _model_menu_response(chat_id, store)

    if command.startswith("menu:set_model:"):
        model = command.split(":", 2)[2].strip()
        if not model:
            return "Empty model name."
        next_state = store.set_model(chat_id, model)
        store.clear_ui_flow(chat_id)
        return (
            f"Model updated.\nprovider: {next_state['provider']}\nmodel: {next_state['model']}\n\n"
            "輸入 menu 可回到主選單，或直接輸入自然語言交給 AI。"
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

    if text.lower() in {"cancel", "取消"}:
        store.clear_ui_flow(chat_id)
        return "Menu input canceled."

    if kind == FLOW_AWAIT_MODEL:
        normalized = text.strip()
        if normalized.lower() in {"menu", "選單", "back", "返回"}:
            return await _handle_menu_action(chat_id, "menu:open", settings, store, agents)
        return "請直接按 model 按鈕切換，或用 /model <name>。輸入 cancel 可離開。"

    if kind == FLOW_AWAIT_PROVIDER:
        normalized = text.strip().lower()
        if normalized in {"menu", "選單", "back", "返回"}:
            return await _handle_menu_action(chat_id, "menu:open", settings, store, agents)
        selected_provider = _resolve_provider_selection(text)
        if selected_provider is not None:
            return await _handle_menu_action(chat_id, f"menu:set_provider:{selected_provider}", settings, store, agents)
        return None

    if kind == FLOW_AWAIT_PROJECT:
        normalized = text.strip()
        lowered = normalized.lower()
        if lowered in {"menu", "選單", "back", "返回"}:
            return await _handle_menu_action(chat_id, "menu:open", settings, store, agents)
        workspace = _resolve_project_selection(settings, normalized)
        if workspace is not None:
            next_state = store.set_project(chat_id, workspace.key, workspace.label, str(workspace.path))
            store.clear_ui_flow(chat_id)
            return (
                f"Project updated.\nproject: {next_state['project_name']}\npath: {next_state['project_path']}\n\n"
                "輸入 menu 可回到主選單，或直接輸入自然語言交給 AI。"
            )
        return None

    if kind == FLOW_AWAIT_MENU_ACTION:
        normalized = text.strip().lower()
        if normalized in {"status", "狀態"}:
            return await _handle_menu_action(chat_id, "menu:status", settings, store, agents)
        if normalized in {"provider", "供應商"}:
            return await _handle_menu_action(chat_id, "menu:provider", settings, store, agents)
        if normalized in {"model", "模型"}:
            return await _handle_menu_action(chat_id, "menu:model", settings, store, agents)
        if normalized in {"projects", "project", "專案"}:
            return await _handle_menu_action(chat_id, "menu:projects", settings, store, agents)
        if normalized in {"menu", "選單"}:
            return await _handle_menu_action(chat_id, "menu:open", settings, store, agents)
        return None

    if kind == FLOW_AWAIT_BRAIN_ACTION:
        normalized = text.strip().lower()
        if normalized in {"寫入今日", "capture"}:
            return await _handle_brain_action(chat_id, "brain:capture", settings, store)
        if normalized in {"inbox"}:
            return await _handle_brain_action(chat_id, "brain:inbox", settings, store)
        if normalized in {"讀今日", "read"}:
            return await _handle_brain_action(chat_id, "brain:read", settings, store)
        if normalized in {"搜尋", "search"}:
            return await _handle_brain_action(chat_id, "brain:search", settings, store)
        if normalized in {"整理", "organize"}:
            return await _handle_brain_action(chat_id, "brain:organize", settings, store)
        if normalized in {"批次整理", "batch"}:
            return await _handle_brain_action(chat_id, "brain:batch", settings, store)
        if normalized in {"專案", "project"}:
            return await _handle_brain_action(chat_id, "brain:project", settings, store)
        if normalized in {"知識卡", "knowledge"}:
            return await _handle_brain_action(chat_id, "brain:knowledge", settings, store)
        if normalized in {"resource"}:
            return await _handle_brain_action(chat_id, "brain:resource", settings, store)
        if normalized in {"每週摘要", "summary"}:
            return await _handle_brain_action(chat_id, "brain:summary", settings, store)
        if normalized in {"決策支援", "decide"}:
            return await _handle_brain_action(chat_id, "brain:decide", settings, store)
        if normalized in {"brain", "第二大腦", "筆記"}:
            return await _handle_brain_action(chat_id, "brain:open", settings, store)
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
    if text in MENU_TRIGGERS or text.lower() in MENU_TRIGGERS:
        store.clear_ui_flow(ctx.chat_id)
        return _main_menu_response(ctx.chat_id, store)
    if text in MODEL_TRIGGERS or text.lower() in MODEL_TRIGGERS:
        return _model_menu_response(ctx.chat_id, store)
    if text in BRAIN_TRIGGERS or text.lower() in BRAIN_TRIGGERS:
        store.clear_ui_flow(ctx.chat_id)
        return _brain_menu_response(ctx.chat_id, store)

    flow_response = await _handle_flow_input(ctx.chat_id, ctx, settings, store, agents)
    if flow_response is not None:
        return flow_response

    request = classify_request(ctx)
    if request.kind == COMMAND_REQUEST:
        return await handle_command(ctx.chat_id, request, settings, store, agents)
    if request.kind == CONTROL_REQUEST:
        return await handle_control(ctx.chat_id, request, store, agents)
    return await handle_agent(ctx.chat_id, request, agents)


async def handle_command(chat_id: int, request: ClassifiedRequest, settings: Settings, store: ChatStateStore, agents: AgentCoordinator) -> str:
    if request.command == "menu" or (request.command and request.command.startswith(MENU_COMMAND_PREFIX)):
        return await _handle_menu_action(chat_id, request.command, settings, store, agents)
    if request.command == "brain" or (request.command and request.command.startswith(BRAIN_COMMAND_PREFIX)):
        return await _handle_brain_action(chat_id, request.command, settings, store)

    state = store.get_chat_state(chat_id)

    if request.command in {"start", "help"}:
        return _help_text()

    if request.command == "about":
        return "robot\nteleapp-based Telegram task router\nOnly agent requests are sent to providers."

    if request.command == "status":
        return _status_text(chat_id, store)

    if request.command == "doctor":
        return build_doctor_report(settings)

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
        return "\n".join(lines)

    if request.command == "model":
        payload = request.payload.strip()
        if not payload:
            return _model_menu_response(chat_id, store)
        selected_model = _resolve_model_selection(str(state["provider"]), payload)
        if selected_model is None:
            return (
                f"Unknown model selection: {payload}\n"
                "Use /model to open the model chooser, or /models to list available models."
            )
        next_state = store.set_model(chat_id, selected_model)
        return f"Model updated.\nprovider: {next_state['provider']}\nmodel: {next_state['model']}"

    if request.command == "projects":
        workspaces = discover_project_workspaces(settings)
        lines = ["Available projects:"]
        for workspace in workspaces:
            lines.append(f"- {workspace.label} | {workspace.key}")
        return "\n".join(lines) if workspaces else "No projects discovered."

    if request.command == "project":
        payload = request.payload.strip()
        if not payload:
            return _projects_menu_response(chat_id, settings, store)
        workspace = _resolve_project_selection(settings, payload)
        if workspace is None:
            return (
                f"Project not found: {payload}\n"
                "Use /project to open the project chooser, or /projects to list available workspaces."
            )
        next_state = store.set_project(chat_id, workspace.key, workspace.label, str(workspace.path))
        return f"Project updated.\nproject: {next_state['project_name']}\npath: {next_state['project_path']}"

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
                    f"job: {current.get('job_id')}",
                    f"kind: {current.get('kind')}",
                    f"goal: {current.get('goal') or '<resume>'}",
                    f"run_id: {current.get('run_id') or '-'}",
                ]
            )
        queue = store.get_agent_queue(chat_id)
        if queue:
            next_job = queue[0]
            return "\n".join(
                [
                    "agent status",
                    "state: queued",
                    f"next_job: {next_job.get('job_id')}",
                    f"kind: {next_job.get('kind')}",
                    f"goal: {next_job.get('goal') or '<resume>'}",
                    f"run_id: {next_job.get('run_id') or '-'}",
                ]
            )
        last = state.get("agent_last_run") if isinstance(state.get("agent_last_run"), dict) else None
        if last:
            return "\n".join(
                [
                    "agent status",
                    "state: idle",
                    f"last_status: {last.get('status')}",
                    f"last_job: {last.get('job_id')}",
                    f"last_kind: {last.get('kind')}",
                    f"last_run_id: {last.get('run_id') or '-'}",
                    f"elapsed_seconds: {last.get('elapsed_seconds')}",
                ]
            )
        return "agent status\nstate: idle\nno current or historical run."

    if request.command == "agentprofiles":
        payload = request.payload.strip()
        config_path = None
        if payload:
            parser = argparse.ArgumentParser(add_help=False)
            parser.add_argument("--config")
            try:
                parsed = parser.parse_args(_split_payload(payload))
                config_path = parsed.config
            except SystemExit:
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
        return "請先貼上你要整理的原始內容。輸入 cancel 可離開。"

    if request.command == "brainbatch":
        return await _handle_brain_action(chat_id, "brain:batch", settings, store)

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

    return f"Unknown command: /{request.command}\nUse /help."


async def handle_control(chat_id: int, request: ClassifiedRequest, store: ChatStateStore, agents: AgentCoordinator) -> str:
    if request.command in {"reset", "newthread"}:
        store.clear_thread_id(chat_id)
        return "Thread state cleared for the current provider."
    if request.command == "restart":
        return "Restart is managed by teleapp supervisor. Use Telegram command /restart."
    if request.command == "clearqueue":
        agents.clear_queue(chat_id)
        return "Queued agent jobs cleared."
    if request.command == "clearschedules":
        agents.clear_schedules(chat_id)
        return "Scheduled agent jobs cleared."
    if request.command in {"continue", "next"}:
        current = store.get_chat_state(chat_id).get("agent_current_run")
        if isinstance(current, dict):
            return f"An agent run is already active.\njob: {current.get('job_id')}\ngoal: {current.get('goal') or '<resume>'}"
        queue = store.get_agent_queue(chat_id)
        if queue:
            next_job = queue[0]
            return f"Next queued job:\n{next_job.get('goal') or '<resume>'}\nproject: {next_job.get('project_name')}"
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
        job_id, position, started = agents.enqueue(chat_id, goal, source=request.command)
        if started:
            return f"Provider run started.\njob: {job_id}\ngoal: {goal}"
        return f"Provider run queued.\njob: {job_id}\nposition: {position}\ngoal: {goal}"
    if request.command == "agent":
        options, error = _parse_agent_options(request.payload)
        if options is None:
            return error or "Usage: /agent ..."
        assert options.goal is not None
        job_id, run_id, position, started = agents.enqueue_auto_dev(
            chat_id,
            options.goal,
            source="agent",
            profile=options.profile,
            config_path=options.config_path,
            enable_commit=options.enable_commit,
            enable_push=options.enable_push,
            enable_pr=options.enable_pr,
            disable_post_run=options.disable_post_run,
        )
        if started:
            return f"Auto-dev run started.\njob: {job_id}\nrun_id: {run_id}\ngoal: {options.goal}"
        return f"Auto-dev run queued.\njob: {job_id}\nrun_id: {run_id}\nposition: {position}\ngoal: {options.goal}"
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

        job_id, run_id, position, started = agents.resume_auto_dev(
            chat_id,
            resume_target=resume_target,
            source="agentresume",
            profile=options.profile,
            config_path=options.config_path,
            enable_commit=options.enable_commit,
            enable_push=options.enable_push,
            enable_pr=options.enable_pr,
            disable_post_run=options.disable_post_run,
        )
        if started:
            return f"Auto-dev resume started.\njob: {job_id}\nrun_id: {run_id}\nresume: {resume_target}"
        return f"Auto-dev resume queued.\njob: {job_id}\nrun_id: {run_id}\nposition: {position}\nresume: {resume_target}"
    if request.command == "schedule":
        parsed, error = _parse_schedule_options(request.payload)
        if parsed is None:
            return error or "Usage: /schedule ..."
        options = parsed["options"]
        assert isinstance(options, AutoDevOptions)
        run_at = str(parsed["run_at"])
        assert options.goal is not None
        job_id, run_id, count = agents.schedule_auto_dev(
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
        )
        return f"Scheduled auto-dev run.\njob: {job_id}\nrun_id: {run_id}\nrun_at: {run_at}\ncount: {count}"
    return f"Unknown control command: /{request.command}"


async def handle_agent(chat_id: int, request: ClassifiedRequest, agents: AgentCoordinator) -> str:
    prompt = request.payload.strip()
    if not prompt:
        return "Empty agent request."
    job_id, position, started = agents.enqueue(chat_id, prompt, source="message")
    if started:
        return f"Provider run started.\njob: {job_id}\ngoal: {prompt}"
    return f"Provider run queued.\njob: {job_id}\nposition: {position}\ngoal: {prompt}"

