from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
RESTART_POLICIES = ("never", "on-failure", "always")
PROXY_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
DEFAULT_PROVIDER = "claude"
DEFAULT_MODEL = "claude-sonnet-4-6"


class ControlError(RuntimeError):
    pass


@dataclass(frozen=True)
class RobotConfigRef:
    name: str
    env_file: Path
    robot_id: str


@dataclass(frozen=True)
class LaunchSpec:
    config: RobotConfigRef
    python_path: Path
    command: list[str]
    env: dict[str, str]
    teleapp_app: str
    provider: str
    model: str


def _add_help_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-h",
        "/h",
        "--help",
        action="help",
        default=argparse.SUPPRESS,
        help="Show this help message and exit.",
    )


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _repo_root(root: Path | None = None) -> Path:
    return (root or ROOT).resolve()


def _state_home(root: Path) -> Path:
    path = root / ".robot_state"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _logs_home(root: Path) -> Path:
    path = _state_home(root) / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ctl_home(root: Path) -> Path:
    path = _state_home(root) / "ctl"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _state_file(root: Path, name: str) -> Path:
    return _ctl_home(root) / f"{name}.json"


def _stop_file(root: Path, name: str) -> Path:
    return _ctl_home(root) / f"{name}.stop"


def _log_file(root: Path, name: str) -> Path:
    return _logs_home(root) / f"{name}.log"


def _legacy_root_logs_home(root: Path) -> Path:
    path = _logs_home(root) / "legacy-root"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _migrate_legacy_root_logs(root: Path) -> list[tuple[Path, Path]]:
    moved: list[tuple[Path, Path]] = []
    for source in sorted(root.glob("*.log")):
        target = _legacy_root_logs_home(root) / source.name
        if target.exists():
            stem = target.stem
            suffix = target.suffix
            index = 1
            while True:
                candidate = target.with_name(f"{stem}.{index}{suffix}")
                if not candidate.exists():
                    target = candidate
                    break
                index += 1
        source.replace(target)
        moved.append((source, target))
    return moved


def _read_state(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    temp_path = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    for attempt in range(8):
        try:
            temp_path.write_text(content, encoding="utf-8")
            temp_path.replace(path)
            return
        except PermissionError:
            if attempt >= 7:
                raise
            time.sleep(0.05 * (attempt + 1))
        finally:
            temp_path.unlink(missing_ok=True)


def _env_values(path: Path) -> dict[str, str]:
    values = dotenv_values(path)
    result: dict[str, str] = {}
    for key, value in values.items():
        if key is None:
            continue
        clean_key = str(key).lstrip("\ufeff").strip()
        if not clean_key:
            continue
        result[clean_key] = "" if value is None else str(value)
    return result


def _default_python_path(root: Path) -> Path:
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def _venv_python(root: Path) -> Path:
    candidate = _default_python_path(root)
    if candidate.exists():
        return candidate
    raise ControlError(
        f"Missing venv python: {candidate}\n"
        "Run bootstrap_robot.bat / bootstrap_robot.sh first."
    )


def _iter_config_candidates(root: Path) -> dict[str, Path]:
    results: dict[str, Path] = {}

    robots_dir = root / ".robots"
    if robots_dir.is_dir():
        for path in sorted(robots_dir.glob("*.env")):
            results[path.stem] = path

    return results


def resolve_config(root: Path, name: str) -> RobotConfigRef:
    root = _repo_root(root)
    clean_name = (name or "").strip() or "default"
    env_file = root / ".robots" / f"{clean_name}.env"
    if not env_file.is_file():
        legacy_env_file = root / f".env.{clean_name}"
        if clean_name == "default" and (root / ".env").is_file():
            raise ControlError(
                f"Legacy config naming is no longer supported. "
                f"Move {root / '.env'} -> {env_file}"
            )
        if legacy_env_file.is_file():
            raise ControlError(
                f"Legacy config naming is no longer supported. "
                f"Move {legacy_env_file} -> {env_file}"
            )
        raise ControlError(
            f"Config '{clean_name}' not found. Expected: {env_file}"
        )

    values = _env_values(env_file)
    robot_id = (values.get("ROBOT_ID") or clean_name or "robot-unknown").strip() or clean_name
    return RobotConfigRef(name=clean_name, env_file=env_file.resolve(), robot_id=robot_id)


def discover_configs(root: Path) -> list[RobotConfigRef]:
    root = _repo_root(root)
    items: list[RobotConfigRef] = []
    for name, env_file in sorted(_iter_config_candidates(root).items()):
        values = _env_values(env_file)
        robot_id = (values.get("ROBOT_ID") or name).strip() or name
        items.append(RobotConfigRef(name=name, env_file=env_file.resolve(), robot_id=robot_id))
    return items


def build_launch_spec(root: Path, config: RobotConfigRef) -> LaunchSpec:
    root = _repo_root(root)
    python_path = _venv_python(root)
    values = _env_values(config.env_file)
    token = (values.get("TELEAPP_TOKEN") or "").strip()
    if not token:
        raise ControlError(f"TELEAPP_TOKEN is missing in {config.env_file}")

    teleapp_app = (values.get("TELEAPP_APP") or "robot.py").strip() or "robot.py"
    provider = (values.get("ROBOT_DEFAULT_PROVIDER") or "codex").strip() or "codex"
    model = (values.get("ROBOT_DEFAULT_MODEL") or "").strip() or "default"

    env = os.environ.copy()
    env.update(values)
    env["ROBOT_ENV_FILE"] = str(config.env_file)
    env["TELEAPP_APP"] = teleapp_app
    env["TELEAPP_PYTHON"] = str(python_path)
    env.setdefault("TELEAPP_HOT_RELOAD", "0")
    env.setdefault("TELEAPP_WATCH_MODE", "app-file-only")

    pythonpath = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = (
        f"{root}{os.pathsep}{pythonpath}" if pythonpath else str(root)
    )

    for key in PROXY_KEYS:
        env[key] = ""

    command = [
        str(python_path),
        "-m",
        "teleapp",
        teleapp_app,
        "--python",
        str(python_path),
    ]
    return LaunchSpec(
        config=config,
        python_path=python_path,
        command=command,
        env=env,
        teleapp_app=teleapp_app,
        provider=provider,
        model=model,
    )


def _is_pid_running(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if completed.returncode != 0:
            return False
        output = (completed.stdout or "").strip()
        if not output:
            return False
        if output.startswith("INFO: No tasks are running"):
            return False
        return str(pid) in output
    try:
        os.kill(pid, 0)
    except (OSError, SystemError):
        return False
    return True


def _wait_for_exit(pid: int, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _is_pid_running(pid):
            return True
        time.sleep(0.2)
    return not _is_pid_running(pid)


def _terminate_process_tree(pid: int, timeout_seconds: float = 10.0) -> None:
    if not _is_pid_running(pid):
        return

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T"],
            capture_output=True,
            check=False,
            text=True,
        )
        if _wait_for_exit(pid, timeout_seconds):
            return
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
            text=True,
        )
        _wait_for_exit(pid, timeout_seconds)
        return

    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return
    if _wait_for_exit(pid, timeout_seconds):
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except OSError:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            return
    _wait_for_exit(pid, timeout_seconds)


def _join_command(args: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in args)


def _read_runtime_status(root: Path, robot_id: str) -> dict[str, Any]:
    if not robot_id:
        return {}
    path = _state_home(root) / "status" / f"{robot_id}.json"
    return _read_state(path)


def _effective_state_name(state: dict[str, Any]) -> str:
    current = str(state.get("state") or "unknown")
    supervisor_pid = int(state.get("supervisor_pid") or 0)
    child_pid = int(state.get("child_pid") or 0)

    if current in {"running", "starting", "stopping"} and not _is_pid_running(supervisor_pid):
        if _is_pid_running(child_pid):
            return "orphaned"
        return "stale"
    return current


def _render_status_entry(root: Path, state: dict[str, Any]) -> str:
    name = str(state.get("config_name") or "?")
    robot_id = str(state.get("robot_id") or "?")
    runtime_status = _read_runtime_status(root, robot_id)
    provider = str(
        runtime_status.get("current_provider")
        or state.get("provider")
        or "-"
    )
    model = str(
        runtime_status.get("current_model")
        or state.get("model")
        or "-"
    )
    active_chats = runtime_status.get("active_chats")
    queue_size = runtime_status.get("queue_size")
    log_file = str(state.get("log_file") or "-")
    restart_policy = str(state.get("restart_policy") or "never")
    restart_count = int(state.get("restart_count") or 0)
    supervisor_pid = int(state.get("supervisor_pid") or 0)
    child_pid = int(state.get("child_pid") or 0)
    status_text = _effective_state_name(state)

    parts = [
        f"{name}: {status_text}",
        f"robot_id={robot_id}",
        f"provider={provider}",
        f"model={model}",
        f"restart={restart_policy}/{restart_count}",
        f"supervisor={supervisor_pid or '-'}",
        f"child={child_pid or '-'}",
    ]
    if active_chats is not None:
        parts.append(f"chats={active_chats}")
    if queue_size is not None:
        parts.append(f"queue={queue_size}")
    lines = [" | ".join(parts)]
    lines.append(f"  env={state.get('env_file') or '-'}")
    lines.append(f"  log={log_file}")
    updated_at = str(state.get("updated_at") or "")
    if updated_at:
        lines.append(f"  updated={updated_at}")
    last_exit_code = state.get("last_exit_code")
    if last_exit_code is not None:
        lines.append(f"  last_exit={last_exit_code}")
    message = str(state.get("message") or "").strip()
    if message:
        lines.append(f"  note={message}")
    return "\n".join(lines)


def _synthetic_state(root: Path, config: RobotConfigRef) -> dict[str, Any]:
    return {
        "config_name": config.name,
        "env_file": str(config.env_file),
        "robot_id": config.robot_id,
        "state": "stopped",
        "provider": "-",
        "model": "-",
        "restart_policy": "never",
        "restart_count": 0,
        "updated_at": "-",
        "log_file": str(_log_file(root, config.name)),
    }


def _status_entries(root: Path, targets: list[str] | None = None) -> list[dict[str, Any]]:
    root = _repo_root(root)
    selected = {item.strip() for item in (targets or []) if item.strip()}
    state_dir = _ctl_home(root)
    results: dict[str, dict[str, Any]] = {}

    for path in sorted(state_dir.glob("*.json")):
        state = _read_state(path)
        name = str(state.get("config_name") or path.stem)
        if selected and name not in selected:
            continue
        state.setdefault("config_name", name)
        results[name] = state

    if selected:
        for name in sorted(selected):
            if name in results:
                continue
            try:
                config = resolve_config(root, name)
            except ControlError:
                continue
            results[name] = _synthetic_state(root, config)

    return [results[name] for name in sorted(results)]


def _tail_lines(path: Path, count: int) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return []
    return lines[-count:]


def _should_restart(policy: str, exit_code: int) -> bool:
    if policy == "always":
        return True
    if policy == "on-failure":
        return exit_code != 0
    return False


def _background_supervisor_command(
    root: Path,
    config_name: str,
    *,
    restart_policy: str,
    restart_delay: float,
    max_restarts: int,
) -> list[str]:
    python_path = _venv_python(root)
    return [
        str(python_path),
        "-m",
        "robot.control",
        "_supervise",
        config_name,
        "--restart",
        restart_policy,
        "--restart-delay",
        str(restart_delay),
        "--max-restarts",
        str(max_restarts),
        "--mode",
        "background",
    ]


def _spawn_background_supervisor(
    root: Path,
    config_name: str,
    *,
    restart_policy: str,
    restart_delay: float,
    max_restarts: int,
) -> int:
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = f"{root}{os.pathsep}{pythonpath}" if pythonpath else str(root)

    kwargs: dict[str, Any] = {
        "cwd": str(root),
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        kwargs["start_new_session"] = True

    process = subprocess.Popen(
        _background_supervisor_command(
            root,
            config_name,
            restart_policy=restart_policy,
            restart_delay=restart_delay,
            max_restarts=max_restarts,
        ),
        **kwargs,
    )
    return int(process.pid)


def _wait_for_supervisor_boot(
    root: Path,
    config_name: str,
    supervisor_pid: int,
    *,
    previous_updated_at: str = "",
    timeout_seconds: float = 3.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    state_path = _state_file(root, config_name)
    while time.monotonic() <= deadline:
        state = _read_state(state_path)
        current_updated_at = str(state.get("updated_at") or "")
        if (
            str(state.get("config_name") or "") == config_name
            and current_updated_at
            and current_updated_at != previous_updated_at
        ):
            return state
        if int(state.get("supervisor_pid") or 0) == int(supervisor_pid):
            return state
        if not _is_pid_running(supervisor_pid):
            return {}
        time.sleep(0.2)
    return {}


def _request_stop(root: Path, config_name: str) -> None:
    _stop_file(root, config_name).write_text("stop\n", encoding="utf-8")


def _stop_supervisor(root: Path, config_name: str, *, timeout_seconds: float = 10.0) -> bool:
    root = _repo_root(root)
    state = _read_state(_state_file(root, config_name))
    if not state:
        try:
            resolve_config(root, config_name)
        except ControlError:
            raise ControlError(f"Config '{config_name}' not found.")
        return False

    supervisor_pid = int(state.get("supervisor_pid") or 0)
    child_pid = int(state.get("child_pid") or 0)

    if supervisor_pid:
        _request_stop(root, config_name)
        if _wait_for_exit(supervisor_pid, timeout_seconds):
            return True
        _terminate_process_tree(supervisor_pid, timeout_seconds=timeout_seconds)

    if child_pid and _is_pid_running(child_pid):
        _terminate_process_tree(child_pid, timeout_seconds=timeout_seconds)

    updated = dict(state)
    updated["state"] = "stopped"
    updated["message"] = "Stopped by robotctl."
    updated["updated_at"] = _now()
    updated["child_pid"] = 0
    _write_state(_state_file(root, config_name), updated)
    return True


def _confirm(question: str, default: bool = False) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    answer = input(question + suffix).strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes", "1", "true", "on"}


def _input_value(prompt: str, *, default: str | None = None, required: bool = False) -> str:
    while True:
        suffix = f" [{default}]" if default else ""
        value = input(f"{prompt}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default
        if not required:
            return ""


def _api_url_env_key(provider: str) -> str:
    clean = "".join(ch if ch.isalnum() else "_" for ch in provider.upper()).strip("_")
    return f"ROBOT_{clean or 'CUSTOM'}_API_URL"


def _provider_api_key_name(provider: str) -> str:
    return {
        "codex": "OPENAI_API_KEY",
        "openai": "OPENAI_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
        "gemini": "GOOGLE_API_KEY",
    }.get(provider, "API_KEY")


def _config_file_path(root: Path, name: str) -> Path:
    return _repo_root(root) / ".robots" / f"{name}.env"


def _write_robot_config(
    root: Path,
    *,
    name: str,
    token: str,
    user_id: str,
    provider: str,
    model: str,
    api_url: str,
    api_key: str,
    codex_bypass_approvals: bool,
    codex_skip_git_repo_check: bool,
) -> Path:
    path = _config_file_path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"TELEAPP_TOKEN={token}",
        f"TELEAPP_ALLOWED_USER_ID={user_id}",
        "TELEAPP_APP=robot.py",
        "",
        f"ROBOT_ID={name}",
        f"ROBOT_DEFAULT_PROVIDER={provider}",
        f"ROBOT_DEFAULT_MODEL={model}",
        "",
        "ROBOT_CODEX_CMD=codex",
        "ROBOT_CLAUDE_CMD=claude",
        "ROBOT_GEMINI_CMD=gemini",
        f"ROBOT_CODEX_BYPASS_APPROVALS_AND_SANDBOX={'1' if codex_bypass_approvals else '0'}",
        f"ROBOT_CODEX_SKIP_GIT_REPO_CHECK={'1' if codex_skip_git_repo_check else '0'}",
    ]
    if api_url or api_key:
        lines.extend(["", "# API Configuration"])
    if api_url:
        lines.append(f"{_api_url_env_key(provider)}={api_url}")
    if api_key:
        lines.append(f"{_provider_api_key_name(provider)}={api_key}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="robotctl",
        description="Unified robot launcher and supervisor.",
        add_help=False,
        prefix_chars="-/",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    _add_help_flags(parser)

    subparsers = parser.add_subparsers(
        dest="command",
        metavar="{help,list,show,add,edit,delete,run,start,stop,restart,status,logs,doctor}",
    )

    help_parser = subparsers.add_parser(
        "help",
        add_help=False,
        prefix_chars="-/",
        help="Show help.",
    )
    _add_help_flags(help_parser)

    list_parser = subparsers.add_parser(
        "list",
        add_help=False,
        prefix_chars="-/",
        help="List robot configs.",
    )
    _add_help_flags(list_parser)

    show_parser = subparsers.add_parser(
        "show",
        add_help=False,
        prefix_chars="-/",
        help="Show one robot config file.",
    )
    _add_help_flags(show_parser)
    show_parser.add_argument("config", nargs="?", default="default")

    add_parser = subparsers.add_parser(
        "add",
        add_help=False,
        prefix_chars="-/",
        help="Create a robot config.",
    )
    _add_help_flags(add_parser)
    add_parser.add_argument("config", nargs="?")
    add_parser.add_argument("--token")
    add_parser.add_argument("--user-id")
    add_parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    add_parser.add_argument("--model", default=DEFAULT_MODEL)
    add_parser.add_argument("--api-url", default="")
    add_parser.add_argument("--api-key", default="")
    add_parser.add_argument("--force", action="store_true")
    add_parser.add_argument("--codex-bypass-approvals", action="store_true")
    add_parser.add_argument("--codex-skip-git-repo-check", action="store_true")

    edit_parser = subparsers.add_parser(
        "edit",
        add_help=False,
        prefix_chars="-/",
        help="Open a robot config in your editor.",
    )
    _add_help_flags(edit_parser)
    edit_parser.add_argument("config")

    delete_parser = subparsers.add_parser(
        "delete",
        add_help=False,
        prefix_chars="-/",
        help="Delete a robot config.",
    )
    _add_help_flags(delete_parser)
    delete_parser.add_argument("config")
    delete_parser.add_argument("--yes", action="store_true")

    run_parser = subparsers.add_parser(
        "run",
        add_help=False,
        prefix_chars="-/",
        help="Run one robot in the foreground.",
    )
    _add_help_flags(run_parser)
    run_parser.add_argument("config", nargs="?", default="default")
    run_parser.add_argument("--restart", choices=RESTART_POLICIES, default="on-failure")
    run_parser.add_argument("--restart-delay", type=float, default=3.0)
    run_parser.add_argument("--max-restarts", type=int, default=0)
    run_parser.add_argument("--force", action="store_true")

    start_parser = subparsers.add_parser(
        "start",
        add_help=False,
        prefix_chars="-/",
        help="Start one or all robots in the background.",
    )
    _add_help_flags(start_parser)
    start_parser.add_argument("target")
    start_parser.add_argument("--restart", choices=RESTART_POLICIES, default="on-failure")
    start_parser.add_argument("--restart-delay", type=float, default=3.0)
    start_parser.add_argument("--max-restarts", type=int, default=0)
    start_parser.add_argument("--force", action="store_true")

    stop_parser = subparsers.add_parser(
        "stop",
        add_help=False,
        prefix_chars="-/",
        help="Stop one or all robots.",
    )
    _add_help_flags(stop_parser)
    stop_parser.add_argument("target")

    restart_parser = subparsers.add_parser(
        "restart",
        add_help=False,
        prefix_chars="-/",
        help="Restart one or all robots in the background.",
    )
    _add_help_flags(restart_parser)
    restart_parser.add_argument("target")
    restart_parser.add_argument("--restart", choices=RESTART_POLICIES, default="on-failure")
    restart_parser.add_argument("--restart-delay", type=float, default=3.0)
    restart_parser.add_argument("--max-restarts", type=int, default=0)

    status_parser = subparsers.add_parser(
        "status",
        add_help=False,
        prefix_chars="-/",
        help="Show runtime status.",
    )
    _add_help_flags(status_parser)
    status_parser.add_argument("targets", nargs="*")
    status_parser.add_argument("--watch", action="store_true")
    status_parser.add_argument("--interval", type=float, default=2.0)

    logs_parser = subparsers.add_parser(
        "logs",
        add_help=False,
        prefix_chars="-/",
        help="Show robot logs.",
    )
    _add_help_flags(logs_parser)
    logs_parser.add_argument("config")
    logs_parser.add_argument("-n", type=int, default=100)
    logs_parser.add_argument("-f", "--follow", action="store_true")

    doctor_parser = subparsers.add_parser(
        "doctor",
        add_help=False,
        prefix_chars="-/",
        help="Run health checks for robot configs.",
    )
    _add_help_flags(doctor_parser)
    doctor_parser.add_argument("target", nargs="?", default="all")

    supervise_parser = subparsers.add_parser(
        "_supervise",
        add_help=False,
        prefix_chars="-/",
        help=argparse.SUPPRESS,
    )
    supervise_parser.add_argument("config")
    supervise_parser.add_argument("--restart", choices=RESTART_POLICIES, default="on-failure")
    supervise_parser.add_argument("--restart-delay", type=float, default=3.0)
    supervise_parser.add_argument("--max-restarts", type=int, default=0)
    supervise_parser.add_argument("--mode", choices=("background", "foreground"), default="background")

    hidden_action = next(
        (action for action in subparsers._choices_actions if action.dest == "_supervise"),
        None,
    )
    if hidden_action is not None:
        subparsers._choices_actions.remove(hidden_action)

    return parser


def _normalize_argv(argv: list[str]) -> list[str]:
    if not argv:
        return []
    aliases = {
        "ls": ["list"],
        "cat": ["show"],
        "del": ["delete"],
        "rm": ["delete"],
        "ps": ["status"],
        "startall": ["start", "all"],
        "stopall": ["stop", "all"],
    }
    first = argv[0].strip().lower()
    if first in aliases:
        return aliases[first] + argv[1:]
    return argv


def _select_targets(root: Path, raw_target: str) -> list[RobotConfigRef]:
    target = (raw_target or "").strip()
    if not target:
        raise ControlError("Missing target robot.")
    if target.lower() != "all":
        return [resolve_config(root, target)]
    configs = discover_configs(root)
    if not configs:
        raise ControlError("No robot configs found.")
    return configs


def cmd_help(parser: argparse.ArgumentParser, _args: argparse.Namespace, _root: Path) -> int:
    parser.print_help()
    return 0


def cmd_list(_parser: argparse.ArgumentParser, _args: argparse.Namespace, root: Path) -> int:
    configs = discover_configs(root)
    if not configs:
        print("No robot configs found.")
        return 0

    statuses = {item.get("config_name"): item for item in _status_entries(root)}
    for config in configs:
        state = statuses.get(config.name) or _synthetic_state(root, config)
        print(
            f"{config.name}: {_effective_state_name(state)} | "
            f"robot_id={config.robot_id} | env={config.env_file}"
        )
    return 0


def cmd_show(_parser: argparse.ArgumentParser, args: argparse.Namespace, root: Path) -> int:
    config = resolve_config(root, args.config)
    print(config.env_file.read_text(encoding="utf-8"))
    return 0


def cmd_add(_parser: argparse.ArgumentParser, args: argparse.Namespace, root: Path) -> int:
    name = (args.config or _input_value("Robot config name", required=True)).strip()
    path = _config_file_path(root, name)
    if path.exists() and not args.force:
        raise ControlError(f"Config already exists: {path}\nUse --force to overwrite.")

    token = (args.token or _input_value("Telegram Bot Token", required=True)).strip()
    user_id = (args.user_id or _input_value("Telegram User ID", required=True)).strip()
    provider = (args.provider or DEFAULT_PROVIDER).strip().lower() or DEFAULT_PROVIDER
    model = (args.model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    api_url = (args.api_url or _input_value("API URL", default="")).strip()
    api_key = (args.api_key or _input_value("API Key", default="")).strip()
    bypass = bool(args.codex_bypass_approvals) or _confirm(
        "Enable Codex bypass approvals and sandbox?",
        default=False,
    )
    skip_git = bool(args.codex_skip_git_repo_check) or _confirm(
        "Enable Codex skip git repo check?",
        default=False,
    )

    written = _write_robot_config(
        root,
        name=name,
        token=token,
        user_id=user_id,
        provider=provider,
        model=model,
        api_url=api_url,
        api_key=api_key,
        codex_bypass_approvals=bypass,
        codex_skip_git_repo_check=skip_git,
    )
    print(f"Created config: {written}")
    return 0


def cmd_edit(_parser: argparse.ArgumentParser, args: argparse.Namespace, root: Path) -> int:
    config = resolve_config(root, args.config)
    editor = os.environ.get("EDITOR") or ("notepad" if os.name == "nt" else "nano")
    parts = shlex.split(editor, posix=os.name != "nt")
    subprocess.run(parts + [str(config.env_file)], check=False)
    return 0


def cmd_delete(_parser: argparse.ArgumentParser, args: argparse.Namespace, root: Path) -> int:
    config = resolve_config(root, args.config)
    state = _read_state(_state_file(root, config.name))
    if state and _effective_state_name(state) in {"running", "starting", "stopping", "orphaned"}:
        raise ControlError(f"Config '{config.name}' is running. Stop it first.")
    if not args.yes and not _confirm(f"Delete config '{config.name}'?", default=False):
        print("Cancelled.")
        return 0
    config.env_file.unlink(missing_ok=True)
    _state_file(root, config.name).unlink(missing_ok=True)
    _stop_file(root, config.name).unlink(missing_ok=True)
    print(f"Deleted config: {config.name}")
    return 0


def _run_supervisor(
    root: Path,
    config_name: str,
    *,
    restart_policy: str,
    restart_delay: float,
    max_restarts: int,
    mode: str,
) -> int:
    root = _repo_root(root)
    config = resolve_config(root, config_name)
    spec = build_launch_spec(root, config)
    state_path = _state_file(root, config.name)
    stop_path = _stop_file(root, config.name)
    log_path = _log_file(root, config.name)
    stop_path.unlink(missing_ok=True)

    terminate_requested = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal terminate_requested
        terminate_requested = True

    for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        signum = getattr(signal, sig_name, None)
        if signum is None:
            continue
        try:
            signal.signal(signum, request_stop)
        except ValueError:
            continue

    restart_count = 0
    exit_code = 0

    while True:
        base_state = {
            "config_name": config.name,
            "env_file": str(config.env_file),
            "robot_id": config.robot_id,
            "provider": spec.provider,
            "model": spec.model,
            "teleapp_app": spec.teleapp_app,
            "command": _join_command(spec.command),
            "restart_policy": restart_policy,
            "restart_delay": restart_delay,
            "max_restarts": max_restarts,
            "restart_count": restart_count,
            "mode": mode,
            "supervisor_pid": os.getpid(),
            "updated_at": _now(),
            "log_file": str(log_path) if mode == "background" else "",
        }
        base_state["state"] = "starting"
        base_state["message"] = "Launching robot process."
        _write_state(state_path, base_state)

        stdout_target: Any = None
        stderr_target: Any = None
        log_handle = None
        try:
            if mode == "background":
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_handle = log_path.open("a", encoding="utf-8")
                log_handle.write(f"\n[{_now()}] starting {config.name}\n")
                log_handle.flush()
                stdout_target = log_handle
                stderr_target = subprocess.STDOUT

            child_kwargs: dict[str, Any] = {
                "cwd": str(root),
                "env": spec.env,
                "stdin": subprocess.DEVNULL,
                "stdout": stdout_target,
                "stderr": stderr_target,
            }
            if os.name == "nt":
                child_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                child_kwargs["start_new_session"] = True

            child = subprocess.Popen(spec.command, **child_kwargs)
        except OSError as exc:
            exit_code = 127
            failure_state = dict(base_state)
            failure_state["state"] = "failed"
            failure_state["last_exit_code"] = exit_code
            failure_state["updated_at"] = _now()
            failure_state["message"] = f"Launch failed: {exc}"
            _write_state(state_path, failure_state)
            if log_handle is not None:
                log_handle.close()
            return exit_code

        running_state = dict(base_state)
        running_state["state"] = "running"
        running_state["child_pid"] = child.pid
        running_state["started_at"] = _now()
        running_state["message"] = "Robot is running."
        _write_state(state_path, running_state)

        last_heartbeat = time.monotonic()
        stop_requested = False
        while True:
            exit_code = child.poll()
            if exit_code is not None:
                break
            if terminate_requested or stop_path.exists():
                stop_requested = True
                stopping_state = dict(running_state)
                stopping_state["state"] = "stopping"
                stopping_state["updated_at"] = _now()
                stopping_state["message"] = "Stop requested."
                _write_state(state_path, stopping_state)
                _terminate_process_tree(child.pid, timeout_seconds=8.0)
                continue
            if time.monotonic() - last_heartbeat >= 5.0:
                running_state["updated_at"] = _now()
                _write_state(state_path, running_state)
                last_heartbeat = time.monotonic()
            time.sleep(0.5)

        if log_handle is not None:
            log_handle.flush()
            log_handle.close()

        finished_state = dict(base_state)
        finished_state["child_pid"] = 0
        finished_state["last_exit_code"] = exit_code
        finished_state["updated_at"] = _now()
        if stop_requested or terminate_requested or stop_path.exists():
            stop_path.unlink(missing_ok=True)
            finished_state["state"] = "stopped"
            finished_state["message"] = "Stopped by request."
            _write_state(state_path, finished_state)
            return 0

        should_restart = _should_restart(restart_policy, int(exit_code))
        if max_restarts > 0 and restart_count >= max_restarts:
            should_restart = False

        finished_state["state"] = "crashed" if int(exit_code) != 0 else "stopped"
        finished_state["message"] = (
            f"Process exited with code {exit_code}."
            if not should_restart
            else f"Process exited with code {exit_code}; restarting in {restart_delay:.1f}s."
        )
        _write_state(state_path, finished_state)

        if not should_restart:
            return int(exit_code)

        restart_count += 1
        time.sleep(max(restart_delay, 0.0))


def cmd_run(_parser: argparse.ArgumentParser, args: argparse.Namespace, root: Path) -> int:
    config = resolve_config(root, args.config)
    existing = _read_state(_state_file(root, config.name))
    if existing and _effective_state_name(existing) in {"running", "starting", "stopping", "orphaned"}:
        if not args.force:
            raise ControlError(
                f"Config '{config.name}' is already running. Use --force to stop it first."
            )
        _stop_supervisor(root, config.name)
    return _run_supervisor(
        root,
        config.name,
        restart_policy=args.restart,
        restart_delay=args.restart_delay,
        max_restarts=args.max_restarts,
        mode="foreground",
    )


def cmd_start(_parser: argparse.ArgumentParser, args: argparse.Namespace, root: Path) -> int:
    root = _repo_root(root)
    targets = _select_targets(root, args.target)
    failed = False
    for config in targets:
        try:
            build_launch_spec(root, config)
        except ControlError as exc:
            failed = True
            print(f"{config.name}: failed to start | {exc}")
            continue

        state = _read_state(_state_file(root, config.name))
        previous_updated_at = str(state.get("updated_at") or "")
        if state and _effective_state_name(state) in {"running", "starting", "stopping", "orphaned"}:
            if not args.force:
                print(f"{config.name}: already running, skipped.")
                continue
            _stop_supervisor(root, config.name)
        pid = _spawn_background_supervisor(
            root,
            config.name,
            restart_policy=args.restart,
            restart_delay=args.restart_delay,
            max_restarts=args.max_restarts,
        )
        boot_state = _wait_for_supervisor_boot(
            root,
            config.name,
            pid,
            previous_updated_at=previous_updated_at,
        )
        if not boot_state and not _is_pid_running(pid):
            failed = True
            print(f"{config.name}: failed to start (supervisor exited early).")
            continue
        print(
            f"{config.name}: started in background | pid={pid} | log={_log_file(root, config.name)}"
        )
    return 1 if failed else 0


def cmd_stop(_parser: argparse.ArgumentParser, args: argparse.Namespace, root: Path) -> int:
    root = _repo_root(root)
    target = (args.target or "").strip()
    if target.lower() == "all":
        names = sorted({state.get("config_name") for state in _status_entries(root)} - {None})
        if not names:
            print("No running robot supervisors found.")
            return 0
        for name in names:
            stopped = _stop_supervisor(root, str(name))
            print(f"{name}: {'stopped' if stopped else 'not running'}")
        return 0

    stopped = _stop_supervisor(root, target)
    print(f"{target}: {'stopped' if stopped else 'not running'}")
    return 0


def cmd_restart(_parser: argparse.ArgumentParser, args: argparse.Namespace, root: Path) -> int:
    root = _repo_root(root)
    targets = _select_targets(root, args.target)
    for config in targets:
        try:
            _stop_supervisor(root, config.name)
        except ControlError:
            pass
        pid = _spawn_background_supervisor(
            root,
            config.name,
            restart_policy=args.restart,
            restart_delay=args.restart_delay,
            max_restarts=args.max_restarts,
        )
        print(
            f"{config.name}: restarted in background | pid={pid} | log={_log_file(root, config.name)}"
        )
    return 0


def _print_status(root: Path, targets: list[str] | None = None) -> None:
    entries = _status_entries(root, targets)
    if not entries:
        print("No robot supervisors found.")
        return
    for index, entry in enumerate(entries):
        if index:
            print()
        print(_render_status_entry(root, entry))


def cmd_status(_parser: argparse.ArgumentParser, args: argparse.Namespace, root: Path) -> int:
    root = _repo_root(root)
    if not args.watch:
        _print_status(root, args.targets)
        return 0

    try:
        while True:
            os.system("cls" if os.name == "nt" else "clear")
            print(f"robotctl status --watch ({_now()})\n")
            _print_status(root, args.targets)
            time.sleep(max(args.interval, 0.2))
    except KeyboardInterrupt:
        return 0


def cmd_logs(_parser: argparse.ArgumentParser, args: argparse.Namespace, root: Path) -> int:
    root = _repo_root(root)
    config = resolve_config(root, args.config)
    path = _log_file(root, config.name)
    if not path.exists():
        raise ControlError(f"Log file not found: {path}")

    for line in _tail_lines(path, max(args.n, 1)):
        print(line)

    if not args.follow:
        return 0

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(0, os.SEEK_END)
        try:
            while True:
                line = handle.readline()
                if line:
                    print(line, end="")
                    continue
                time.sleep(0.5)
        except KeyboardInterrupt:
            return 0


def _doctor_checks(root: Path, config: RobotConfigRef) -> tuple[list[str], list[str]]:
    infos: list[str] = []
    issues: list[str] = []
    raw = config.env_file.read_text(encoding="utf-8", errors="replace")
    values = _env_values(config.env_file)
    state = _read_state(_state_file(root, config.name))

    infos.append(f"env={config.env_file}")
    if raw.startswith("\ufeff"):
        infos.append("env_bom=utf8-sig (supported)")
    else:
        infos.append("env_bom=none")

    if (values.get("TELEAPP_TOKEN") or "").strip():
        infos.append("token=ok")
    else:
        issues.append("TELEAPP_TOKEN missing")

    python_path = _default_python_path(root)
    if python_path.exists():
        infos.append(f"venv_python=ok ({python_path})")
    else:
        issues.append(f"venv_python missing ({python_path})")

    log_path = _log_file(root, config.name)
    infos.append(f"log={log_path}")

    if state:
        effective = _effective_state_name(state)
        infos.append(f"state={effective}")
        supervisor_pid = int(state.get("supervisor_pid") or 0)
        child_pid = int(state.get("child_pid") or 0)
        if supervisor_pid and not _is_pid_running(supervisor_pid):
            issues.append(f"supervisor_pid dead ({supervisor_pid})")
        if child_pid and not _is_pid_running(child_pid):
            issues.append(f"child_pid dead ({child_pid})")
    else:
        infos.append("state=none")

    stop_path = _stop_file(root, config.name)
    if stop_path.exists():
        issues.append(f"stop flag exists ({stop_path})")

    return infos, issues


def cmd_doctor(_parser: argparse.ArgumentParser, args: argparse.Namespace, root: Path) -> int:
    root = _repo_root(root)
    targets = _select_targets(root, args.target)
    has_issue = False
    for index, config in enumerate(targets):
        infos, issues = _doctor_checks(root, config)
        if index:
            print()
        status = "ISSUE" if issues else "OK"
        print(f"{config.name}: {status}")
        for info in infos:
            print(f"  - {info}")
        for issue in issues:
            print(f"  - issue: {issue}")
        if issues:
            has_issue = True
    return 1 if has_issue else 0


def cmd_supervise(_parser: argparse.ArgumentParser, args: argparse.Namespace, root: Path) -> int:
    return _run_supervisor(
        root,
        args.config,
        restart_policy=args.restart,
        restart_delay=args.restart_delay,
        max_restarts=args.max_restarts,
        mode=args.mode,
    )


COMMAND_HANDLERS = {
    "help": cmd_help,
    "list": cmd_list,
    "show": cmd_show,
    "add": cmd_add,
    "edit": cmd_edit,
    "delete": cmd_delete,
    "run": cmd_run,
    "start": cmd_start,
    "stop": cmd_stop,
    "restart": cmd_restart,
    "status": cmd_status,
    "logs": cmd_logs,
    "doctor": cmd_doctor,
    "_supervise": cmd_supervise,
}


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    _migrate_legacy_root_logs(ROOT)
    normalized_argv = _normalize_argv(list(sys.argv[1:] if argv is None else argv))
    if not normalized_argv:
        parser.print_help()
        return 0
    args = parser.parse_args(normalized_argv)
    if not args.command:
        parser.print_help()
        return 0

    handler = COMMAND_HANDLERS.get(args.command)
    if handler is None:
        parser.print_help()
        return 2

    try:
        return int(handler(parser, args, ROOT) or 0)
    except ControlError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
