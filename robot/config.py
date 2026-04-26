from __future__ import annotations

import logging
import os
import shlex
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Use utf-8-sig so `.env` files saved with BOM still parse first key correctly.
# Don't override existing environment variables (security best practice)
load_dotenv(override=False, encoding="utf-8-sig")

# Log warning if .env file would override existing vars
if Path(".env").exists():
    from dotenv import dotenv_values
    env_vars = dotenv_values(".env")
    for key in env_vars:
        if key in os.environ:
            logging.warning(f"Environment variable {key} already set, not overriding from .env")

VERSION = "0.1.1"
DEFAULT_GOOGLE_CALENDAR_SCOPES = ("https://www.googleapis.com/auth/calendar.readonly",)

PROVIDER_LABELS = {
    "codex": "Codex",
    "claude": "Claude",
    "gemini": "Gemini",
}

SUPPORTED_MODELS = {
    "codex": [
        "gpt-5.3-codex",
        "gpt-5.4",
        "gpt-5.4-mini",
        "custom",
    ],
    "claude": [
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
        "custom",
    ],
    "gemini": [
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "custom",
    ],
}

MODEL_CHOICES = {
    "codex": [
        ("gpt-5.3-codex", "gpt-5.3-codex | coding"),
        ("gpt-5.4", "gpt-5.4 | strong general"),
        ("gpt-5.4-mini", "gpt-5.4-mini | fast general"),
        ("custom", "custom | specify any model"),
    ],
    "claude": [
        ("claude-opus-4-7", "claude-opus-4-7 | strongest"),
        ("claude-sonnet-4-6", "claude-sonnet-4-6 | balanced"),
        ("claude-haiku-4-5", "claude-haiku-4-5 | fastest"),
        ("custom", "custom | specify any model"),
    ],
    "gemini": [
        ("gemini-2.5-pro", "gemini-2.5-pro"),
        ("gemini-2.5-flash", "gemini-2.5-flash"),
        ("custom", "custom | specify any model"),
    ],
}

MODEL_DESCRIPTIONS = {
    "codex": {
        "gpt-5.3-codex": "Latest frontier agentic coding model.",
        "gpt-5.4": "Latest frontier agentic coding model.",
        "gpt-5.4-mini": "Fast and cost-efficient GPT-5.4 variant.",
        "custom": "Use any model (e.g. deepseek-chat, qwen-turbo).",
    },
    "claude": {
        "claude-opus-4-7": "Most capable model for complex tasks.",
        "claude-sonnet-4-6": "Balanced performance and speed.",
        "claude-haiku-4-5": "Fast and cost-efficient.",
        "custom": "Use any model (e.g. deepseek-chat, qwen-turbo).",
    },
    "gemini": {
        "gemini-2.5-pro": "Google's most capable model.",
        "gemini-2.5-flash": "Fast and efficient.",
        "custom": "Use any model (e.g. deepseek-chat, qwen-turbo).",
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
    robot_id: str
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
    claude_skip_permissions: bool
    custom_models: list[str]
    google_calendar_enabled: bool
    google_calendar_credentials_path: Path
    google_calendar_token_path: Path
    google_calendar_calendar_id: str
    google_calendar_scopes: tuple[str, ...]


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


def _default_codex_root(root: Path) -> Path:
    try:
        home = Path.home()
    except RuntimeError:
        # Some test environments clear HOME/USERPROFILE and Path.home() fails.
        return (root.parent / "codex").resolve()
    return (home / "codex").expanduser()


def _split_google_scopes(raw: str | None) -> tuple[str, ...]:
    text = (raw or "").strip()
    if not text:
        return DEFAULT_GOOGLE_CALENDAR_SCOPES
    normalized = text.replace(";", ",")
    parts = [item.strip() for item in normalized.split(",") if item.strip()]
    return tuple(parts) if parts else DEFAULT_GOOGLE_CALENDAR_SCOPES


def load_settings(project_root: Path | None = None) -> Settings:
    root = (project_root or Path(__file__).resolve().parent.parent).resolve()
    state_home = Path(os.getenv("ROBOT_STATE_HOME", str(root / ".robot_state"))).expanduser()
    state_home.mkdir(parents=True, exist_ok=True)

    robot_id = os.getenv("ROBOT_ID", "").strip()
    if not robot_id:
        token = os.getenv("TELEAPP_TOKEN", "")
        robot_id = f"robot-{hash(token) % 100000:05d}" if token else "robot-unknown"

    default_provider = normalize_provider(os.getenv("ROBOT_DEFAULT_PROVIDER", "codex"))
    default_model = normalize_model(default_provider, os.getenv("ROBOT_DEFAULT_MODEL", "gpt-5.3-codex"))

    commands = {
        "codex": _split_command(os.getenv("ROBOT_CODEX_CMD", "codex")),
        "claude": _split_command(os.getenv("ROBOT_CLAUDE_CMD", "claude")),
        "gemini": _split_command(os.getenv("ROBOT_GEMINI_CMD", "gemini")),
    }
    model_flags = {
        "codex": "-m",
        "claude": os.getenv("ROBOT_CLAUDE_MODEL_FLAG", "--model").strip() or "--model",
        "gemini": os.getenv("ROBOT_GEMINI_MODEL_FLAG", "--model").strip() or "--model",
    }
    auto_dev_command = _split_command(os.getenv("ROBOT_AUTO_DEV_CMD", "python auto_dev_agent.py"))
    brain_cli_command = _split_command(os.getenv("ROBOT_BRAIN_CLI_CMD", "obsidian"))
    brain_vault_name = (os.getenv("ROBOT_BRAIN_VAULT", "secondbrain") or "secondbrain").strip()
    brain_vault_path = _resolve_brain_vault_path(root, os.getenv("ROBOT_BRAIN_VAULT_PATH"), brain_vault_name)
    # Security-first defaults: dangerous Codex flags are opt-in.
    codex_bypass_approvals_and_sandbox = _env_flag("ROBOT_CODEX_BYPASS_APPROVALS_AND_SANDBOX", False)
    codex_skip_git_repo_check = _env_flag("ROBOT_CODEX_SKIP_GIT_REPO_CHECK", False)
    claude_skip_permissions = _env_flag("ROBOT_CLAUDE_SKIP_PERMISSIONS", False)
    raw_custom_models = os.getenv("ROBOT_CUSTOM_MODELS", "") or ""
    custom_models = [m.strip() for m in raw_custom_models.split(",") if m.strip()]
    google_calendar_enabled = _env_flag("ROBOT_GOOGLE_CALENDAR_ENABLED", False)
    google_calendar_credentials_path = Path(
        os.getenv(
            "ROBOT_GOOGLE_CALENDAR_CREDENTIALS_PATH",
            str(root / "google_calendar_credentials.json"),
        )
    ).expanduser()
    google_calendar_token_path = Path(
        os.getenv(
            "ROBOT_GOOGLE_CALENDAR_TOKEN_PATH",
            str(state_home / "google_calendar_token.json"),
        )
    ).expanduser()
    google_calendar_calendar_id = (
        os.getenv("ROBOT_GOOGLE_CALENDAR_ID", "primary") or "primary"
    ).strip() or "primary"
    google_calendar_scopes = _split_google_scopes(
        os.getenv("ROBOT_GOOGLE_CALENDAR_SCOPES")
    )

    raw_roots = (os.getenv("ROBOT_PROJECTS_ROOTS", "") or "").strip()
    roots: list[Path] = []
    if raw_roots:
        for part in raw_roots.split(";"):
            text = part.strip()
            if text:
                roots.append(Path(text).expanduser())
    else:
        roots.append(_default_codex_root(root))
        # Keep explicit project_root discoverable for local/dev/test runs.
        if project_root is not None:
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
        session_state_path=state_home / f"robot_state_{robot_id}.json",
        robot_id=robot_id,
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
        claude_skip_permissions=claude_skip_permissions,
        custom_models=custom_models,
        google_calendar_enabled=google_calendar_enabled,
        google_calendar_credentials_path=google_calendar_credentials_path,
        google_calendar_token_path=google_calendar_token_path,
        google_calendar_calendar_id=google_calendar_calendar_id,
        google_calendar_scopes=google_calendar_scopes,
    )
