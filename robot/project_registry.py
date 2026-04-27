from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from robot.config import Settings

PROJECT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _registry_path(settings: Settings) -> Path:
    return settings.state_home / "projects.json"


def _projects_notes_root(settings: Settings) -> Path:
    path = settings.state_home / "projects"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _project_notes_path(settings: Settings, name: str) -> Path:
    folder = _projects_notes_root(settings) / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "notes.md"


def _default_registry() -> dict[str, Any]:
    return {
        "version": 1,
        "active_project": "",
        "projects": {},
    }


def _load_registry(settings: Settings) -> dict[str, Any]:
    path = _registry_path(settings)
    if not path.exists():
        return _default_registry()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_registry()
    if not isinstance(data, dict):
        return _default_registry()
    data.setdefault("version", 1)
    data.setdefault("active_project", "")
    projects = data.get("projects")
    if not isinstance(projects, dict):
        data["projects"] = {}
    return data


def _save_registry(settings: Settings, registry: dict[str, Any]) -> None:
    path = _registry_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _normalize_name(name: str) -> str:
    return str(name or "").strip()


def _validate_project_name(name: str) -> str:
    normalized = _normalize_name(name)
    if not normalized:
        raise ValueError("project name is required")
    if not PROJECT_NAME_PATTERN.match(normalized):
        raise ValueError("project name must match [A-Za-z0-9][A-Za-z0-9._-]{0,63}")
    return normalized


def _resolve_path(settings: Settings, raw_path: str) -> Path:
    text = str(raw_path or "").strip()
    if not text:
        raise ValueError("project path is required")
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = (settings.project_root / candidate).resolve()
    else:
        candidate = candidate.resolve()
    return candidate


def _project_key(path: Path) -> str:
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:12]
    return f"proj-{digest}"


def register_project(settings: Settings, name: str, path: str) -> dict[str, Any]:
    project_name = _validate_project_name(name)
    project_path = _resolve_path(settings, path)
    timestamp = _now()

    registry = _load_registry(settings)
    projects = registry.setdefault("projects", {})
    if not isinstance(projects, dict):
        projects = {}
        registry["projects"] = projects

    existing = projects.get(project_name)
    if isinstance(existing, dict):
        created_at = str(existing.get("created_at") or timestamp)
        note_count = int(existing.get("note_count") or 0)
        last_used_at = str(existing.get("last_used_at") or "")
        last_activity_at = str(existing.get("last_activity_at") or "")
    else:
        created_at = timestamp
        note_count = 0
        last_used_at = ""
        last_activity_at = ""

    project = {
        "name": project_name,
        "key": _project_key(project_path),
        "path": str(project_path),
        "created_at": created_at,
        "updated_at": timestamp,
        "last_used_at": last_used_at,
        "last_activity_at": last_activity_at,
        "note_count": note_count,
    }
    projects[project_name] = project
    _save_registry(settings, registry)
    return project


def list_registered_projects(settings: Settings) -> tuple[list[dict[str, Any]], str]:
    registry = _load_registry(settings)
    projects = registry.get("projects")
    if not isinstance(projects, dict):
        return [], ""
    items = [value for value in projects.values() if isinstance(value, dict)]
    items.sort(key=lambda item: str(item.get("name") or "").lower())
    return items, str(registry.get("active_project") or "")


def _resolve_registered_project(registry: dict[str, Any], ref: str) -> dict[str, Any] | None:
    needle = str(ref or "").strip()
    if not needle:
        return None
    projects = registry.get("projects")
    if not isinstance(projects, dict):
        return None

    direct = projects.get(needle)
    if isinstance(direct, dict):
        return direct

    lowered = needle.lower()
    for item in projects.values():
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").lower() == lowered:
            return item
        if str(item.get("key") or "") == needle:
            return item

    partial = [
        item
        for item in projects.values()
        if isinstance(item, dict) and lowered in str(item.get("name") or "").lower()
    ]
    if len(partial) == 1:
        return partial[0]
    return None


def use_project(settings: Settings, ref: str) -> dict[str, Any] | None:
    registry = _load_registry(settings)
    project = _resolve_registered_project(registry, ref)
    if project is None:
        return None
    name = str(project.get("name") or "")
    now = _now()
    project["last_used_at"] = now
    project["last_activity_at"] = now
    project["updated_at"] = now
    registry["active_project"] = name
    projects = registry.setdefault("projects", {})
    if isinstance(projects, dict):
        projects[name] = project
    _save_registry(settings, registry)
    return project


def get_project(settings: Settings, ref: str) -> dict[str, Any] | None:
    registry = _load_registry(settings)
    return _resolve_registered_project(registry, ref)


def active_project(settings: Settings) -> dict[str, Any] | None:
    registry = _load_registry(settings)
    active_name = str(registry.get("active_project") or "")
    if not active_name:
        return None
    return _resolve_registered_project(registry, active_name)


def add_project_note(settings: Settings, ref: str, text: str) -> tuple[dict[str, Any], Path] | None:
    note_text = str(text or "").strip()
    if not note_text:
        raise ValueError("note text is required")

    registry = _load_registry(settings)
    project = _resolve_registered_project(registry, ref)
    if project is None:
        return None

    name = str(project.get("name") or "")
    notes_path = _project_notes_path(settings, name)
    timestamp = _now()
    with notes_path.open("a", encoding="utf-8") as handle:
        handle.write(f"- [{timestamp}] {note_text}\n")

    project["note_count"] = int(project.get("note_count") or 0) + 1
    project["last_activity_at"] = timestamp
    project["updated_at"] = timestamp
    projects = registry.setdefault("projects", {})
    if isinstance(projects, dict):
        projects[name] = project
    _save_registry(settings, registry)
    return project, notes_path


def project_status(project: dict[str, Any]) -> str:
    path = Path(str(project.get("path") or "")).expanduser()
    if not path.exists():
        return "missing"
    if not path.is_dir():
        return "not-dir"
    if (path / ".git").exists():
        return "git"
    return "dir"


def _run_git(path: Path, args: list[str]) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=2.5,
            cwd=path,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return False, ""
    if completed.returncode != 0:
        return False, (completed.stderr or "").strip()
    return True, (completed.stdout or "").strip()


def project_info(project: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(project.get("path") or "")).expanduser()
    result: dict[str, Any] = {
        "name": str(project.get("name") or ""),
        "key": str(project.get("key") or ""),
        "path": str(path),
        "exists": path.exists(),
        "is_dir": path.is_dir(),
        "status": project_status(project),
        "git_available": False,
        "is_git_repo": False,
        "branch": "-",
        "dirty": False,
        "remote_origin": "-",
    }
    if not path.exists() or not path.is_dir():
        return result

    ok_git, _ = _run_git(path, ["--version"])
    result["git_available"] = ok_git
    if not ok_git:
        return result

    ok_repo, _ = _run_git(path, ["rev-parse", "--is-inside-work-tree"])
    result["is_git_repo"] = ok_repo
    if not ok_repo:
        return result

    ok_branch, branch = _run_git(path, ["rev-parse", "--abbrev-ref", "HEAD"])
    if ok_branch and branch:
        result["branch"] = branch

    ok_dirty, dirty = _run_git(path, ["status", "--porcelain"])
    if ok_dirty:
        result["dirty"] = bool(dirty.strip())

    ok_remote, remote = _run_git(path, ["remote", "get-url", "origin"])
    if ok_remote and remote:
        result["remote_origin"] = remote
    return result


def project_doctor(project: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(project.get("path") or "")).expanduser()
    checks: list[str] = []
    issues: list[str] = []

    checks.append(f"path={path}")
    if not path.exists():
        issues.append("path missing")
        return {"checks": checks, "issues": issues}
    if not path.is_dir():
        issues.append("path is not directory")
        return {"checks": checks, "issues": issues}

    checks.append("path exists")
    checks.append("path is directory")
    checks.append(f"perm_read={'yes' if os.access(path, os.R_OK) else 'no'}")
    checks.append(f"perm_write={'yes' if os.access(path, os.W_OK) else 'no'}")
    checks.append(f"perm_exec={'yes' if os.access(path, os.X_OK) else 'no'}")

    if not os.access(path, os.R_OK):
        issues.append("no read permission")
    if not os.access(path, os.W_OK):
        issues.append("no write permission")

    ok_git, _ = _run_git(path, ["--version"])
    checks.append(f"git_available={'yes' if ok_git else 'no'}")
    if not ok_git:
        issues.append("git command unavailable")
        return {"checks": checks, "issues": issues}

    ok_repo, _ = _run_git(path, ["rev-parse", "--is-inside-work-tree"])
    checks.append(f"is_git_repo={'yes' if ok_repo else 'no'}")
    if not ok_repo:
        issues.append("not a git repo")
    return {"checks": checks, "issues": issues}
