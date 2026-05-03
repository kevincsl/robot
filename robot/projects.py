from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from robot.config import Settings

EXCLUDED_NAMES = {
    ".git",
    ".github",
    ".venv",
    "__pycache__",
    "node_modules",
    ".robot_state",
    "dist",
    "build",
}

PROJECT_MARKERS = (
    ".git",
    "pyproject.toml",
    "package.json",
    "README.md",
)


@dataclass(frozen=True)
class ProjectWorkspace:
    key: str
    label: str
    path: Path


def _workspace_key_for(path: Path) -> str:
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:12]
    return f"proj-{digest}"


def _looks_like_project(path: Path) -> bool:
    return any((path / marker).exists() for marker in PROJECT_MARKERS)


def _label_for(root: Path, path: Path) -> str:
    if path == root:
        return path.name
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return path.name


def discover_project_workspaces(settings: Settings) -> list[ProjectWorkspace]:
    workspaces: list[ProjectWorkspace] = []
    seen: set[str] = set()

    for root in _effective_projects_roots(settings):
        if not root.exists() or not root.is_dir():
            continue

        candidates: list[Path] = []
        if _looks_like_project(root):
            candidates.append(root)

        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name in EXCLUDED_NAMES:
                continue
            if _looks_like_project(child):
                candidates.append(child)

        for path in candidates:
            resolved = str(path.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            workspaces.append(
                ProjectWorkspace(
                    key=_workspace_key_for(path),
                    label=_label_for(root, path),
                    path=path.resolve(),
                )
            )

    workspaces.sort(key=lambda item: item.label.lower())
    return workspaces


def _projects_roots_state_path(settings: Settings) -> Path:
    return settings.state_home / "projects_roots.json"


def _normalize_root(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _read_projects_roots_state(settings: Settings) -> dict[str, list[str]]:
    path = _projects_roots_state_path(settings)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {"roots": []}
    if not isinstance(raw, dict):
        return {"roots": []}
    roots = raw.get("roots")
    if not isinstance(roots, list):
        return {"roots": []}
    clean_roots = [str(item).strip() for item in roots if str(item).strip()]
    return {"roots": clean_roots}


def _write_projects_roots_state(settings: Settings, roots: list[Path]) -> None:
    path = _projects_roots_state_path(settings)
    payload = {"roots": [str(item) for item in roots]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _effective_projects_roots(settings: Settings) -> list[Path]:
    configured = [_normalize_root(path) for path in settings.projects_roots]
    state = _read_projects_roots_state(settings)
    dynamic = [_normalize_root(path) for path in state.get("roots", [])]
    merged: list[Path] = []
    seen: set[str] = set()
    for item in [*configured, *dynamic]:
        marker = str(item)
        if marker in seen:
            continue
        seen.add(marker)
        merged.append(item)
    return merged


def list_projects_roots(settings: Settings) -> list[Path]:
    return _effective_projects_roots(settings)


def add_projects_root(settings: Settings, path: str) -> list[Path]:
    candidate = _normalize_root(path)
    state = _read_projects_roots_state(settings)
    current = [_normalize_root(item) for item in state.get("roots", [])]
    merged: list[Path] = []
    seen: set[str] = set()
    for item in [*current, candidate]:
        marker = str(item)
        if marker in seen:
            continue
        seen.add(marker)
        merged.append(item)
    _write_projects_roots_state(settings, merged)
    return _effective_projects_roots(settings)


def remove_projects_root(settings: Settings, path: str) -> tuple[bool, list[Path]]:
    candidate = _normalize_root(path)
    state = _read_projects_roots_state(settings)
    current = [_normalize_root(item) for item in state.get("roots", [])]
    next_roots = [item for item in current if item != candidate]
    removed = len(next_roots) != len(current)
    _write_projects_roots_state(settings, next_roots)
    return removed, _effective_projects_roots(settings)


def get_default_workspace(settings: Settings) -> ProjectWorkspace:
    matches = discover_project_workspaces(settings)
    exact = next((item for item in matches if item.path == settings.project_root), None)
    if exact is not None:
        return exact
    return ProjectWorkspace(
        key=_workspace_key_for(settings.project_root),
        label=settings.project_root.name,
        path=settings.project_root,
    )


def find_workspace(settings: Settings, value: str) -> ProjectWorkspace | None:
    needle = (value or "").strip()
    if not needle:
        return None

    lowered = needle.lower()
    workspaces = discover_project_workspaces(settings)
    for workspace in workspaces:
        if workspace.key == needle:
            return workspace
        if workspace.label.lower() == lowered:
            return workspace

    partial = [item for item in workspaces if lowered in item.label.lower()]
    if len(partial) == 1:
        return partial[0]
    return None


def _compact_branch_name(branch_name: str) -> str:
    text = (branch_name or "").strip()
    if not text:
        return text
    if "/" not in text:
        return text
    return text.split("/", 1)[0]


def _git_branch_name(path: Path) -> str | None:
    try:
        current = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=1.2,
            cwd=path,
        )
    except (FileNotFoundError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None

    branch = (current.stdout or "").strip()
    if not branch:
        return None
    if branch != "HEAD":
        return _compact_branch_name(branch)

    try:
        detached = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=1.2,
            cwd=path,
        )
    except (FileNotFoundError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return "detached"

    revision = (detached.stdout or "").strip()
    if not revision:
        return "detached"
    return f"detached:{revision}"


def format_project_with_branch(project_name: str, project_path: str | Path | None) -> str:
    label = (project_name or "").strip() or "-"
    if project_path is None:
        return label
    try:
        path = Path(project_path).expanduser()
    except TypeError:
        return label

    branch = _git_branch_name(path)
    if not branch:
        return label
    return f"{label} [{branch}]"
