from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from robot.brain import create_schedule_note, list_schedule_notes, list_schedule_occurrences, update_schedule_note
from robot.config import Settings

_TIME_RE = re.compile(r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})$")


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _parse_time_text(value: str) -> tuple[int, int] | None:
    match = _TIME_RE.fullmatch((value or "").strip())
    if not match:
        return None
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return hour, minute


def _robot_event_key(path: str, date_text: str, time_text: str) -> str:
    return "|".join([path.strip(), date_text.strip(), time_text.strip()])


def _build_google_payload(item: dict[str, str]) -> dict[str, Any] | None:
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
    path = (item.get("path") or "").strip()
    title = (item.get("title") or "").strip() or "Robot Schedule"
    robot_key = _robot_event_key(path, date_text, item.get("time") or "")
    recurrence = (item.get("recurrence") or "").strip()
    description = f"Synced from Robot schedule\npath: {path}"
    if recurrence:
        description += f"\nrecurrence: {recurrence}"

    return {
        "summary": title,
        "description": description,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
        "extendedProperties": {
            "private": {
                "robot_event_key": robot_key,
                "robot_schedule_path": path,
            }
        },
    }


def _google_start_to_date_time(event: dict[str, Any]) -> tuple[str, str] | None:
    start_obj = event.get("start")
    if not isinstance(start_obj, dict):
        return None
    start_dt = start_obj.get("dateTime")
    if not isinstance(start_dt, str) or not start_dt.strip():
        return None

    normalized = start_dt.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    local = dt.astimezone()
    return local.strftime("%Y-%m-%d"), local.strftime("%H:%M")


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

    def all_items(self) -> list[dict[str, Any]]:
        items = self._data.get("items")
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    def get_by_robot_key(self, robot_event_key: str) -> dict[str, Any] | None:
        for item in self.all_items():
            if item.get("robot_event_key") == robot_event_key:
                return item
        return None

    def get_by_google_id(self, google_event_id: str) -> dict[str, Any] | None:
        for item in self.all_items():
            if item.get("google_event_id") == google_event_id:
                return item
        return None

    def upsert(
        self,
        *,
        robot_event_key: str,
        google_event_id: str,
        robot_schedule_path: str,
        source_of_truth: str,
        sync_status: str = "ok",
    ) -> None:
        entry = self.get_by_google_id(google_event_id) or self.get_by_robot_key(robot_event_key)
        if entry is None:
            self._data.setdefault("items", []).append(
                {
                    "robot_event_key": robot_event_key,
                    "google_event_id": google_event_id,
                    "robot_schedule_path": robot_schedule_path,
                    "last_synced_at": _utc_now_iso(),
                    "source_of_truth": source_of_truth,
                    "sync_status": sync_status,
                }
            )
            return
        entry["robot_event_key"] = robot_event_key
        entry["google_event_id"] = google_event_id
        entry["robot_schedule_path"] = robot_schedule_path
        entry["last_synced_at"] = _utc_now_iso()
        entry["source_of_truth"] = source_of_truth
        entry["sync_status"] = sync_status

    def mark_deleted_by_google_ids(self, existing_google_ids: set[str]) -> int:
        marked = 0
        for entry in self.all_items():
            gid = str(entry.get("google_event_id") or "").strip()
            if not gid or gid in existing_google_ids:
                continue
            if entry.get("sync_status") == "deleted":
                continue
            entry["sync_status"] = "deleted"
            entry["last_synced_at"] = _utc_now_iso()
            marked += 1
        return marked


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


def _require_google_service(settings: Settings):
    if settings.google_credentials_path is None:
        raise RuntimeError("Missing GOOGLE_CREDENTIALS_PATH for Google Calendar sync.")
    if not settings.google_credentials_path.exists():
        raise RuntimeError(f"Google credentials file not found: {settings.google_credentials_path}")
    try:
        return _build_google_service(settings.google_credentials_path, settings.google_token_path)
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Google Calendar dependencies missing. Install: "
            "google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        ) from exc


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
        return {"enabled": False, "reason": "direction_not_supported", "created": 0, "updated": 0, "skipped": 0, "errors": 0}

    _, items = list_schedule_occurrences(settings, period=period, limit=max(1, limit))
    mapping = ScheduleGoogleMappingStore(settings.google_sync_mapping_path)
    run_dry = settings.google_calendar_sync_dry_run if dry_run is None else bool(dry_run)

    prepared: list[tuple[str, str, dict[str, Any]]] = []
    skipped = 0
    for item in items:
        payload = _build_google_payload(item)
        if payload is None:
            skipped += 1
            continue
        path = (item.get("path") or "").strip()
        date_text = (item.get("date") or "").strip()
        time_text = (item.get("time") or "").strip()
        prepared.append((_robot_event_key(path, date_text, time_text), path, payload))

    if run_dry:
        created = 0
        updated = 0
        for key, _, _ in prepared:
            if mapping.get_by_robot_key(key):
                updated += 1
            else:
                created += 1
        return {
            "enabled": True,
            "mode": "push",
            "dry_run": True,
            "source_count": len(items),
            "processed": len(prepared),
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "deleted": 0,
            "errors": 0,
            "error_samples": [],
        }

    service = _require_google_service(settings)
    created = 0
    updated = 0
    errors = 0
    error_samples: list[str] = []

    for key, path, payload in prepared:
        try:
            entry = mapping.get_by_robot_key(key)
            if entry and entry.get("google_event_id"):
                gid = str(entry.get("google_event_id"))
                service.events().update(calendarId=settings.google_calendar_id, eventId=gid, body=payload).execute()
                mapping.upsert(
                    robot_event_key=key,
                    google_event_id=gid,
                    robot_schedule_path=path,
                    source_of_truth="robot",
                    sync_status="ok",
                )
                updated += 1
            else:
                created_event = service.events().insert(calendarId=settings.google_calendar_id, body=payload).execute()
                gid = str(created_event.get("id") or "").strip()
                if gid:
                    mapping.upsert(
                        robot_event_key=key,
                        google_event_id=gid,
                        robot_schedule_path=path,
                        source_of_truth="robot",
                        sync_status="ok",
                    )
                created += 1
        except Exception as exc:  # pragma: no cover
            errors += 1
            if len(error_samples) < 5:
                error_samples.append(str(exc))

    mapping.save()
    return {
        "enabled": True,
        "mode": "push",
        "dry_run": False,
        "source_count": len(items),
        "processed": len(prepared),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "deleted": 0,
        "errors": errors,
        "error_samples": error_samples,
    }


def sync_schedule_from_google(
    settings: Settings,
    *,
    limit: int = 200,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    if not settings.google_calendar_sync_enabled:
        return {"enabled": False, "reason": "disabled", "created": 0, "updated": 0, "skipped": 0, "errors": 0}
    if settings.google_calendar_sync_direction not in {"google_to_robot", "bidirectional"}:
        return {"enabled": False, "reason": "direction_not_supported", "created": 0, "updated": 0, "skipped": 0, "errors": 0}

    run_dry = settings.google_calendar_sync_dry_run if dry_run is None else bool(dry_run)
    service = _require_google_service(settings)
    mapping = ScheduleGoogleMappingStore(settings.google_sync_mapping_path)

    fetch_count = max(1, min(limit, 500))
    now = datetime.now(UTC)
    time_min = (now - timedelta(days=30)).isoformat()
    fetched = (
        service.events()
        .list(
            calendarId=settings.google_calendar_id,
            timeMin=time_min,
            maxResults=fetch_count,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    events = fetched.get("items")
    if not isinstance(events, list):
        events = []

    local_notes = list_schedule_notes(settings, limit=5000)
    notes_by_path = {str(item.get("path") or "").strip(): item for item in local_notes}

    prepared: list[dict[str, str]] = []
    skipped = 0
    for event in events:
        if not isinstance(event, dict):
            skipped += 1
            continue
        gid = str(event.get("id") or "").strip()
        if not gid:
            skipped += 1
            continue
        parsed = _google_start_to_date_time(event)
        if parsed is None:
            skipped += 1
            continue
        date_text, time_text = parsed
        summary = str(event.get("summary") or "").strip() or "Google Event"
        mapped = mapping.get_by_google_id(gid)
        mapped_path = str(mapped.get("robot_schedule_path") or "").strip() if isinstance(mapped, dict) else ""
        prepared.append(
            {
                "google_event_id": gid,
                "title": summary,
                "date": date_text,
                "time": time_text,
                "mapped_path": mapped_path,
            }
        )

    if run_dry:
        created = 0
        updated = 0
        for item in prepared:
            path = item.get("mapped_path") or ""
            if path and path in notes_by_path:
                updated += 1
            else:
                created += 1
        seen_ids = {item["google_event_id"] for item in prepared}
        deleted = 0
        for entry in mapping.all_items():
            gid = str(entry.get("google_event_id") or "").strip()
            if gid and gid not in seen_ids and entry.get("sync_status") != "deleted":
                deleted += 1
        return {
            "enabled": True,
            "mode": "pull",
            "dry_run": True,
            "source_count": len(events),
            "processed": len(prepared),
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "deleted": deleted,
            "errors": 0,
            "error_samples": [],
        }

    created = 0
    updated = 0
    errors = 0
    error_samples: list[str] = []
    seen_ids: set[str] = set()

    for item in prepared:
        gid = item["google_event_id"]
        seen_ids.add(gid)
        title = item["title"]
        date_text = item["date"]
        time_text = item["time"]
        mapped_path = item.get("mapped_path") or ""

        try:
            if mapped_path and mapped_path in notes_by_path:
                update_schedule_note(settings, mapped_path, date_text=date_text, time_text=time_text)
                key = _robot_event_key(mapped_path, date_text, time_text)
                mapping.upsert(
                    robot_event_key=key,
                    google_event_id=gid,
                    robot_schedule_path=mapped_path,
                    source_of_truth="google",
                    sync_status="ok",
                )
                updated += 1
            else:
                new_path = create_schedule_note(settings, title, date_text, time_text)
                key = _robot_event_key(new_path, date_text, time_text)
                mapping.upsert(
                    robot_event_key=key,
                    google_event_id=gid,
                    robot_schedule_path=new_path,
                    source_of_truth="google",
                    sync_status="ok",
                )
                notes_by_path[new_path] = {"path": new_path, "date": date_text, "time": time_text}
                created += 1
        except Exception as exc:  # pragma: no cover
            errors += 1
            if len(error_samples) < 5:
                error_samples.append(str(exc))

    deleted = mapping.mark_deleted_by_google_ids(seen_ids)
    mapping.save()
    return {
        "enabled": True,
        "mode": "pull",
        "dry_run": False,
        "source_count": len(events),
        "processed": len(prepared),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "deleted": deleted,
        "errors": errors,
        "error_samples": error_samples,
    }
