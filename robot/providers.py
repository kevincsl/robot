from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
import threading
from typing import Any

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
    phase: str = "pending"
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def set_process(self, process: subprocess.Popen[str]) -> None:
        with self._lock:
            self.process = process
            cancelled = self.cancelled
            self.phase = "running"
        if cancelled and process.poll() is None:
            with contextlib.suppress(OSError):
                process.terminate()

    def clear(self) -> None:
        with self._lock:
            self.process = None

    def set_phase(self, phase: str) -> None:
        with self._lock:
            self.phase = _safe_text(phase).strip() or self.phase

    def get_phase(self) -> str:
        with self._lock:
            return self.phase

    def cancel(self) -> bool:
        with self._lock:
            self.cancelled = True
            process = self.process
            self.phase = "stopping"
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


def _windows_creationflags_no_window() -> int:
    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _extract_text_candidates(payload: Any) -> list[str]:
    texts: list[str] = []
    if isinstance(payload, str):
        if payload.strip():
            texts.append(payload)
        return texts
    if isinstance(payload, list):
        for item in payload:
            texts.extend(_extract_text_candidates(item))
        return texts
    if not isinstance(payload, dict):
        return texts

    for key in ("text", "delta"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            texts.append(value)

    for key in ("content", "output", "items", "message", "response"):
        value = payload.get(key)
        if value is not None:
            texts.extend(_extract_text_candidates(value))

    return texts


def _merge_assistant_text(delta_text: str, snapshot_text: str) -> str:
    delta_clean = _safe_text(delta_text).strip()
    snapshot_clean = _safe_text(snapshot_text).strip()
    if delta_clean and snapshot_clean:
        if delta_clean in snapshot_clean:
            return snapshot_clean
        if snapshot_clean in delta_clean:
            return delta_clean
        if len(snapshot_clean) >= len(delta_clean):
            return snapshot_clean
    return delta_clean or snapshot_clean


def _parse_json_event_line(line: str) -> dict[str, Any] | None:
    candidate = line.strip()
    if not candidate:
        return None
    if candidate.startswith("data:"):
        candidate = candidate[5:].strip()
    if not candidate:
        return None
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        brace = candidate.find("{")
        if brace < 0:
            return None
        try:
            parsed = json.loads(candidate[brace:])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _parse_codex_stream(
    *,
    stdout: str,
    stderr: str,
    base_thread_id: str | None,
) -> tuple[str | None, str, str]:
    next_thread_id = base_thread_id
    assistant_snapshot = ""
    assistant_delta_chunks: list[str] = []
    latest_detail = ""
    stdout_lines = [line.strip() for line in (stdout or "").splitlines() if line.strip()]
    stderr_text = (stderr or "").strip()

    for line in stdout_lines:
        event = _parse_json_event_line(line)
        if event is None:
            latest_detail = line
            continue

        event_type = event.get("type")
        if event_type == "thread.started":
            candidate = str(event.get("thread_id") or "").strip()
            if candidate:
                next_thread_id = candidate
            continue
        if event_type == "response.output_text.delta":
            delta = str(event.get("delta") or "")
            if delta:
                assistant_delta_chunks.append(delta)
            continue
        if event_type in {"response.output_text.done", "response.completed"}:
            candidates = _extract_text_candidates(event)
            if candidates:
                assistant_snapshot = max(candidates, key=len)
            continue
        if event_type in {"item.completed", "item.started"}:
            item = event.get("item")
            if isinstance(item, dict):
                item_type = str(item.get("type") or "")
                if item_type == "command_execution":
                    latest_detail = str(item.get("aggregated_output") or item.get("command") or "").strip() or latest_detail
                else:
                    candidates = _extract_text_candidates(item)
                    if candidates:
                        assistant_snapshot = max(candidates, key=len)
            continue
        if event_type == "item.delta":
            delta = str(event.get("delta") or "")
            if delta:
                assistant_delta_chunks.append(delta)
                continue
            item = event.get("item")
            if isinstance(item, dict):
                inner_delta = str(item.get("delta") or "")
                if inner_delta:
                    assistant_delta_chunks.append(inner_delta)
            continue
        if event_type == "error":
            latest_detail = str(event.get("message") or "").strip() or latest_detail

    assistant_text = _merge_assistant_text("".join(assistant_delta_chunks), assistant_snapshot)
    detail = latest_detail or stderr_text
    return next_thread_id, assistant_text, detail


def _is_stream_disconnect(detail: str) -> bool:
    text = (detail or "").strip().lower()
    if not text:
        return False
    return "stream disconnected before completion" in text or "stream closed before response.completed" in text


def _is_context_window_exhausted(detail: str) -> bool:
    text = (detail or "").strip().lower()
    if not text:
        return False
    return (
        "ran out of room in the model's context window" in text
        or "clear earlier history before retrying" in text
    )


def _parse_claude_stream(
    *,
    stdout: str,
    stderr: str,
    base_session_id: str | None,
) -> tuple[str | None, str, str]:
    next_session_id = base_session_id
    assistant_text = ""
    latest_detail = ""
    stdout_lines = [line.strip() for line in (stdout or "").splitlines() if line.strip()]
    stderr_text = (stderr or "").strip()

    for line in stdout_lines:
        event = _parse_json_event_line(line)
        if event is None:
            latest_detail = line
            continue

        event_type = event.get("type")
        if event_type == "system":
            if event.get("subtype") == "init":
                candidate = str(event.get("session_id") or "").strip()
                if candidate:
                    next_session_id = candidate
            continue
        if event_type == "assistant":
            message = event.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict):
                            if item.get("type") == "text":
                                text_val = str(item.get("text") or "").strip()
                                if text_val:
                                    assistant_text = text_val
                            elif item.get("type") == "thinking":
                                # skip thinking blocks
                                pass
            continue
        if event_type == "result":
            subtype = event.get("subtype")
            if subtype == "success":
                result_text = str(event.get("result") or "").strip()
                if result_text:
                    assistant_text = result_text
                error_status = event.get("api_error_status")
                if error_status:
                    latest_detail = str(error_status)
            elif subtype == "error":
                latest_detail = str(event.get("error") or event.get("message") or "").strip() or latest_detail
            continue

    detail = latest_detail or stderr_text
    return next_session_id, assistant_text, detail


def _is_claude_permission_denied(detail: str) -> bool:
    text = (detail or "").strip().lower()
    if not text:
        return False
    return "permission denied" in text or "not allowed to use" in text


def _is_claude_session_not_found(detail: str) -> bool:
    text = (detail or "").strip().lower()
    if not text:
        return False
    return "no conversation found with session id" in text


def _build_codex_command(
    *,
    settings: Settings,
    model: str,
    thread_id: str | None,
) -> list[str]:
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
    return command


def _build_claude_command(
    *,
    settings: Settings,
    model: str,
    session_id: str | None,
    prompt: str,
) -> list[str]:
    command = list(settings.provider_commands["claude"])
    shared_flags: list[str] = ["-p", "--output-format", "stream-json", "--verbose"]
    if settings.claude_skip_permissions:
        shared_flags.append("--dangerously-skip-permissions")
    if session_id:
        command.extend(["--resume", session_id])
    command.extend(shared_flags)
    model_flag = settings.provider_model_flags.get("claude", "-m")
    command.extend([model_flag, model])
    # Claude CLI takes prompt as positional argument
    if prompt:
        command.append(prompt)
    return command


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
    if normalized == "claude":
        return await _run_claude(
            settings,
            model=model,
            prompt=prompt,
            session_id=thread_id,
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
    if invocation is not None:
        invocation.set_phase("auto-dev: preparing command")
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
    if invocation is not None:
        invocation.set_phase("auto-dev: executing")
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
        if not workdir.exists():
            return subprocess.CompletedProcess(
                command, 1, "", f"workdir does not exist: {workdir}"
            )
        safe_prompt = _safe_text(prompt)
        if invocation is not None:
            invocation.set_phase("process: starting")
        popen_kwargs: dict[str, Any] = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "cwd": str(workdir),
        }
        no_window = _windows_creationflags_no_window()
        if no_window:
            popen_kwargs["creationflags"] = no_window
        process = subprocess.Popen(
            command,
            **popen_kwargs,
        )
        if invocation is not None:
            invocation.set_process(process)
        try:
            if invocation is not None:
                invocation.set_phase("process: waiting for completion")
            stdout, stderr = process.communicate(safe_prompt)
            if invocation is not None:
                invocation.set_phase("process: completed")
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
    if invocation is not None:
        invocation.set_phase(f"{provider}: preparing command")
    command = list(settings.provider_commands[provider])
    model_flag = settings.provider_model_flags.get(provider, "--model")
    if model:
        command.extend([model_flag, model])

    started = time.monotonic()

    if invocation is not None:
        invocation.set_phase(f"{provider}: executing")
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
    if invocation is not None:
        invocation.set_phase("codex: preparing command")
    command = _build_codex_command(settings=settings, model=model, thread_id=thread_id)

    started = time.monotonic()

    if invocation is not None:
        invocation.set_phase("codex: executing")
    completed = await _run_process(command, prompt=prompt, workdir=workdir, invocation=invocation)
    cancelled = bool(invocation and invocation.cancelled)
    next_thread_id, assistant_text, latest_detail = _parse_codex_stream(
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        base_thread_id=thread_id,
    )

    if (
        completed.returncode != 0
        and not cancelled
        and not assistant_text
        and _is_stream_disconnect(latest_detail)
    ):
        if invocation is not None:
            invocation.set_phase("codex: retrying after stream disconnect")
        retry_completed = await _run_process(command, prompt=prompt, workdir=workdir, invocation=invocation)
        retry_thread_id, retry_assistant_text, retry_detail = _parse_codex_stream(
            stdout=retry_completed.stdout or "",
            stderr=retry_completed.stderr or "",
            base_thread_id=next_thread_id,
        )
        completed = retry_completed
        if retry_thread_id:
            next_thread_id = retry_thread_id
        assistant_text = retry_assistant_text
        latest_detail = retry_detail

    if (
        completed.returncode != 0
        and not cancelled
        and thread_id is not None
        and _is_context_window_exhausted(latest_detail)
    ):
        if invocation is not None:
            invocation.set_phase("codex: retrying with fresh thread")
        fresh_command = _build_codex_command(settings=settings, model=model, thread_id=None)
        retry_completed = await _run_process(fresh_command, prompt=prompt, workdir=workdir, invocation=invocation)
        retry_thread_id, retry_assistant_text, retry_detail = _parse_codex_stream(
            stdout=retry_completed.stdout or "",
            stderr=retry_completed.stderr or "",
            base_thread_id=None,
        )
        completed = retry_completed
        next_thread_id = retry_thread_id
        assistant_text = retry_assistant_text
        latest_detail = retry_detail

    body = assistant_text or latest_detail or "Codex finished without an assistant reply."
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


async def _run_claude(
    settings: Settings,
    *,
    model: str,
    prompt: str,
    session_id: str | None,
    workdir: Path,
    project_label: str,
    invocation: RunningInvocation | None,
) -> AgentRunResult:
    if invocation is not None:
        invocation.set_phase("claude: preparing command")
    command = _build_claude_command(settings=settings, model=model, session_id=session_id, prompt=prompt)

    started = time.monotonic()

    if invocation is not None:
        invocation.set_phase("claude: executing")
    completed = await _run_process(command, prompt="", workdir=workdir, invocation=invocation)
    cancelled = bool(invocation and invocation.cancelled)
    next_session_id, assistant_text, latest_detail = _parse_claude_stream(
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        base_session_id=session_id,
    )

    if (
        completed.returncode != 0
        and not cancelled
        and not assistant_text
        and _is_stream_disconnect(latest_detail)
    ):
        if invocation is not None:
            invocation.set_phase("claude: retrying after stream disconnect")
        retry_completed = await _run_process(command, prompt="", workdir=workdir, invocation=invocation)
        retry_session_id, retry_assistant_text, retry_detail = _parse_claude_stream(
            stdout=retry_completed.stdout or "",
            stderr=retry_completed.stderr or "",
            base_session_id=next_session_id,
        )
        completed = retry_completed
        if retry_session_id:
            next_session_id = retry_session_id
        assistant_text = retry_assistant_text
        latest_detail = retry_detail

    if (
        completed.returncode != 0
        and not cancelled
        and session_id is not None
        and _is_claude_session_not_found(latest_detail)
    ):
        if invocation is not None:
            invocation.set_phase("claude: retrying with fresh session")
        fresh_command = _build_claude_command(
            settings=settings,
            model=model,
            session_id=None,
            prompt=prompt,
        )
        retry_completed = await _run_process(fresh_command, prompt="", workdir=workdir, invocation=invocation)
        retry_session_id, retry_assistant_text, retry_detail = _parse_claude_stream(
            stdout=retry_completed.stdout or "",
            stderr=retry_completed.stderr or "",
            base_session_id=None,
        )
        completed = retry_completed
        next_session_id = retry_session_id
        assistant_text = retry_assistant_text
        latest_detail = retry_detail

    body = assistant_text or latest_detail or "Claude finished without an assistant reply."
    if cancelled:
        body = f"Claude run stopped.\n\n{body}".strip()
    if completed.returncode != 0:
        body = f"Claude failed (code {completed.returncode}).\n\n{body}".strip()

    footer = f"project: {project_label}\nprovider: claude\nmodel: {model}"
    return AgentRunResult(
        provider="claude",
        model=model,
        final_text=_clip(f"{body}\n\n{footer}"),
        thread_id=next_session_id,
        return_code=completed.returncode,
        elapsed_seconds=int(time.monotonic() - started),
        cancelled=cancelled,
    )
