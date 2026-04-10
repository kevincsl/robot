from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

from robot.config import Settings


INVALID_PATH_CHARS = re.compile(r'[<>:"/\\|?*]+')
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)


def _run_brain_command(settings: Settings, *args: str) -> str:
    command = [*settings.brain_cli_command, *args, f"vault={settings.brain_vault_name}"]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return (completed.stdout or "").strip()


def _try_cli(settings: Settings, *args: str) -> str | None:
    try:
        return _run_brain_command(settings, *args)
    except (FileNotFoundError, OSError, subprocess.CalledProcessError):
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
    result = _try_cli(
        settings,
        "property:set",
        f"path={relative_path}",
        f"name={name}",
        f"value={value}",
        f"type={type_name}",
    )
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
        results.append(
            {
                "file": _relative_posix(path, vault_root),
                "matches": [{"text": line} for line in matched_lines[:2]],
            }
        )
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


def ensure_weekly_summary_note(settings: Settings) -> str:
    stamp = datetime.now().strftime("%G-[W]%V")
    path = f"07 Decision Support/Weekly Summary - {stamp}.md"
    result = _try_cli(settings, "create", f"path={path}", "template=Template - Weekly Summary")
    relative = path if result is not None else _create_note_direct(settings, path, template="Template - Weekly Summary")
    apply_note_defaults(settings, relative, note_type="review", title=stamp, topic="weekly-summary", review=True)
    return relative


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
