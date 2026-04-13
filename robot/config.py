from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

VERSION = "0.1.1"

PROVIDER_LABELS = {
    "codex": "Codex",
    "gemini": "Gemini",
    "copilot": "Copilot",
}

SUPPORTED_MODELS = {
    "codex": [
        "gpt-5.3-codex",
        "gpt-5.4",
        "gpt-5.2-codex",
        "gpt-5.1-codex-max",
        "gpt-5.2",
        "gpt-5.1-codex-mini",
    ],
    "gemini": [
        "gemini-2.5-pro",
        "gemini-2.5-flash",
    ],
    "copilot": [
        "gpt-5",
        "claude-sonnet-4",
        "gemini-2.5-pro",
    ],
}

MODEL_CHOICES = {
    "codex": [
        ("gpt-5.3-codex", "gpt-5.3-codex | coding"),
        ("gpt-5.4", "gpt-5.4 | strong general"),
        ("gpt-5.2-codex", "gpt-5.2-codex | balanced coding"),
        ("gpt-5.1-codex-max", "gpt-5.1-codex-max | deep"),
        ("gpt-5.2", "gpt-5.2 | general"),
        ("gpt-5.1-codex-mini", "gpt-5.1-codex-mini | fast"),
    ],
    "gemini": [
        ("gemini-2.5-pro", "gemini-2.5-pro"),
        ("gemini-2.5-flash", "gemini-2.5-flash"),
    ],
    "copilot": [
        ("gpt-5", "gpt-5"),
        ("claude-sonnet-4", "claude-sonnet-4"),
        ("gemini-2.5-pro", "gemini-2.5-pro"),
    ],
}

MODEL_DESCRIPTIONS = {
    "codex": {
        "gpt-5.3-codex": "Latest frontier agentic coding model.",
        "gpt-5.4": "Latest frontier agentic coding model.",
        "gpt-5.2-codex": "Frontier agentic coding model.",
        "gpt-5.1-codex-max": "Codex-optimized flagship for deep and fast reasoning.",
        "gpt-5.2": "Latest frontier model with improvements across knowledge and coding.",
        "gpt-5.1-codex-mini": "Optimized for codex. Cheaper, faster, but less capable.",
    }
}


def _split_command(raw: str) -> list[str]:
    parts = shlex.split(raw, posix=False)
    return parts if parts else [raw]


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass(frozen=True)
class Settings:
    project_root: Path
    state_home: Path
    session_state_path: Path
    default_provider: str
    default_model: str
    provider_commands: dict[str, list[str]]
    provider_model_flags: dict[str, str]
    auto_dev_command: list[str]
    projects_roots: list[Path]
    brain_cli_command: list[str]
    brain_vault_name: str
    brain_vault_path: Path | None
    codex_bypass_approvals_and_sandbox: bool
    codex_skip_git_repo_check: bool


def normalize_provider(provider: str | None) -> str:
    candidate = (provider or "").strip().lower()
    return candidate if candidate in PROVIDER_LABELS else "codex"


def normalize_model(provider: str, model: str | None) -> str:
    normalized_provider = normalize_provider(provider)
    candidate = (model or "").strip()
    if not candidate:
        return SUPPORTED_MODELS[normalized_provider][0]
    if candidate in SUPPORTED_MODELS.get(normalized_provider, []):
        return candidate
    return candidate


def _resolve_brain_vault_path(root: Path, configured_path: str | None, vault_name: str) -> Path | None:
    if configured_path and configured_path.strip():
        return Path(configured_path).expanduser().resolve()

    candidates = [
        root / vault_name,
        root.parent / vault_name,
        root / "secondbrain",
        root.parent / "secondbrain",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def load_settings(project_root: Path | None = None) -> Settings:
    root = (project_root or Path(__file__).resolve().parent.parent).resolve()
    state_home = Path(os.getenv("ROBOT_STATE_HOME", str(root / ".robot_state"))).expanduser()
    state_home.mkdir(parents=True, exist_ok=True)

    default_provider = normalize_provider(os.getenv("ROBOT_DEFAULT_PROVIDER", "codex"))
    default_model = normalize_model(default_provider, os.getenv("ROBOT_DEFAULT_MODEL", "gpt-5.3-codex"))

    commands = {
        "codex": _split_command(os.getenv("ROBOT_CODEX_CMD", "codex")),
        "gemini": _split_command(os.getenv("ROBOT_GEMINI_CMD", "gemini")),
        "copilot": _split_command(os.getenv("ROBOT_COPILOT_CMD", "copilot")),
    }
    model_flags = {
        "codex": "-m",
        "gemini": os.getenv("ROBOT_GEMINI_MODEL_FLAG", "--model").strip() or "--model",
        "copilot": os.getenv("ROBOT_COPILOT_MODEL_FLAG", "--model").strip() or "--model",
    }
    auto_dev_command = _split_command(os.getenv("ROBOT_AUTO_DEV_CMD", "python auto_dev_agent.py"))
    brain_cli_command = _split_command(os.getenv("ROBOT_BRAIN_CLI_CMD", "obsidian"))
    brain_vault_name = (os.getenv("ROBOT_BRAIN_VAULT", "secondbrain") or "secondbrain").strip()
    brain_vault_path = _resolve_brain_vault_path(root, os.getenv("ROBOT_BRAIN_VAULT_PATH"), brain_vault_name)
    codex_bypass_approvals_and_sandbox = _env_flag("ROBOT_CODEX_BYPASS_APPROVALS_AND_SANDBOX", True)
    codex_skip_git_repo_check = _env_flag("ROBOT_CODEX_SKIP_GIT_REPO_CHECK", True)

    raw_roots = (os.getenv("ROBOT_PROJECTS_ROOTS", "") or "").strip()
    roots: list[Path] = []
    if raw_roots:
        for part in raw_roots.split(";"):
            text = part.strip()
            if text:
                roots.append(Path(text).expanduser())
    else:
        roots.append(root.parent)
        roots.append(root)

    unique_roots: list[Path] = []
    seen: set[str] = set()
    for candidate in roots:
        marker = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if marker in seen:
            continue
        seen.add(marker)
        unique_roots.append(candidate)

    return Settings(
        project_root=root,
        state_home=state_home,
        session_state_path=state_home / "robot_state.json",
        default_provider=default_provider,
        default_model=default_model,
        provider_commands=commands,
        provider_model_flags=model_flags,
        auto_dev_command=auto_dev_command,
        projects_roots=unique_roots,
        brain_cli_command=brain_cli_command,
        brain_vault_name=brain_vault_name,
        brain_vault_path=brain_vault_path,
        codex_bypass_approvals_and_sandbox=codex_bypass_approvals_and_sandbox,
        codex_skip_git_repo_check=codex_skip_git_repo_check,
    )
