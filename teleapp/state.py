from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class ChatSessionState:
    chat_id: int
    queued_requests: int = 0
    active_request_id: str | None = None
    last_request_id: str | None = None
    last_activity_at: datetime | None = None
    status_messages: dict[str, int] = field(default_factory=dict)
    last_timing: dict[str, float | str | int] = field(default_factory=dict)
    status_rate_limited_until: float = 0.0


@dataclass(slots=True)
class RuntimeState:
    running: bool = False
    busy: bool = False
    pid: int | None = None
    last_chat_id: int | None = None
    active_chat_id: int | None = None
    active_request_id: str | None = None
    total_queued_requests: int = 0
    started_at: datetime | None = None
    last_restart_at: datetime | None = None
    last_restart_reason: str | None = None
    last_error: str | None = None
    last_exit_code: int | None = None
    restart_count: int = 0
    watched_paths: list[str] = field(default_factory=list)
    chat_sessions: dict[int, ChatSessionState] = field(default_factory=dict)
