from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from robot.config import Settings


def _token_fingerprint(token: str) -> str:
    text = (token or "").strip()
    if not text:
        return "-"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest[:12]}"


def _lock_owner_pid(lock_path: Path) -> str:
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
    except OSError:
        return "-"
    return raw if raw.isdigit() else "-"


def _windows_python_processes() -> list[dict[str, str]]:
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.Name -match '^(python|py)(\\\\.exe)?$' } | "
                "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=4,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    if completed.returncode != 0 or not completed.stdout.strip():
        return []

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []

    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return []

    result: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("ProcessId") or "").strip()
        name = str(item.get("Name") or "").strip()
        cmd = str(item.get("CommandLine") or "").strip()
        if pid:
            result.append({"pid": pid, "name": name, "cmd": cmd})
    return result


def _posix_python_processes() -> list[dict[str, str]]:
    try:
        completed = subprocess.run(
            ["ps", "-eo", "pid=,comm=,args="],
            check=False,
            capture_output=True,
            text=True,
            timeout=4,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    if completed.returncode != 0:
        return []

    result: list[dict[str, str]] = []
    for line in completed.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=2)
        if len(parts) < 2:
            continue
        pid = parts[0]
        name = parts[1]
        cmd = parts[2] if len(parts) > 2 else ""
        lower_name = name.lower()
        if "python" not in lower_name and lower_name != "py":
            continue
        result.append({"pid": pid, "name": name, "cmd": cmd})
    return result


def _python_processes() -> list[dict[str, str]]:
    if os.name == "nt":
        return _windows_python_processes()
    return _posix_python_processes()


def _robot_like_pids(processes: list[dict[str, str]]) -> list[str]:
    pids: list[str] = []
    for proc in processes:
        cmd = str(proc.get("cmd") or "").lower()
        if "-m robot" in cmd or "robot\\__main__.py" in cmd or "robot/__main__.py" in cmd:
            pids.append(str(proc.get("pid") or "").strip())
    return [pid for pid in pids if pid]


def build_doctor_report(settings: Settings) -> str:
    lock_path = settings.project_root / ".robot_state" / "robot.lock"
    lock_owner = _lock_owner_pid(lock_path)
    token_fingerprint = _token_fingerprint(os.getenv("TELEAPP_TOKEN", ""))
    all_python = _python_processes()
    robot_pids = _robot_like_pids(all_python)
    current_pid = str(os.getpid())
    peer_robot_pids = [pid for pid in robot_pids if pid != current_pid]

    lines = [
        "robot doctor",
        f"pid: {current_pid}",
        f"lock_path: {lock_path}",
        f"lock_owner_pid: {lock_owner}",
        f"token_fingerprint: {token_fingerprint}",
        f"python_processes: {len(all_python)}",
        f"robot_like_pids: {', '.join(robot_pids) if robot_pids else '-'}",
        f"peer_robot_pids: {', '.join(peer_robot_pids) if peer_robot_pids else '-'}",
        f"potential_local_conflict: {'yes' if peer_robot_pids else 'no'}",
        "note: remote instances with the same bot token can still cause Conflict.",
    ]
    return "\n".join(lines)

