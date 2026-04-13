from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
import threading

from robot.config import Settings, normalize_provider
from robot.text import normalize_text


@dataclass(slots=True)
class AgentRunResult:
    provider: str
    model: str
    final_text: str
    thread_id: str | None = None
    return_code: int = 0
    elapsed_seconds: int = 0
    cancelled: bool = False


@dataclass(slots=True)
class RunningInvocation:
    process: subprocess.Popen[str] | None = None
    cancelled: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def set_process(self, process: subprocess.Popen[str]) -> None:
        with self._lock:
            self.process = process
            cancelled = self.cancelled
        if cancelled and process.poll() is None:
            with contextlib.suppress(OSError):
                process.terminate()

    def clear(self) -> None:
        with self._lock:
            self.process = None

    def cancel(self) -> bool:
        with self._lock:
            self.cancelled = True
            process = self.process
        if process is None:
            return True
        if process.poll() is not None:
            return False
        try:
            process.terminate()
            return True
        except OSError:
            return False


def _clip(text: str, limit: int = 3900) -> str:
    cleaned = _safe_text(text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def _safe_text(text: str | None) -> str:
    return normalize_text(text)


async def run_agent_request(
    settings: Settings,
    *,
    provider: str,
    model: str,
    prompt: str,
    thread_id: str | None,
    workdir: Path,
    project_label: str,
    invocation: RunningInvocation | None = None,
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
            invocation=invocation,
        )
    return await _run_generic(
        settings,
        provider=normalized,
        model=model,
        prompt=prompt,
        workdir=workdir,
        project_label=project_label,
        invocation=invocation,
    )


async def list_auto_dev_profiles(
    settings: Settings,
    *,
    workdir: Path,
    config_path: str | None = None,
) -> str:
    command = list(settings.auto_dev_command)
    if config_path:
        command.extend(["--config", config_path])
    command.append("--list-profiles")

    completed = await _run_process(command, prompt="", workdir=workdir, invocation=None)
    output = (completed.stdout or "").strip()
    error = (completed.stderr or "").strip()
    body = output or error or "No profile output."
    if completed.returncode != 0:
        body = f"auto-dev profile listing failed (code {completed.returncode}).\n\n{body}".strip()
    return _clip(body)


async def run_auto_dev_request(
    settings: Settings,
    *,
    prompt: str | None,
    workdir: Path,
    project_label: str,
    run_id: str,
    profile_name: str | None = None,
    config_path: str | None = None,
    resume_target: str | None = None,
    enable_commit: bool = False,
    enable_push: bool = False,
    enable_pr: bool = False,
    disable_post_run: bool = False,
    invocation: RunningInvocation | None = None,
) -> AgentRunResult:
    command = list(settings.auto_dev_command)
    if resume_target:
        command.extend(["--resume", resume_target])
    elif prompt:
        command.extend(["--goal", prompt])
    if profile_name:
        command.extend(["--profile", profile_name])
    if config_path:
        command.extend(["--config", config_path])
    if enable_commit:
        command.append("--commit")
    if enable_push:
        command.append("--push")
    if enable_pr:
        command.append("--pr")
    if disable_post_run:
        command.append("--no-post-run")

    started = time.monotonic()
    completed = await _run_process(command, prompt="", workdir=workdir, invocation=invocation)
    output = (completed.stdout or "").strip()
    error = (completed.stderr or "").strip()
    cancelled = bool(invocation and invocation.cancelled)
    body = output or error or "auto-dev finished without output."
    if cancelled:
        body = f"auto-dev run stopped.\n\n{body}".strip()
    if completed.returncode != 0:
        body = f"auto-dev failed (code {completed.returncode}).\n\n{body}".strip()

    footer = "\n".join(
        [
            f"project: {project_label}",
            "provider: auto-dev",
            f"run_id: {run_id}",
            f"profile: {profile_name or '-'}",
        ]
    )
    return AgentRunResult(
        provider="auto-dev",
        model=profile_name or "-",
        final_text=_clip(f"{body}\n\n{footer}"),
        thread_id=None,
        return_code=completed.returncode,
        elapsed_seconds=int(time.monotonic() - started),
        cancelled=cancelled,
    )


async def _run_process(
    command: list[str],
    *,
    prompt: str,
    workdir: Path,
    invocation: RunningInvocation | None,
) -> subprocess.CompletedProcess[str]:
    def _invoke() -> subprocess.CompletedProcess[str]:
        safe_prompt = _safe_text(prompt)
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(workdir),
        )
        if invocation is not None:
            invocation.set_process(process)
        try:
            stdout, stderr = process.communicate(safe_prompt)
        finally:
            if invocation is not None:
                invocation.clear()
        return subprocess.CompletedProcess(
            command,
            process.returncode or 0,
            _safe_text(stdout),
            _safe_text(stderr),
        )

    return await asyncio.to_thread(_invoke)


async def _run_generic(
    settings: Settings,
    *,
    provider: str,
    model: str,
    prompt: str,
    workdir: Path,
    project_label: str,
    invocation: RunningInvocation | None,
) -> AgentRunResult:
    command = list(settings.provider_commands[provider])
    model_flag = settings.provider_model_flags.get(provider, "--model")
    if model:
        command.extend([model_flag, model])

    started = time.monotonic()

    completed = await _run_process(command, prompt=prompt, workdir=workdir, invocation=invocation)
    output = (completed.stdout or "").strip()
    error = (completed.stderr or "").strip()
    body = output or error or f"{provider} finished without output."
    cancelled = bool(invocation and invocation.cancelled)
    if cancelled:
        body = f"{provider} run stopped.\n\n{body}".strip()
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
        cancelled=cancelled,
    )


async def _run_codex(
    settings: Settings,
    *,
    model: str,
    prompt: str,
    thread_id: str | None,
    workdir: Path,
    project_label: str,
    invocation: RunningInvocation | None,
) -> AgentRunResult:
    command = list(settings.provider_commands["codex"])
    shared_flags: list[str] = []
    if settings.codex_bypass_approvals_and_sandbox:
        shared_flags.append("--dangerously-bypass-approvals-and-sandbox")
    if settings.codex_skip_git_repo_check:
        shared_flags.append("--skip-git-repo-check")
    if thread_id:
        command.extend(
            [
                "exec",
                "resume",
                *shared_flags,
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
                *shared_flags,
                "--json",
                "-m",
                model,
                "-",
            ]
        )

    started = time.monotonic()

    completed = await _run_process(command, prompt=prompt, workdir=workdir, invocation=invocation)
    next_thread_id = thread_id
    assistant_text = ""
    latest_detail = ""
    stdout_lines = [line.strip() for line in (completed.stdout or "").splitlines() if line.strip()]
    stderr_text = (completed.stderr or "").strip()
    cancelled = bool(invocation and invocation.cancelled)

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
    if cancelled:
        body = f"Codex run stopped.\n\n{body}".strip()
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
        cancelled=cancelled,
    )
