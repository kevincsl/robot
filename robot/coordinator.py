from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class RobotStatus:
    robot_id: str
    last_heartbeat: float
    status: str
    current_provider: str | None
    current_model: str | None
    active_chats: int
    queue_size: int
    metadata: dict[str, Any]


class RobotCoordinator:
    """Multi-robot coordination using file-based messaging."""

    def __init__(self, state_home: Path, robot_id: str) -> None:
        self._state_home = state_home
        self._robot_id = robot_id
        self._lock = threading.RLock()
        self._messages_dir = state_home / "messages"
        self._status_dir = state_home / "status"
        self._messages_dir.mkdir(parents=True, exist_ok=True)
        self._status_dir.mkdir(parents=True, exist_ok=True)
        self._status_file = self._status_dir / f"{robot_id}.json"
        self._last_heartbeat = time.time()

    def update_status(
        self,
        status: str = "running",
        current_provider: str | None = None,
        current_model: str | None = None,
        active_chats: int = 0,
        queue_size: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Update this robot's status."""
        with self._lock:
            self._last_heartbeat = time.time()
            data = {
                "robot_id": self._robot_id,
                "last_heartbeat": self._last_heartbeat,
                "status": status,
                "current_provider": current_provider,
                "current_model": current_model,
                "active_chats": active_chats,
                "queue_size": queue_size,
                "metadata": metadata or {},
            }
            try:
                self._status_file.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except (OSError, TypeError, ValueError):
                pass

    def get_all_robots(self, timeout_seconds: float = 60.0) -> list[RobotStatus]:
        """Get status of all robots (exclude stale ones)."""
        robots: list[RobotStatus] = []
        cutoff = time.time() - timeout_seconds

        try:
            for status_file in self._status_dir.glob("*.json"):
                try:
                    data = json.loads(status_file.read_text(encoding="utf-8"))
                    if not isinstance(data, dict):
                        continue

                    last_heartbeat = float(data.get("last_heartbeat", 0))
                    if last_heartbeat < cutoff:
                        continue

                    robots.append(
                        RobotStatus(
                            robot_id=str(data.get("robot_id", "")),
                            last_heartbeat=last_heartbeat,
                            status=str(data.get("status", "unknown")),
                            current_provider=data.get("current_provider"),
                            current_model=data.get("current_model"),
                            active_chats=int(data.get("active_chats", 0)),
                            queue_size=int(data.get("queue_size", 0)),
                            metadata=data.get("metadata") or {},
                        )
                    )
                except (OSError, json.JSONDecodeError, ValueError, TypeError):
                    continue
        except OSError:
            pass

        return sorted(robots, key=lambda r: r.robot_id)

    def get_robot_status(self, robot_id: str) -> RobotStatus | None:
        """Get status of a specific robot."""
        status_file = self._status_dir / f"{robot_id}.json"
        if not status_file.exists():
            return None

        try:
            data = json.loads(status_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None

            return RobotStatus(
                robot_id=str(data.get("robot_id", "")),
                last_heartbeat=float(data.get("last_heartbeat", 0)),
                status=str(data.get("status", "unknown")),
                current_provider=data.get("current_provider"),
                current_model=data.get("current_model"),
                active_chats=int(data.get("active_chats", 0)),
                queue_size=int(data.get("queue_size", 0)),
                metadata=data.get("metadata") or {},
            )
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            return None

    def broadcast_message(self, topic: str, payload: dict[str, Any]) -> None:
        """Broadcast a message to all robots."""
        timestamp = time.time()
        message_id = f"{self._robot_id}_{int(timestamp * 1000)}"
        message_file = self._messages_dir / f"{message_id}.json"

        data = {
            "message_id": message_id,
            "from_robot": self._robot_id,
            "topic": topic,
            "timestamp": timestamp,
            "payload": payload,
        }

        try:
            message_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except (OSError, TypeError, ValueError):
            pass

    def get_messages(self, since: float = 0.0, topic: str | None = None) -> list[dict[str, Any]]:
        """Get messages since timestamp, optionally filtered by topic."""
        messages: list[dict[str, Any]] = []

        try:
            for message_file in self._messages_dir.glob("*.json"):
                try:
                    data = json.loads(message_file.read_text(encoding="utf-8"))
                    if not isinstance(data, dict):
                        continue

                    timestamp = float(data.get("timestamp", 0))
                    if timestamp <= since:
                        continue

                    if topic and str(data.get("topic", "")) != topic:
                        continue

                    messages.append(data)
                except (OSError, json.JSONDecodeError, ValueError, TypeError):
                    continue
        except OSError:
            pass

        return sorted(messages, key=lambda m: m.get("timestamp", 0))

    def cleanup_old_messages(self, max_age_seconds: float = 3600.0) -> int:
        """Remove messages older than max_age_seconds."""
        cutoff = time.time() - max_age_seconds
        removed = 0

        try:
            for message_file in self._messages_dir.glob("*.json"):
                try:
                    data = json.loads(message_file.read_text(encoding="utf-8"))
                    if not isinstance(data, dict):
                        continue

                    timestamp = float(data.get("timestamp", 0))
                    if timestamp < cutoff:
                        message_file.unlink()
                        removed += 1
                except (OSError, json.JSONDecodeError, ValueError, TypeError):
                    continue
        except OSError:
            pass

        return removed
