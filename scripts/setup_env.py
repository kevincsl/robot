from __future__ import annotations

from pathlib import Path


ENV_PATH = Path(".env")
ENV_EXAMPLE_PATH = Path(".env.example")

TOKEN_KEY = "TELEAPP_TOKEN"
USER_KEY = "TELEAPP_ALLOWED_USER_ID"
APP_KEY = "TELEAPP_APP"
APP_DEFAULT = "robot.py"


def _is_placeholder(value: str) -> bool:
    text = (value or "").strip().lower()
    return (not text) or ("<your" in text and ">" in text)


def _read_env(path: Path) -> tuple[list[str], dict[str, str]]:
    if not path.exists():
        return [], {}
    lines = path.read_text(encoding="utf-8").splitlines()
    data: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return lines, data


def _prompt_value(label: str, current: str) -> str:
    if current and not _is_placeholder(current):
        raw = input(f"{label} [{current}] (Enter to keep): ").strip()
        return raw or current
    while True:
        raw = input(f"{label}: ").strip()
        if raw:
            return raw
        print(f"{label} cannot be empty.")


def _write_env(path: Path, original_lines: list[str], updates: dict[str, str]) -> None:
    keys_seen: set[str] = set()
    rendered: list[str] = []

    for line in original_lines:
        if "=" not in line or line.strip().startswith("#"):
            rendered.append(line)
            continue
        key, _ = line.split("=", 1)
        normalized = key.strip()
        if normalized in updates:
            rendered.append(f"{normalized}={updates[normalized]}")
            keys_seen.add(normalized)
        else:
            rendered.append(line)

    for key, value in updates.items():
        if key not in keys_seen:
            rendered.append(f"{key}={value}")

    path.write_text("\n".join(rendered).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    if not ENV_PATH.exists() and ENV_EXAMPLE_PATH.exists():
        ENV_PATH.write_text(ENV_EXAMPLE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        print("Created .env from .env.example")

    original_lines, env_map = _read_env(ENV_PATH)

    updates = {
        TOKEN_KEY: _prompt_value(TOKEN_KEY, env_map.get(TOKEN_KEY, "")),
        USER_KEY: _prompt_value(USER_KEY, env_map.get(USER_KEY, "")),
        APP_KEY: env_map.get(APP_KEY, "").strip() or APP_DEFAULT,
    }

    _write_env(ENV_PATH, original_lines, updates)
    print("Updated .env with TELEAPP settings.")


if __name__ == "__main__":
    main()
