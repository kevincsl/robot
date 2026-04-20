from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from robot.brain import list_schedule_occurrences
from robot.config import Settings

_TIME_RE = re.compile(r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})$")


def _utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _parse_time_text(value: str) -> tuple[int, int] | None:
    match = _TIME_RE.fullmatch((value or "").strip())
    if not match:
        return None
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return hour, minute


def _robot_event_key(item: dict[str, str]) -> str:
    return "|".join(
        [
            (item.get("path") or "").strip(),
            (item.get("date") or "").strip(),
            (item.get("time") or "").strip(),
        ]
    )


def _build_event_payload(item: dict[str, str]) -> dict[str, Any] | None:
    parsed_time = _parse_time_text(item.get("time") or "")
    date_text = (item.get("date") or "").strip()
    if parsed_time is None or not date_text:
        return None

    try:
        date_obj = datetime.fromisoformat(date_text).date()
    except ValueError:
        return None

    hour, minute = parsed_time
    local_tz = datetime.now().astimezone().tzinfo
    start = datetime(date_obj.year, date_obj.month, date_obj.day, hour, minute, tzinfo=local_tz)
    end = start + timedelta(hours=1)

    robot_key = _robot_event_key(item)
    robot_path = (item.get("path") or "").strip()
    summary = (item.get("title") or "").strip() or "Robot Schedule"
    description = f"Synced from Robot schedule\npath: {robot_path}"
    recurrence_label = (item.get("recurrence") or "").strip()
    if recurrence_label:
        description += f"\nrecurrence: {recurrence_label}"

    return {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
        "extendedProperties": {
            "private": {
                "robot_event_key": robot_key,
                "robot_schedule_path": robot_path,
            }
        },
    }


class ScheduleGoogleMappingStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"version": 1, "items": []}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "items": []}
        if not isinstance(payload, dict):
            return {"version": 1, "items": []}
        items = payload.get("items")
        if not isinstance(items, list):
            payload["items"] = []
        payload.setdefault("version", 1)
        return payload

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, robot_event_key: str) -> dict[str, Any] | None:
        for item in self._data.get("items", []):
            if isinstance(item, dict) and item.get("robot_event_key") == robot_event_key:
                return item
        return None

    def upsert(self, robot_event_key: str, google_event_id: str, *, sync_status: str = "ok") -> None:
        entry = self.get(robot_event_key)
        if entry is None:
            self._data.setdefault("items", []).append(
                {
                    "robot_event_key": robot_event_key,
                    "google_event_id": google_event_id,
                    "last_synced_at": _utc_now_iso(),
                    "source_of_truth": "robot",
                    "sync_status": sync_status,
                }
            )
            return
        entry["google_event_id"] = google_event_id
        entry["last_synced_at"] = _utc_now_iso()
        entry["source_of_truth"] = "robot"
        entry["sync_status"] = sync_status


def _build_google_service(credentials_path: Path, token_path: Path):
    from google.auth.transport.requests import Request  # type: ignore
    from google.oauth2.credentials import Credentials  # type: ignore
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    from googleapiclient.discovery import build  # type: ignore

    scopes = ["https://www.googleapis.com/auth/calendar"]
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), scopes)
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def sync_schedule_to_google(
    settings: Settings,
    *,
    period: str = "month",
    limit: int = 200,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    if not settings.google_calendar_sync_enabled:
        return {"enabled": False, "reason": "disabled", "created": 0, "updated": 0, "skipped": 0, "errors": 0}

    if settings.google_calendar_sync_direction not in {"robot_to_google", "bidirectional"}:
        return {
            "enabled": True,
            "reason": "direction_not_supported",
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": 0,
        }

    title, items = list_schedule_occurrences(settings, period=period, limit=max(1, limit))
    mapping = ScheduleGoogleMappingStore(settings.google_sync_mapping_path)
    run_dry = settings.google_calendar_sync_dry_run if dry_run is None else bool(dry_run)

    prepared: list[tuple[str, dict[str, Any]]] = []
    skipped = 0
    for item in items:
        payload = _build_event_payload(item)
        if payload is None:
            skipped += 1
            continue
        key = _robot_event_key(item)
        prepared.append((key, payload))

    if run_dry:
        created = 0
        updated = 0
        for key, _ in prepared:
            if mapping.get(key):
                updated += 1
            else:
                created += 1
        return {
            "enabled": True,
            "reason": "ok",
            "title": title,
            "dry_run": True,
            "source_items": len(items),
            "processed_items": len(prepared),
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "errors": 0,
            "error_samples": [],
        }

    if settings.google_credentials_path is None:
        raise RuntimeError("Missing GOOGLE_CREDENTIALS_PATH for Google Calendar sync.")
    if not settings.google_credentials_path.exists():
        raise RuntimeError(f"Google credentials file not found: {settings.google_credentials_path}")

    try:
        service = _build_google_service(settings.google_credentials_path, settings.google_token_path)
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Google Calendar dependencies missing. Install: "
            "google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        ) from exc

    created = 0
    updated = 0
    errors = 0
    error_samples: list[str] = []

    for key, payload in prepared:
        try:
            entry = mapping.get(key)
            if entry and entry.get("google_event_id"):
                event_id = str(entry.get("google_event_id"))
                service.events().update(
                    calendarId=settings.google_calendar_id,
                    eventId=event_id,
                    body=payload,
                ).execute()
                mapping.upsert(key, event_id)
                updated += 1
            else:
                created_event = (
                    service.events()
                    .insert(calendarId=settings.google_calendar_id, body=payload)
                    .execute()
                )
                new_event_id = str(created_event.get("id") or "")
                if new_event_id:
                    mapping.upsert(key, new_event_id)
                created += 1
        except Exception as exc:  # pragma: no cover - integration/runtime path
            errors += 1
            if len(error_samples) < 5:
                error_samples.append(str(exc))

    mapping.save()
    return {
        "enabled": True,
        "reason": "ok",
        "title": title,
        "dry_run": False,
        "source_items": len(items),
        "processed_items": len(prepared),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "error_samples": error_samples,
    }
