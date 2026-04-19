from __future__ import annotations

import asyncio
from pathlib import Path


def _iter_tracked_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]

    files: list[Path] = []
    for child in path.rglob("*.py"):
        if "__pycache__" in child.parts:
            continue
        files.append(child)
    return files


def _snapshot(paths: list[Path]) -> dict[str, float]:
    data: dict[str, float] = {}
    for path in paths:
        for file_path in _iter_tracked_files(path):
            try:
                data[str(file_path)] = file_path.stat().st_mtime
            except OSError:
                continue
    return data


class PollingHotReload:
    def __init__(
        self,
        *,
        paths: list[Path],
        quiet_seconds: int,
        poll_seconds: int,
        on_reload,
    ) -> None:
        self._paths = paths
        self._quiet_seconds = quiet_seconds
        self._poll_seconds = poll_seconds
        self._on_reload = on_reload
        self._stop = asyncio.Event()

    async def run(self) -> None:
        last_snapshot = _snapshot(self._paths)
        pending_reason: str | None = None
        changed_at: float | None = None
        loop = asyncio.get_running_loop()

        while not self._stop.is_set():
            await asyncio.sleep(self._poll_seconds)
            next_snapshot = _snapshot(self._paths)
            changed = [path for path, mtime in next_snapshot.items() if last_snapshot.get(path) != mtime]
            removed = [path for path in last_snapshot if path not in next_snapshot]

            if changed or removed:
                path = Path((changed or removed)[0])
                pending_reason = f"file changed: {path.name}"
                changed_at = loop.time()

            if pending_reason and changed_at is not None and (loop.time() - changed_at) >= self._quiet_seconds:
                await self._on_reload(pending_reason)
                pending_reason = None
                changed_at = None
                next_snapshot = _snapshot(self._paths)

            last_snapshot = next_snapshot

    def stop(self) -> None:
        self._stop.set()
