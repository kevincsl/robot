from __future__ import annotations

import re

DISPLAY_MODE_USER = "user"
DISPLAY_MODE_DEVELOPER = "developer"

DISPLAY_MODE_LABELS = {
    DISPLAY_MODE_USER: "使用者模式",
    DISPLAY_MODE_DEVELOPER: "開發者模式",
}

_DISPLAY_MODE_LOOKUP = {
    "user": DISPLAY_MODE_USER,
    "user mode": DISPLAY_MODE_USER,
    "usermode": DISPLAY_MODE_USER,
    "使用者模式": DISPLAY_MODE_USER,
    "developer": DISPLAY_MODE_DEVELOPER,
    "developer mode": DISPLAY_MODE_DEVELOPER,
    "developermode": DISPLAY_MODE_DEVELOPER,
    "dev": DISPLAY_MODE_DEVELOPER,
    "dev mode": DISPLAY_MODE_DEVELOPER,
    "devmode": DISPLAY_MODE_DEVELOPER,
    "開發者模式": DISPLAY_MODE_DEVELOPER,
}

_FOOTER_PREFIXES = (
    "project: ",
    "provider: ",
    "model: ",
    "run_id: ",
    "profile: ",
    "回覆來自 model: ",
)
_FOOTER_PREFIXES_NORMALIZED = tuple(prefix.lower() for prefix in _FOOTER_PREFIXES)
_MODEL_ORIGIN_FOOTER_RE = re.compile(r"^回覆來自\s*model\s*[:：]\s*", re.IGNORECASE)


def normalize_display_mode(value: str | None) -> str:
    normalized = _normalize_mode_key(value)
    return _DISPLAY_MODE_LOOKUP.get(normalized, DISPLAY_MODE_DEVELOPER)


def resolve_display_mode_switch_text(text: str | None) -> str | None:
    normalized = _normalize_mode_key(text)
    return _DISPLAY_MODE_LOOKUP.get(normalized)


def display_mode_label(mode: str) -> str:
    normalized = normalize_display_mode(mode)
    return DISPLAY_MODE_LABELS.get(normalized, DISPLAY_MODE_LABELS[DISPLAY_MODE_DEVELOPER])


def format_display_mode_changed(mode: str) -> str:
    normalized = normalize_display_mode(mode)
    if normalized == DISPLAY_MODE_USER:
        return "已切換為使用者模式。後續會顯示簡潔進度與最終回覆。"
    return "已切換為開發者模式。後續會顯示完整執行細節。"


def format_display_mode_status(mode: str) -> str:
    normalized = normalize_display_mode(mode)
    lines = [f"目前模式: {display_mode_label(normalized)}"]
    if normalized == DISPLAY_MODE_USER:
        lines.append("顯示內容: 簡潔進度與最終回覆")
    else:
        lines.append("顯示內容: 完整執行細節")
    lines.append("可用: /mode user | /mode developer")
    return "\n".join(lines)


def format_run_started(
    mode: str,
    *,
    kind: str,
    goal: str,
    project: str,
    path: str,
    queue_waiting: int,
    elapsed: str,
) -> str:
    normalized = normalize_display_mode(mode)
    if normalized == DISPLAY_MODE_USER:
        return _format_user_progress(project=project, elapsed=elapsed)

    title = "Auto-dev run started." if kind == "auto_dev" else "Provider run started."
    return "\n".join(
        [
            title,
            f"goal: {goal}",
            f"project: {project}",
            f"path: {path}",
            f"queue_waiting: {queue_waiting}",
            f"elapsed: {elapsed}",
            "heartbeat: starting (first update within 1 second)",
        ]
    )


def format_run_queued(
    mode: str,
    *,
    kind: str,
    goal: str,
    project: str,
    path: str,
    position: int,
    elapsed: str,
) -> str:
    normalized = normalize_display_mode(mode)
    if normalized == DISPLAY_MODE_USER:
        return _format_user_progress(project=project, elapsed=elapsed)

    title = "Auto-dev run queued." if kind == "auto_dev" else "Provider run queued."
    hint = "hint: use /queue to check waiting jobs"
    return "\n".join(
        [
            title,
            f"goal: {goal}",
            f"project: {project}",
            f"path: {path}",
            f"queue_position: {position}",
            f"elapsed: {elapsed}",
            hint,
        ]
    )


def format_queue_waiting(
    mode: str,
    *,
    kind: str,
    goal: str,
    project: str,
    path: str,
    queue_pending: int,
    elapsed: str,
) -> str:
    normalized = normalize_display_mode(mode)
    if normalized == DISPLAY_MODE_USER:
        return _format_user_progress(project=project, elapsed=elapsed)

    return "\n".join(
        [
            "Queue waiting.",
            f"kind: {kind}",
            f"doing: {goal}",
            f"project: {project}",
            f"path: {path}",
            "phase: queue: waiting for worker",
            f"queue_pending: {queue_pending}",
            f"elapsed: {elapsed}",
        ]
    )


def format_worker_started(
    mode: str,
    *,
    kind: str,
    goal: str,
    project: str,
    path: str,
    provider: str,
    model: str,
    phase: str,
    queue_pending: int,
    progress: str,
    elapsed: str,
) -> str:
    normalized = normalize_display_mode(mode)
    if normalized == DISPLAY_MODE_USER:
        return _format_user_progress(project=project, elapsed=elapsed)

    return "\n".join(
        [
            "Agent run started.",
            f"kind: {kind}",
            f"goal: {goal}",
            f"project: {project}",
            f"path: {path}",
            f"provider: {provider}",
            f"model/profile: {model}",
            f"phase: {phase}",
            f"queue_pending: {queue_pending}",
            f"progress: {progress}",
            f"elapsed: {elapsed}",
            "heartbeat: active",
        ]
    )


def format_heartbeat(
    mode: str,
    *,
    kind: str,
    goal: str,
    project: str,
    path: str,
    phase: str,
    queue_pending: int,
    progress: str,
    elapsed: str,
) -> str:
    normalized = normalize_display_mode(mode)
    if normalized == DISPLAY_MODE_USER:
        return _format_user_progress(project=project, elapsed=elapsed)

    return "\n".join(
        [
            "Heartbeat.",
            f"kind: {kind}",
            f"doing: {goal}",
            f"project: {project}",
            f"path: {path}",
            f"phase: {phase}",
            f"queue_pending: {queue_pending}",
            f"progress: {progress}",
            f"elapsed: {elapsed}",
        ]
    )


def format_run_finished(
    mode: str,
    *,
    kind: str,
    goal: str,
    project: str,
    path: str,
    queue_pending: int,
    status: str,
    elapsed: str,
) -> str:
    normalized = normalize_display_mode(mode)
    if normalized == DISPLAY_MODE_USER:
        return _format_user_progress(project=project, elapsed=elapsed)

    return "\n".join(
        [
            "Agent run finished.",
            f"kind: {kind}",
            f"goal: {goal}",
            f"project: {project}",
            f"path: {path}",
            f"queue_pending: {queue_pending}",
            f"status: {status}",
            f"elapsed: {elapsed}",
        ]
    )


def format_recovered_run(
    mode: str,
    *,
    kind: str,
    goal: str,
    project: str,
    path: str,
) -> str:
    normalized = normalize_display_mode(mode)
    if normalized == DISPLAY_MODE_USER:
        return "\n".join(
            [
                "已恢復先前中斷的工作。",
                _format_project_tag(project),
            ]
        )

    return "\n".join(
        [
            "Recovered interrupted run after restart.",
            f"kind: {kind}",
            f"doing: {goal}",
            f"project: {project}",
            f"path: {path}",
        ]
    )


def format_run_stopped(
    mode: str,
    *,
    kind: str,
    goal: str,
    project: str,
    path: str,
    elapsed: str,
) -> str:
    normalized = normalize_display_mode(mode)
    if normalized == DISPLAY_MODE_USER:
        return "\n".join(
            [
                f"{_format_project_tag(project)} 處理中止",
                f"total_elapsed: {_elapsed_to_user_value(elapsed)}",
            ]
        )

    return "\n".join(
        [
            "Agent run stopped during shutdown.",
            f"kind: {kind}",
            f"goal: {goal}",
            f"project: {project}",
            f"path: {path}",
            f"elapsed: {elapsed}",
        ]
    )


def format_output_text(
    mode: str,
    *,
    kind: str,
    text: str,
    model: str,
    success: bool,
    project: str | None = None,
    elapsed: str | None = None,
    cancelled: bool = False,
) -> str:
    normalized = normalize_display_mode(mode)
    if normalized == DISPLAY_MODE_DEVELOPER:
        return text

    body = strip_output_footer(_strip_user_mode_completion_wrapper(text))
    if kind != "provider":
        return body

    if cancelled:
        title = "處理中止"
    elif success:
        title = "處理完成"
    else:
        title = "處理失敗"

    lines = [f"{_format_project_tag(project or '-')} {title}"]
    if elapsed is not None:
        lines.append(f"total_elapsed: {_elapsed_to_user_value(elapsed)}")
    if body:
        lines.extend(["", body])
    origin = (model or "").strip() or "-"
    lines.extend(["", f"回覆來自 model: {origin}"])
    return "\n".join(lines).strip()


def strip_output_footer(text: str) -> str:
    lines = text.rstrip().splitlines()
    if not lines:
        return ""

    trimmed = list(lines)
    removed_any = False
    while trimmed:
        while trimmed and not trimmed[-1].strip():
            trimmed.pop()
        if trimmed and _is_footer_line(trimmed[-1]):
            trimmed.pop()
            removed_any = True
            continue
        break

    if not removed_any:
        return text.strip()

    return "\n".join(trimmed).strip()


def _strip_user_mode_completion_wrapper(text: str) -> str:
    lines = text.strip().splitlines()
    if len(lines) < 2:
        return text.strip()

    first = lines[0].strip()
    second = lines[1].strip()
    if not first.startswith("專案["):
        return text.strip()
    if not (
        first.endswith("處理完成")
        or first.endswith("處理失敗")
        or first.endswith("處理中止")
    ):
        return text.strip()
    if not second.startswith("total_elapsed: "):
        return text.strip()

    start_index = 2
    while start_index < len(lines) and not lines[start_index].strip():
        start_index += 1
    if start_index >= len(lines):
        return ""

    end_index = len(lines)
    if _is_footer_line(lines[-1]):
        end_index -= 1
        while end_index > start_index and not lines[end_index - 1].strip():
            end_index -= 1

    return "\n".join(lines[start_index:end_index]).strip()


def _is_footer_line(line: str) -> bool:
    normalized = line.strip().lower()
    if not normalized:
        return False
    if normalized.startswith(_FOOTER_PREFIXES_NORMALIZED):
        return True
    return bool(_MODEL_ORIGIN_FOOTER_RE.match(line.strip()))


def _format_user_progress(*, project: str, elapsed: str) -> str:
    seconds = _elapsed_to_seconds(elapsed)
    state = "已接收訊息" if seconds <= 0 else "處理中"
    tag = _format_project_tag(project)
    if seconds > 0:
        return f"{tag} {state} {_elapsed_to_user_value(elapsed)}"
    return f"{tag} {state}"


def _elapsed_history_lines(elapsed: str) -> list[str]:
    seconds = _elapsed_to_seconds(elapsed)
    if seconds <= 0:
        return ["elapsed: 0s"]
    marks = list(range(0, seconds + 1, 5))
    if not marks:
        marks = [0]
    return [f"elapsed: {mark}s" for mark in marks]


def _elapsed_to_user_value(elapsed: str) -> str:
    return f"{_elapsed_to_seconds(elapsed)}s"


def _elapsed_to_seconds(elapsed: str) -> int:
    text = str(elapsed or "").strip().lower()
    if not text:
        return 0
    if text.endswith("s") and text[:-1].isdigit():
        return max(0, int(text[:-1]))
    parts = text.split(":")
    if all(part.isdigit() for part in parts):
        values = [int(part) for part in parts]
        if len(values) == 2:
            return max(0, (values[0] * 60) + values[1])
        if len(values) == 3:
            return max(0, (values[0] * 3600) + (values[1] * 60) + values[2])
    return 0


def _format_project_tag(project: str) -> str:
    text = str(project or "").strip() or "-"
    match = re.match(r"^(?P<name>.+?) \[(?P<branch>.+)\]$", text)
    if match:
        return f"專案[{match.group('name')}/{match.group('branch')}]"
    return f"專案[{text}]"


def _normalize_mode_key(value: str | None) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"\s+", " ", text)
