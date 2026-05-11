"""Security utilities for robot project."""
from __future__ import annotations

import hmac
import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Permission mode constants
# ---------------------------------------------------------------------------
PROJECTS_ROOT = Path("~/projects").expanduser()
ROBOT_ROOT    = Path("~/robot").expanduser()
TELEAPP       = Path("~/teleapp").expanduser()

PERMISSION_MODES = ("user", "developer", "superuser")
PERMISSION_CONFIG_PATH = Path(
    os.getenv("ROBOT_PERMISSIONS_PATH", str(Path.home() / ".config" / "robot" / "permissions.json"))
)

# ---------------------------------------------------------------------------
# Permission config (lazy-loaded, module-level singleton)
# ---------------------------------------------------------------------------
_permission_config: dict | None = None


def _load_permission_config() -> dict:
    """Load and validate permissions.json with HMAC verification."""
    global _permission_config
    if _permission_config is not None:
        return _permission_config

    path = PERMISSION_CONFIG_PATH
    if not path.exists():
        logging.warning("Permission config not found at %s — using defaults", path)
        _permission_config = _default_permission_config()
        return _permission_config

    try:
        raw = path.read_text()
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        logging.error("Failed to read permission config at %s: %s", path, exc)
        _permission_config = _default_permission_config()
        return _permission_config

    key = os.getenv("ROBOT_PERMISSION_KEY", "")
    if key:
        try:
            stored_sig = data.get("signature", "")
            payload = json.dumps(data["rules"], sort_keys=True, ensure_ascii=False)
            expected = hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(stored_sig, expected):
                logging.error("HMAC signature mismatch for %s — rejecting config", path)
                _permission_config = _default_permission_config()
                return _permission_config
        except (KeyError, TypeError) as exc:
            logging.error("Permission config missing rules or signature: %s", exc)
            _permission_config = _default_permission_config()
            return _permission_config
    else:
        logging.warning("ROBOT_PERMISSION_KEY not set — HMAC verification skipped")

    _permission_config = data
    return _permission_config


def _default_permission_config() -> dict:
    return {
        "version": "1.0",
        "rules": {
            "user": {
                "whitelist": [str(PROJECTS_ROOT)],
                "blacklist": [str(ROBOT_ROOT), str(TELEAPP)],
            },
            "developer": {
                "whitelist": [str(PROJECTS_ROOT), str(ROBOT_ROOT)],
                "blacklist": [str(TELEAPP)],
            },
            "superuser": {
                "whitelist": ["*"],
                "blacklist": [],
            },
        },
        "signature": "",
    }


def _expand_config_paths(paths: list[str]) -> list[Path]:
    """Replace ${HOME} in paths and return list of expanded Path objects.

    The sentinel "*" is preserved as-is (not resolved) to mean 'allow all'.
    """
    result: list[Path] = []
    home = str(Path.home())
    for p in paths:
        if p == "*":
            result.append(Path("*"))
        else:
            p = p.replace("${HOME}", home)
            result.append(Path(p).expanduser().resolve())
    return result


def get_mode_rules(mode: Literal["user", "developer", "superuser"]) -> dict:
    """Return whitelist/blacklist for the given mode, with ${HOME} expanded."""
    config = _load_permission_config()
    rules = config.get("rules", {}).get(mode, {})
    whitelist = _expand_config_paths(rules.get("whitelist", []))
    blacklist = _expand_config_paths(rules.get("blacklist", []))
    return {"whitelist": whitelist, "blacklist": blacklist}


def check_write_allowed(abs_path: Path, mode: Literal["user", "developer", "superuser"] = "user") -> bool:
    """
    Check if a path is writable under the given permission mode.

    Args:
        abs_path: Absolute path to check
        mode: Permission mode — 'user', 'developer', or 'superuser'

    Returns:
        True if write is allowed, False otherwise
    """
    if mode == "superuser":
        return True

    rules = get_mode_rules(mode)
    blacklist = rules["blacklist"]
    whitelist = rules["whitelist"]

    resolved = abs_path.resolve()

    # Blacklist blocks first
    for blocked in blacklist:
        try:
            resolved.relative_to(blocked)
            return False
        except ValueError:
            continue

    # Whitelist check
    for allowed in whitelist:
        # "*" means allow everything not on blacklist
        if str(allowed) == "*":
            return True
        try:
            resolved.relative_to(allowed)
            return True
        except ValueError:
            continue

    return False


class SecurityError(Exception):
    """Raised when a security violation is detected."""
    pass


def validate_path_traversal(
    target_path: Path,
    allowed_roots: list[Path],
    *,
    must_exist: bool = False,
) -> Path:
    """
    Validate that a path is within allowed roots and doesn't contain traversal attacks.

    Args:
        target_path: The path to validate
        allowed_roots: List of allowed root directories
        must_exist: If True, path must exist

    Returns:
        Resolved absolute path

    Raises:
        SecurityError: If path is outside allowed roots or contains suspicious patterns
    """
    # Resolve to absolute path
    try:
        resolved = target_path.resolve()
    except (OSError, RuntimeError) as exc:
        raise SecurityError(f"Cannot resolve path: {exc}") from exc

    # Check for suspicious patterns before resolution
    path_str = str(target_path)
    suspicious_patterns = [
        r'\.\.[/\\]',  # Parent directory traversal
        r'[/\\]\.\.[/\\]',
        r'^\.\./',
        r'^\.\.$',
    ]

    for pattern in suspicious_patterns:
        if re.search(pattern, path_str):
            raise SecurityError(f"Path contains suspicious pattern: {path_str}")

    # Verify resolved path is within allowed roots
    is_allowed = False
    for root in allowed_roots:
        try:
            root_resolved = root.resolve()
            # Check if target is under this root
            resolved.relative_to(root_resolved)
            is_allowed = True
            break
        except (ValueError, OSError):
            continue

    if not is_allowed:
        raise SecurityError(
            f"Path outside allowed directories: {resolved}\n"
            f"Allowed roots: {', '.join(str(r) for r in allowed_roots)}"
        )

    # Check existence if required
    if must_exist and not resolved.exists():
        raise SecurityError(f"Path does not exist: {resolved}")

    return resolved


def validate_command_args(args: list[str]) -> list[str]:
    """
    Validate command arguments to prevent injection attacks.

    Args:
        args: List of command arguments

    Returns:
        Validated arguments

    Raises:
        SecurityError: If arguments contain suspicious patterns
    """
    validated: list[str] = []

    # Dangerous patterns that could lead to command injection
    dangerous_patterns = [
        r'[;&|`$]',  # Shell metacharacters
        r'\$\(',     # Command substitution
        r'`',        # Backtick command substitution
        r'>\s*/',    # Redirect to absolute path
        r'<\s*/',    # Read from absolute path
    ]

    for arg in args:
        arg_str = str(arg)

        # Check for dangerous patterns
        for pattern in dangerous_patterns:
            if re.search(pattern, arg_str):
                raise SecurityError(
                    f"Argument contains dangerous pattern: {arg_str}\n"
                    f"Pattern: {pattern}"
                )

        # Validate email addresses (for sendmail)
        if '@' in arg_str and not _is_valid_email(arg_str):
            raise SecurityError(f"Invalid email format: {arg_str}")

        validated.append(arg_str)

    return validated


def _is_valid_email(email: str) -> bool:
    """Basic email validation."""
    # Simple regex for basic email validation
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def sanitize_file_size(file_path: Path, max_size_mb: int = 50) -> None:
    """
    Check if file size is within acceptable limits.

    Args:
        file_path: Path to file
        max_size_mb: Maximum allowed size in MB

    Raises:
        SecurityError: If file is too large
    """
    if not file_path.exists():
        raise SecurityError(f"File does not exist: {file_path}")

    size_bytes = file_path.stat().st_size
    size_mb = size_bytes / (1024 * 1024)

    if size_mb > max_size_mb:
        raise SecurityError(
            f"File too large: {size_mb:.2f}MB (max: {max_size_mb}MB)\n"
            f"Path: {file_path}"
        )


def sanitize_error_message(error_msg: str, project_root: Path) -> str:
    """
    Remove sensitive information from error messages.

    Args:
        error_msg: Original error message
        project_root: Project root path to redact

    Returns:
        Sanitized error message
    """
    sanitized = str(error_msg)

    # Replace absolute paths with relative ones
    try:
        root_str = str(project_root.resolve())
        sanitized = sanitized.replace(root_str, "<project_root>")
    except (OSError, RuntimeError):
        pass

    # Replace home directory
    try:
        home_str = str(Path.home())
        sanitized = sanitized.replace(home_str, "~")
    except RuntimeError:
        pass

    # Remove potential API keys or tokens (basic pattern)
    sanitized = re.sub(
        r'["\']?[a-zA-Z0-9_-]{32,}["\']?',
        '<REDACTED>',
        sanitized
    )

    return sanitized
