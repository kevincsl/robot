from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


DEFAULT_OUTPUT_TYPE = "output"
DEFAULT_ERROR_TYPE = "error"
DEFAULT_STATUS_TYPE = "status"


@dataclass(slots=True)
class AppEvent:
    type: str
    text: str
    chat_id: int | None = None
    request_id: str | None = None
    process_pid: int | None = None
    stream: str = "stdout"
    raw: dict[str, Any] | None = None


def _sanitize_surrogates(value: Any) -> Any:
    if isinstance(value, str):
        return value.encode("utf-8", errors="replace").decode("utf-8")
    if isinstance(value, dict):
        return {key: _sanitize_surrogates(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_surrogates(item) for item in value]
    return value


def encode_input_event(
    chat_id: int,
    text: str,
    *,
    request_id: str,
    command: str | None = None,
    raw: dict[str, Any] | None = None,
) -> str:
    payload = {
        "type": "input",
        "chat_id": chat_id,
        "request_id": request_id,
        "text": text,
    }
    if command:
        payload["command"] = command
    if raw:
        payload["raw"] = raw
    return json.dumps(_sanitize_surrogates(payload), ensure_ascii=False)


def decode_output_line(line: str, *, stream: str) -> AppEvent | None:
    cleaned = (line or "").strip()
    if not cleaned:
        return None

    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return AppEvent(
            type=DEFAULT_ERROR_TYPE if stream == "stderr" else DEFAULT_OUTPUT_TYPE,
            text=cleaned,
            stream=stream,
            raw=None,
        )

    if not isinstance(payload, dict):
        return AppEvent(
            type=DEFAULT_ERROR_TYPE if stream == "stderr" else DEFAULT_OUTPUT_TYPE,
            text=cleaned,
            stream=stream,
            raw={"payload": payload},
        )

    text = str(payload.get("text") or payload.get("message") or cleaned)
    raw_type = str(payload.get("type") or "").strip().lower()
    event_type = raw_type or (DEFAULT_ERROR_TYPE if stream == "stderr" else DEFAULT_OUTPUT_TYPE)

    chat_id: int | None = None
    raw_chat_id = payload.get("chat_id")
    if isinstance(raw_chat_id, int):
        chat_id = raw_chat_id
    elif isinstance(raw_chat_id, str) and raw_chat_id.strip().lstrip("-").isdigit():
        chat_id = int(raw_chat_id.strip())

    request_id: str | None = None
    raw_request_id = payload.get("request_id")
    if isinstance(raw_request_id, str) and raw_request_id.strip():
        request_id = raw_request_id.strip()

    command: str | None = None
    raw_command = payload.get("command")
    if isinstance(raw_command, str) and raw_command.strip():
        command = raw_command.strip()

    raw_payload = payload.get("raw")
    if not isinstance(raw_payload, dict):
        raw_payload = payload

    return AppEvent(
        type=event_type,
        text=text,
        chat_id=chat_id,
        request_id=request_id,
        raw={**raw_payload, "command": command} if command else raw_payload,
        stream=stream,
    )
