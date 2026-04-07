from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from teleapp.context import MessageContext

from robot.config import PROVIDER_LABELS, SUPPORTED_MODELS, Settings, VERSION
from robot.projects import discover_project_workspaces, find_workspace
from robot.providers import run_agent_request
from robot.state import ChatStateStore

COMMAND_REQUEST = "command"
CONTROL_REQUEST = "control"
AGENT_REQUEST = "agent"

COMMAND_NAMES = {
    "start",
    "help",
    "about",
    "status",
    "provider",
    "model",
    "models",
    "project",
    "projects",
}

CONTROL_NAMES = {
    "reset",
    "newthread",
    "restart",
}


@dataclass(slots=True)
class ClassifiedRequest:
    kind: str
    command: str | None
    payload: str


def _command_payload(text: str) -> str:
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[1].strip()


def classify_request(ctx: MessageContext) -> ClassifiedRequest:
    text = (ctx.text or "").strip()
    command = (ctx.command or "").strip().lower() or None

    if command in COMMAND_NAMES:
        return ClassifiedRequest(COMMAND_REQUEST, command, _command_payload(text))
    if command in CONTROL_NAMES:
        return ClassifiedRequest(CONTROL_REQUEST, command, _command_payload(text))
    if command == "agent":
        return ClassifiedRequest(AGENT_REQUEST, command, _command_payload(text))
    if text.startswith("/"):
        return ClassifiedRequest(COMMAND_REQUEST, command, _command_payload(text))
    return ClassifiedRequest(AGENT_REQUEST, None, text)


def _status_text(chat_id: int, store: ChatStateStore) -> str:
    state = store.get_chat_state(chat_id)
    return "\n".join(
        [
            "robot status",
            f"version: {VERSION}",
            f"provider: {state['provider']}",
            f"model: {state['model']}",
            f"project: {state['project_name']}",
            f"path: {state['project_path']}",
            f"thread_id: {state['thread_id'] or '-'}",
            "",
            "request classes:",
            "- command request: /provider /model /project /status",
            "- control request: /reset /newthread /restart",
            "- agent request: plain text or /agent <goal>",
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
            "",
            "control commands:",
            "/reset",
            "/newthread",
            "/restart",
            "",
            "agent requests:",
            "- any normal text message",
            "- /agent <goal>",
        ]
    )


async def handle_request(ctx: MessageContext, settings: Settings, store: ChatStateStore) -> str:
    request = classify_request(ctx)
    if request.kind == COMMAND_REQUEST:
        return handle_command(ctx.chat_id, request, settings, store)
    if request.kind == CONTROL_REQUEST:
        return handle_control(ctx.chat_id, request, store)
    return await handle_agent(ctx.chat_id, request, settings, store)


def handle_command(chat_id: int, request: ClassifiedRequest, settings: Settings, store: ChatStateStore) -> str:
    state = store.get_chat_state(chat_id)

    if request.command in {"start", "help"}:
        return _help_text()

    if request.command == "about":
        return "robot\nteleapp-based Telegram task router\nOnly agent requests are sent to providers."

    if request.command == "status":
        return _status_text(chat_id, store)

    if request.command == "provider":
        payload = request.payload.strip().lower()
        if not payload:
            lines = [f"Current provider: {state['provider']}", "", "Available providers:"]
            lines.extend(f"- {name}" for name in PROVIDER_LABELS)
            return "\n".join(lines)
        if payload not in PROVIDER_LABELS:
            return f"Unknown provider: {payload}\nAvailable: {', '.join(PROVIDER_LABELS)}"
        next_state = store.set_provider(chat_id, payload)
        return f"Provider updated.\nprovider: {next_state['provider']}\nmodel: {next_state['model']}"

    if request.command == "models":
        provider = state["provider"]
        lines = [f"Models for {provider}:"]
        lines.extend(f"- {item}" for item in SUPPORTED_MODELS.get(provider, []))
        return "\n".join(lines)

    if request.command == "model":
        payload = request.payload.strip()
        if not payload:
            provider = state["provider"]
            lines = [f"Current model: {state['model']}", f"Provider: {provider}", "", "Suggested models:"]
            lines.extend(f"- {item}" for item in SUPPORTED_MODELS.get(provider, []))
            return "\n".join(lines)
        next_state = store.set_model(chat_id, payload)
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
            return f"Current project: {state['project_name']}\npath: {state['project_path']}\n\nUse /projects to list workspaces."
        workspace = find_workspace(settings, payload)
        if workspace is None:
            return f"Project not found: {payload}\nUse /projects to list available workspaces."
        next_state = store.set_project(chat_id, workspace.key, workspace.label, str(workspace.path))
        return f"Project updated.\nproject: {next_state['project_name']}\npath: {next_state['project_path']}"

    return f"Unknown command: /{request.command}\nUse /help."


def handle_control(chat_id: int, request: ClassifiedRequest, store: ChatStateStore) -> str:
    if request.command in {"reset", "newthread"}:
        store.clear_thread_id(chat_id)
        return "Thread state cleared for the current provider."
    if request.command == "restart":
        return "Process restart is not wired yet. Use your process manager or rerun start_robot."
    return f"Unknown control command: /{request.command}"


async def handle_agent(chat_id: int, request: ClassifiedRequest, settings: Settings, store: ChatStateStore) -> str:
    prompt = request.payload.strip()
    if not prompt:
        return "Empty agent request."

    state = store.get_chat_state(chat_id)
    result = await run_agent_request(
        settings,
        provider=state["provider"],
        model=state["model"],
        prompt=prompt,
        thread_id=state["thread_id"],
        workdir=Path(state["project_path"]),
        project_label=str(state["project_name"]),
    )
    if result.thread_id is not None:
        store.set_thread_id(chat_id, str(state["provider"]), result.thread_id)
    return result.final_text

