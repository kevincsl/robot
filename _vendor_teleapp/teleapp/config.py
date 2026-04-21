from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


if load_dotenv is not None:
    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        load_dotenv(dotenv_path=cwd_env, override=True)
    else:
        load_dotenv(override=True)


def _read_int_env(name: str, default: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _read_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class TeleappConfig:
    telegram_token: str = ""
    allowed_user_id: int = 0
    telegram_chat_id: int | None = None
    app_path: Path | None = None
    python_executable: str = sys.executable
    hot_reload: bool = True
    auto_restart_on_crash: bool = True
    reload_quiet_seconds: int = 2
    reload_poll_seconds: int = 1
    restart_backoff_seconds: int = 1
    watch_mode: str = "app-dir"
    watch_paths: list[Path] | None = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="teleapp")
    parser.add_argument("app", nargs="?", help="Path to the hosted Python app")
    parser.add_argument("--token", default=os.getenv("TELEAPP_TOKEN", ""))
    parser.add_argument("--allowed-user-id", type=int, default=_read_int_env("TELEAPP_ALLOWED_USER_ID", 0))
    parser.add_argument("--chat-id", type=int, default=_read_int_env("TELEAPP_CHAT_ID", 0))
    parser.add_argument("--python", dest="python_executable", default=os.getenv("TELEAPP_PYTHON", sys.executable))
    parser.add_argument("--no-hot-reload", action="store_true")
    parser.add_argument("--no-auto-restart-on-crash", action="store_true")
    parser.add_argument("--reload-quiet-seconds", type=int, default=_read_int_env("TELEAPP_RELOAD_QUIET_SECONDS", 2))
    parser.add_argument("--reload-poll-seconds", type=int, default=_read_int_env("TELEAPP_RELOAD_POLL_SECONDS", 1))
    parser.add_argument("--restart-backoff-seconds", type=int, default=_read_int_env("TELEAPP_RESTART_BACKOFF_SECONDS", 1))
    parser.add_argument("--watch-mode", choices=["app-dir", "app-file-only"], default=os.getenv("TELEAPP_WATCH_MODE", "app-dir"))
    parser.add_argument("--watch", action="append", default=[])
    return parser


def load_config(args: argparse.Namespace) -> TeleappConfig:
    app_value = (args.app or os.getenv("TELEAPP_APP", "")).strip()
    if not app_value:
        raise SystemExit("Missing hosted app path. Use `teleapp <app.py>` or TELEAPP_APP.")

    app_path = Path(app_value).expanduser().resolve()
    if not app_path.exists():
        raise SystemExit(f"Hosted app not found: {app_path}")

    if not args.token.strip():
        raise SystemExit("Missing TELEAPP_TOKEN.")
    if args.allowed_user_id <= 0:
        raise SystemExit("TELEAPP_ALLOWED_USER_ID must be a positive integer.")

    watch_mode = str(getattr(args, "watch_mode", "app-dir") or "app-dir").strip().lower()
    watch_paths: list[Path] = []
    raw_watch = list(args.watch or [])
    if raw_watch:
        watch_paths.extend(Path(item).expanduser().resolve() for item in raw_watch)
    elif watch_mode == "app-file-only":
        watch_paths.append(app_path)
    else:
        watch_paths.append(app_path.parent)

    return TeleappConfig(
        telegram_token=args.token.strip(),
        allowed_user_id=args.allowed_user_id,
        telegram_chat_id=args.chat_id if args.chat_id > 0 else None,
        app_path=app_path,
        python_executable=args.python_executable,
        hot_reload=not getattr(args, "no_hot_reload", False) and _read_bool_env("TELEAPP_HOT_RELOAD", True),
        auto_restart_on_crash=not getattr(args, "no_auto_restart_on_crash", False)
        and _read_bool_env("TELEAPP_AUTO_RESTART_ON_CRASH", True),
        reload_quiet_seconds=max(1, args.reload_quiet_seconds),
        reload_poll_seconds=max(1, args.reload_poll_seconds),
        restart_backoff_seconds=max(0, getattr(args, "restart_backoff_seconds", 1)),
        watch_mode=watch_mode,
        watch_paths=watch_paths,
    )


def build_runtime_config(
    *,
    telegram_token: str | None = None,
    allowed_user_id: int | None = None,
    telegram_chat_id: int | None = None,
    app_path: str | Path | None = None,
    python_executable: str | None = None,
    hot_reload: bool | None = None,
    auto_restart_on_crash: bool | None = None,
    reload_quiet_seconds: int | None = None,
    reload_poll_seconds: int | None = None,
    restart_backoff_seconds: int | None = None,
    watch_mode: str | None = None,
    watch_paths: list[str | Path] | None = None,
) -> TeleappConfig:
    resolved_token = (telegram_token if telegram_token is not None else os.getenv("TELEAPP_TOKEN", "")).strip()
    resolved_allowed_user_id = (
        allowed_user_id if allowed_user_id is not None else _read_int_env("TELEAPP_ALLOWED_USER_ID", 0)
    )
    resolved_chat_id = (
        telegram_chat_id
        if telegram_chat_id is not None
        else (_read_int_env("TELEAPP_CHAT_ID", 0) or None)
    )
    resolved_python = python_executable or os.getenv("TELEAPP_PYTHON", sys.executable)
    resolved_hot_reload = hot_reload if hot_reload is not None else _read_bool_env("TELEAPP_HOT_RELOAD", True)
    resolved_auto_restart_on_crash = (
        auto_restart_on_crash
        if auto_restart_on_crash is not None
        else _read_bool_env("TELEAPP_AUTO_RESTART_ON_CRASH", True)
    )
    resolved_reload_quiet_seconds = (
        reload_quiet_seconds
        if reload_quiet_seconds is not None
        else _read_int_env("TELEAPP_RELOAD_QUIET_SECONDS", 2)
    )
    resolved_reload_poll_seconds = (
        reload_poll_seconds
        if reload_poll_seconds is not None
        else _read_int_env("TELEAPP_RELOAD_POLL_SECONDS", 1)
    )
    resolved_restart_backoff_seconds = (
        restart_backoff_seconds
        if restart_backoff_seconds is not None
        else _read_int_env("TELEAPP_RESTART_BACKOFF_SECONDS", 1)
    )
    resolved_watch_mode = (watch_mode or os.getenv("TELEAPP_WATCH_MODE", "app-dir")).strip().lower() or "app-dir"
    resolved_app_value = app_path if app_path is not None else os.getenv("TELEAPP_APP", "")
    resolved_app_path = (
        Path(resolved_app_value).expanduser().resolve()
        if str(resolved_app_value).strip()
        else None
    )
    resolved_watch_paths = [Path(path).expanduser().resolve() for path in (watch_paths or [])]
    if resolved_app_path is not None and not resolved_watch_paths:
        if resolved_watch_mode == "app-file-only":
            resolved_watch_paths = [resolved_app_path]
        else:
            resolved_watch_paths = [resolved_app_path.parent]
    return TeleappConfig(
        telegram_token=resolved_token,
        allowed_user_id=resolved_allowed_user_id,
        telegram_chat_id=resolved_chat_id,
        app_path=resolved_app_path,
        python_executable=resolved_python,
        hot_reload=resolved_hot_reload,
        auto_restart_on_crash=resolved_auto_restart_on_crash,
        reload_quiet_seconds=max(1, resolved_reload_quiet_seconds),
        reload_poll_seconds=max(1, resolved_reload_poll_seconds),
        restart_backoff_seconds=max(0, resolved_restart_backoff_seconds),
        watch_mode=resolved_watch_mode,
        watch_paths=resolved_watch_paths,
    )
