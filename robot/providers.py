from __future__ import annotations

import asyncio
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from robot.config import Settings, normalize_provider


@dataclass(slots=True)
class AgentRunResult:
    provider: str
    model: str
    final_text: str
    thread_id: str | None = None
    return_code: int = 0
    elapsed_seconds: int = 0


def _clip(text: str, limit: int = 3900) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


async def run_agent_request(
    settings: Settings,
    *,
    provider: str,
    model: str,
    prompt: str,
    thread_id: str | None,
    workdir: Path,
    project_label: str,
) -> AgentRunResult:
    normalized = normalize_provider(provider)
    if normalized == "codex":
        return await _run_codex(
            settings,
            model=model,
            prompt=prompt,
            thread_id=thread_id,
            workdir=workdir,
            project_label=project_label,
        )
    return await _run_generic(
        settings,
        provider=normalized,
        model=model,
        prompt=prompt,
        workdir=workdir,
        project_label=project_label,
    )


async def _run_generic(
    settings: Settings,
    *,
    provider: str,
    model: str,
    prompt: str,
    workdir: Path,
    project_label: str,
) -> AgentRunResult:
    command = list(settings.provider_commands[provider])
    model_flag = settings.provider_model_flags.get(provider, "--model")
    if model:
        command.extend([model_flag, model])

    started = time.monotonic()

    def _invoke() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(workdir),
            check=False,
        )

    completed = await asyncio.to_thread(_invoke)
    output = (completed.stdout or "").strip()
    error = (completed.stderr or "").strip()
    body = output or error or f"{provider} finished without output."
    if completed.returncode != 0:
        body = f"{provider} failed (code {completed.returncode}).\n\n{body}".strip()

    footer = f"project: {project_label}\nprovider: {provider}\nmodel: {model}"
    return AgentRunResult(
        provider=provider,
        model=model,
        final_text=_clip(f"{body}\n\n{footer}"),
        thread_id=None,
        return_code=completed.returncode,
        elapsed_seconds=int(time.monotonic() - started),
    )


async def _run_codex(
    settings: Settings,
    *,
    model: str,
    prompt: str,
    thread_id: str | None,
    workdir: Path,
    project_label: str,
) -> AgentRunResult:
    command = list(settings.provider_commands["codex"])
    if thread_id:
        command.extend(
            [
                "exec",
                "resume",
                "--dangerously-bypass-approvals-and-sandbox",
                "--skip-git-repo-check",
                "--json",
                "-m",
                model,
                thread_id,
                "-",
            ]
        )
    else:
        command.extend(
            [
                "exec",
                "--dangerously-bypass-approvals-and-sandbox",
                "--skip-git-repo-check",
                "--json",
                "-m",
                model,
                "-",
            ]
        )

    started = time.monotonic()

    def _invoke() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(workdir),
            check=False,
        )

    completed = await asyncio.to_thread(_invoke)
    next_thread_id = thread_id
    assistant_text = ""
    latest_detail = ""
    stdout_lines = [line.strip() for line in (completed.stdout or "").splitlines() if line.strip()]
    stderr_text = (completed.stderr or "").strip()

    for line in stdout_lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            latest_detail = line
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type == "thread.started":
            candidate = str(event.get("thread_id") or "").strip()
            if candidate:
                next_thread_id = candidate
        elif event_type in {"item.completed", "item.started"}:
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message":
                assistant_text = str(item.get("text") or "").strip() or assistant_text
            elif isinstance(item, dict) and item.get("type") == "command_execution":
                latest_detail = str(item.get("aggregated_output") or item.get("command") or "").strip() or latest_detail
        elif event_type == "error":
            latest_detail = str(event.get("message") or "").strip() or latest_detail

    body = assistant_text or latest_detail or stderr_text or "Codex finished without an assistant reply."
    if completed.returncode != 0:
        body = f"Codex failed (code {completed.returncode}).\n\n{body}".strip()

    footer = f"project: {project_label}\nprovider: codex\nmodel: {model}"
    return AgentRunResult(
        provider="codex",
        model=model,
        final_text=_clip(f"{body}\n\n{footer}"),
        thread_id=next_thread_id,
        return_code=completed.returncode,
        elapsed_seconds=int(time.monotonic() - started),
    )

