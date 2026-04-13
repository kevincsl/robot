from __future__ import annotations

import sys
from pathlib import Path

import tomllib


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_toml(path: Path) -> dict:
    return tomllib.loads(_read_text(path))


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    failures: list[str] = []

    robot_pyproject = _load_toml(root / "pyproject.toml")
    vendor_pyproject = _load_toml(root / "_vendor_teleapp" / "pyproject.toml")

    robot_version = str(robot_pyproject.get("project", {}).get("version", "")).strip()
    vendor_version = str(vendor_pyproject.get("project", {}).get("version", "")).strip()

    if not robot_version:
        failures.append("robot version missing in pyproject.toml")
    if not vendor_version:
        failures.append("teleapp version missing in _vendor_teleapp/pyproject.toml")

    config_text = _read_text(root / "robot" / "config.py")
    version_marker = f'VERSION = "{robot_version}"'
    if robot_version and version_marker not in config_text:
        failures.append(f"robot/config.py VERSION does not match pyproject version ({robot_version})")

    sync_targets = [
        "state.py",
        "supervisor.py",
        "telegram_gateway.py",
    ]
    for name in sync_targets:
        src = root / "_vendor_teleapp" / "teleapp" / name
        build = root / "_vendor_teleapp" / "build" / "lib" / "teleapp" / name
        if not src.exists() or not build.exists():
            failures.append(f"missing sync target: {name}")
            continue
        if _read_text(src) != _read_text(build):
            failures.append(f"vendor mismatch: {src.relative_to(root)} != {build.relative_to(root)}")

    if failures:
        print("release consistency check: FAILED")
        for item in failures:
            print(f"- {item}")
        return 1

    print("release consistency check: OK")
    print(f"- robot version: {robot_version}")
    print(f"- teleapp version: {vendor_version}")
    print("- vendor sync targets: state.py, supervisor.py, telegram_gateway.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
