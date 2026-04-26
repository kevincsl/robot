"""Security utilities for robot project."""
from __future__ import annotations

import re
from pathlib import Path


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
