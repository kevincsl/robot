from __future__ import annotations

import atexit
import hashlib
import os
import sys
import tempfile
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:  # pragma: no cover
    import fcntl


class SingletonInstanceError(RuntimeError):
    pass


_LOCK_HANDLE = None
_LOCK_PATH: Path | None = None


def _mask_token(token: str) -> str:
    clean = token.strip()
    if not clean:
        return ""
    if len(clean) <= 4:
        return "****"
    if len(clean) <= 8:
        return f"{clean[:2]}...{clean[-2:]}"
    return f"{clean[:4]}...{clean[-3:]}"


def _lock_identity(app_path: Path, *, token: str | None, allowed_user_id: int | None) -> str:
    clean_token = (token or "").strip()
    clean_user = int(allowed_user_id or 0)
    if clean_token:
        return f"token:{clean_token}|user:{clean_user}"
    return f"app:{app_path}"


def _lock_target_label(app_path: Path, *, token: str | None, allowed_user_id: int | None) -> str:
    clean_token = (token or "").strip()
    clean_user = int(allowed_user_id or 0)
    if clean_token:
        return f"token:{_mask_token(clean_token)}|user:{clean_user}"
    return f"app:{app_path}"


def _lock_name(app_path: Path, *, token: str | None, allowed_user_id: int | None) -> str:
    identity = _lock_identity(app_path, token=token, allowed_user_id=allowed_user_id)
    fingerprint = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:16]
    return f"teleapp-{fingerprint}.lock"


def _lock_file_path(app_path: Path, *, token: str | None, allowed_user_id: int | None) -> Path:
    return Path(tempfile.gettempdir()) / _lock_name(app_path, token=token, allowed_user_id=allowed_user_id)


def acquire_singleton(app_path: Path, *, token: str | None = None, allowed_user_id: int | None = None) -> Path:
    global _LOCK_HANDLE, _LOCK_PATH
    if _LOCK_HANDLE is not None:
        return _LOCK_PATH or _lock_file_path(app_path, token=token, allowed_user_id=allowed_user_id)

    lock_path = _lock_file_path(app_path, token=token, allowed_user_id=allowed_user_id)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+", encoding="utf-8")
    lock_target = _lock_target_label(app_path, token=token, allowed_user_id=allowed_user_id)

    try:
        if os.name == "nt":
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:  # pragma: no cover - platform-specific
                raise SingletonInstanceError(f"Another teleapp instance is already running for {lock_target}") from exc
        else:  # pragma: no cover
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise SingletonInstanceError(f"Another teleapp instance is already running for {lock_target}") from exc

        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
    except Exception:
        handle.close()
        raise

    _LOCK_HANDLE = handle
    _LOCK_PATH = lock_path
    atexit.register(release_singleton)
    return lock_path


def release_singleton() -> None:
    global _LOCK_HANDLE, _LOCK_PATH
    handle = _LOCK_HANDLE
    if handle is None:
        return

    try:
        handle.seek(0)
        handle.truncate()
        if os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:  # pragma: no cover
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        try:
            handle.close()
        except OSError:
            pass
        _LOCK_HANDLE = None
        _LOCK_PATH = None
