from __future__ import annotations

import re
from typing import TYPE_CHECKING

from robot.footer_parser import clean_footer, format_footer, format_footer_from_text

if TYPE_CHECKING:
    from robot.template_loader import DisplayModeTemplates

DISPLAY_MODE_USER = "user"
DISPLAY_MODE_DEVELOPER = "developer"

CODE_DISPLAY_NORMAL = "normal"
CODE_DISPLAY_SMART = "smart"
CODE_DISPLAY_ALL = "all"

# ── template injection ───────────────────────────────────────
_templates: DisplayModeTemplates | None = None
_template_locale: str | None = None


def configure_templates(templates: DisplayModeTemplates) -> None:
    global _templates, _template_locale
    _templates = templates
    _template_locale = templates.locale


def _t() -> DisplayModeTemplates:
    global _templates
    if _templates is None:
        from robot.template_loader import get_templates
        _templates = get_templates()
    return _templates


def configure_templates_for_locale(locale: str, platform: str = "telegram") -> None:
    """Reload templates for the given locale (call after i18n.set_locale)."""
    global _templates, _template_locale
    from robot.template_loader import clear_templates_cache, get_templates
    clear_templates_cache()
    _templates = get_templates(locale=locale, platform=platform)
    _template_locale = locale

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

_CODE_DISPLAY_MODE_LOOKUP = {
    "normal": CODE_DISPLAY_NORMAL,
    "off": CODE_DISPLAY_NORMAL,
    "none": CODE_DISPLAY_NORMAL,
    "smart": CODE_DISPLAY_SMART,
    "auto": CODE_DISPLAY_SMART,
    "all": CODE_DISPLAY_ALL,
    "copy": CODE_DISPLAY_ALL,
    "copycode": CODE_DISPLAY_ALL,
    "copy_code": CODE_DISPLAY_ALL,
    "code": CODE_DISPLAY_ALL,
    "on": CODE_DISPLAY_ALL,
}


_MODEL_ORIGIN_FOOTER_RE = re.compile(r"^回覆來自\s*model\s*[:：]\s*", re.IGNORECASE)

def normalize_display_mode(value: str | None) -> str:
    normalized = _normalize_mode_key(value)
    return _DISPLAY_MODE_LOOKUP.get(normalized, DISPLAY_MODE_DEVELOPER)


def resolve_display_mode_switch_text(text: str | None) -> str | None:
    normalized = _normalize_mode_key(text)
    return _DISPLAY_MODE_LOOKUP.get(normalized)


def normalize_code_display_mode(value: str | None) -> str:
    normalized = _normalize_mode_key(value)
    return _CODE_DISPLAY_MODE_LOOKUP.get(normalized, CODE_DISPLAY_SMART)


def code_display_mode_label(mode: str | None) -> str:
    normalized = normalize_code_display_mode(mode)
    if normalized == CODE_DISPLAY_ALL:
        return "copy_code"
    if normalized == CODE_DISPLAY_NORMAL:
        return "normal"
    return "smart"


def wrap_text_for_code_display(text: str, mode: str | None) -> str:
    normalized = normalize_code_display_mode(mode)
    clean = str(text or "")
    if normalized != CODE_DISPLAY_ALL or not clean.strip():
        return clean
    if "```" in clean:
        return clean
    return f"```text\n{clean}\n```"


def display_mode_label(mode: str) -> str:
    normalized = normalize_display_mode(mode)
    return _t().mode_label(normalized)


def format_display_mode_changed(mode: str) -> str:
    normalized = normalize_display_mode(mode)
    return _t().mode_changed(normalized)


def format_display_mode_status(mode: str) -> str:
    normalized = normalize_display_mode(mode)
    tmpl = _t()
    lines = [tmpl.mode_status_current(tmpl.mode_label(normalized))]
    if normalized == DISPLAY_MODE_USER:
        lines.append(tmpl.mode_status_content("user"))
    else:
        lines.append(tmpl.mode_status_content("developer"))
    lines.append(tmpl.mode_status_usage())
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
    return _t().developer_run_started(
        kind,
        goal=goal,
        project=project,
        path=path,
        queue_waiting=str(queue_waiting),
        elapsed=elapsed,
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
    return _t().developer_run_queued(
        kind,
        goal=goal,
        project=project,
        path=path,
        position=str(position),
        elapsed=elapsed,
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
    return _t().developer_queue_waiting(
        kind=kind,
        goal=goal,
        project=project,
        path=path,
        queue_pending=str(queue_pending),
        elapsed=elapsed,
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
    return _t().developer_worker_started(
        kind=kind,
        goal=goal,
        project=project,
        path=path,
        provider=provider,
        model=model,
        phase=phase,
        queue_pending=str(queue_pending),
        progress=progress,
        elapsed=elapsed,
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
    return _t().developer_heartbeat(
        kind=kind,
        goal=goal,
        project=project,
        path=path,
        phase=phase,
        queue_pending=str(queue_pending),
        progress=progress,
        elapsed=elapsed,
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
    return _t().developer_run_finished(
        kind=kind,
        goal=goal,
        project=project,
        path=path,
        queue_pending=str(queue_pending),
        status=status,
        elapsed=elapsed,
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
    tmpl = _t()
    if normalized == DISPLAY_MODE_USER:
        return "\n".join(
            [
                tmpl.recovered_run("user"),
                _format_project_tag(project),
            ]
        )
    return "\n".join(
        [
            tmpl.recovered_run("developer"),
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
    tmpl = _t()
    if normalized == DISPLAY_MODE_USER:
        return tmpl.run_stopped("user", tag=_format_project_tag(project), elapsed=_elapsed_to_user_value(elapsed))
    return "\n".join(
        [
            tmpl.run_stopped_developer(),
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

    tmpl = _t()
    body = strip_output_footer(_strip_user_mode_completion_wrapper(text))
    if kind != "provider":
        return body

    if cancelled:
        icon = "⛔"
        title = tmpl.output_cancelled()
    elif success:
        icon = "✅"
        title = tmpl.output_success()
    else:
        icon = "❌"
        title = tmpl.output_failure()

    elapsed_display = f" · {_elapsed_to_user_value(elapsed)}" if elapsed is not None else ""
    lines = [f"{icon} {_format_project_tag(project or '-')} {title}{elapsed_display}"]
    if body:
        lines.extend(["", body])
    origin = (model or "").strip() or "-"
    lines.extend(["", tmpl.footer_origin(origin)])
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
    tmpl = _t()
    lines = text.strip().splitlines()
    if not lines:
        return text.strip()

    first = lines[0].strip()
    icons = tmpl.wrapper_icons()
    has_icon_prefix = any(first.startswith(icon + tmpl.wrapper_project_prefix()) for icon in icons)
    has_legacy_prefix = first.startswith(tmpl.wrapper_project_prefix())
    if not (has_icon_prefix or has_legacy_prefix):
        return text.strip()

    success = tmpl.wrapper_completion_success()
    failure = tmpl.wrapper_completion_failure()
    cancelled = tmpl.wrapper_completion_cancelled()
    if not (
        first.endswith(success) or f"{success} ·" in first
        or first.endswith(failure) or f"{failure} ·" in first
        or first.endswith(cancelled) or f"{cancelled} ·" in first
    ):
        return text.strip()

    start_index = 1
    if has_legacy_prefix and start_index < len(lines):
        if lines[start_index].strip().lower().startswith("total_elapsed:"):
            start_index += 1
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
    if normalized.startswith(_t().footer_prefixes_normalized()):
        return True
    return bool(_MODEL_ORIGIN_FOOTER_RE.match(line.strip()))


def _format_user_progress(*, project: str, elapsed: str) -> str:
    seconds = _elapsed_to_seconds(elapsed)
    tag = _format_project_tag(project)
    tmpl = _t()
    if seconds > 0:
        return tmpl.user_progress_processing(tag=tag, elapsed=_elapsed_to_user_value(elapsed))
    return tmpl.user_progress_received(tag=tag)


def _format_project_tag(project: str) -> str:
    text = str(project or "").strip() or "-"
    match = re.match(r"^(?P<name>.+?) \[(?P<branch>.+)\]$", text)
    tmpl = _t()
    if match:
        return tmpl.project_tag_with_branch(name=match.group("name"), branch=match.group("branch"))
    return tmpl.project_tag_without_branch(text=text)


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


def _normalize_mode_key(value: str | None) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"\s+", " ", text)
