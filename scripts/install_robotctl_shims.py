from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
USER_BIN = Path.home() / ".local" / "bin"


def _windows_python() -> Path:
    return ROOT / ".venv" / "Scripts" / "python.exe"


def _posix_python() -> Path:
    return ROOT / ".venv" / "bin" / "python"


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _install_windows_cmd() -> Path:
    target = USER_BIN / "robotctl.cmd"
    python_path = _windows_python()
    content = (
        "@echo off\n"
        "setlocal\n"
        f"\"{python_path}\" \"{ROOT / 'robotctl.py'}\" %*\n"
    )
    _write_text(target, content)
    return target


def _install_posix_sh() -> Path:
    target = USER_BIN / "robotctl"
    python_path = _posix_python()
    content = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"exec \"{python_path}\" \"{ROOT / 'robotctl.py'}\" \"$@\"\n"
    )
    _write_text(target, content)
    current_mode = target.stat().st_mode
    target.chmod(current_mode | 0o111)
    return target


def _remove_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()


def main() -> None:
    installed: list[Path] = []
    if os.name == "nt":
        _remove_if_exists(USER_BIN / "robotctl")
        installed.append(_install_windows_cmd())
    else:
        installed.append(_install_posix_sh())

    print("Installed robotctl shims:")
    for path in installed:
        print(f"- {path}")


if __name__ == "__main__":
    main()
