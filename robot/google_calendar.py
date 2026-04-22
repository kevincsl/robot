from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from robot.config import Settings

DEPENDENCY_HINT = (
    "Missing Google Calendar dependencies. Install: "
    "pip install google-api-python-client google-auth google-auth-oauthlib"
)

ROBOT_SUMMARY_PREFIX = "[robot] "
ROBOT_MANAGED_KEY = "robot_managed"
ROBOT_CHAT_ID_KEY = "robot_chat_id"
ROBOT_GOAL_KEY = "robot_goal"
ROBOT_JOB_ID_KEY = "robot_job_id"
ROBOT_PROFILE_KEY = "robot_profile"
ROBOT_CONFIG_PATH_KEY = "robot_config_path"
ROBOT_ENABLE_COMMIT_KEY = "robot_enable_commit"
ROBOT_ENABLE_PUSH_KEY = "robot_enable_push"
ROBOT_ENABLE_PR_KEY = "robot_enable_pr"
ROBOT_DISABLE_POST_RUN_KEY = "robot_disable_post_run"
ROBOT_PROJECT_PATH_KEY = "robot_project_path"


class GoogleCalendarError(RuntimeError):
    pass


class GoogleCalendarDependencyError(GoogleCalendarError):
    pass


class GoogleCalendarAuthError(GoogleCalendarError):
    pass


def _import_google_modules() -> tuple[Any, Any, Any, Any, Any]:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
    except ImportError as exc:
        raise GoogleCalendarDependencyError(DEPENDENCY_HINT) from exc
    return Request, Credentials, InstalledAppFlow, build, HttpError


def _write_token(token_path: Path, creds: Any) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")


def _http_status(exc: Exception) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    resp = getattr(exc, "resp", None)
    if resp is None:
        return None
    raw = getattr(resp, "status", None)
    return int(raw) if isinstance(raw, int) else None


def _inspect_token_state(settings: Settings) -> tuple[str, str]:
    _request_cls, credentials_cls, _flow_cls, _build, _http_error_cls = _import_google_modules()
    token_path = settings.google_calendar_token_path
    if not token_path.exists():
        return "missing", "token file not found"
    try:
        creds = credentials_cls.from_authorized_user_file(
            str(token_path),
            list(settings.google_calendar_scopes),
        )
    except Exception as exc:
        return "invalid", f"token parse failed: {exc}"
    if creds.valid:
        return "ready", "token is valid"
    if creds.expired and creds.refresh_token:
        return "expired_refreshable", "token expired but has refresh_token"
    return "invalid", "token is invalid or missing refresh_token"


def _load_valid_credentials(settings: Settings) -> Any:
    request_cls, credentials_cls, _flow_cls, _build, _http_error_cls = _import_google_modules()
    token_path = settings.google_calendar_token_path
    creds: Any | None = None
    if token_path.exists():
        try:
            creds = credentials_cls.from_authorized_user_file(
                str(token_path),
                list(settings.google_calendar_scopes),
            )
        except Exception as exc:
            raise GoogleCalendarAuthError(f"Token file is invalid: {exc}") from exc
    if creds is None:
        raise GoogleCalendarAuthError(
            "Token file is missing. Run: python scripts/google_calendar_auth.py"
        )
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(request_cls())
            _write_token(token_path, creds)
            return creds
        except Exception as exc:
            raise GoogleCalendarAuthError(
                f"Token refresh failed: {exc}. Re-authorize with: python scripts/google_calendar_auth.py"
            ) from exc
    raise GoogleCalendarAuthError(
        "Token is not valid and cannot be refreshed. Re-authorize with: python scripts/google_calendar_auth.py"
    )


def _build_calendar_service(settings: Settings) -> tuple[Any, Any, Any]:
    creds = _load_valid_credentials(settings)
    _request_cls, _credentials_cls, _flow_cls, build, http_error_cls = _import_google_modules()
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return service, creds, http_error_cls


def _has_write_scope(creds: Any) -> bool:
    required_any = {
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.app.created",
    }
    granted = set(getattr(creds, "scopes", []) or [])
    if granted and required_any.intersection(granted):
        return True
    has_scopes = getattr(creds, "has_scopes", None)
    if callable(has_scopes):
        for scope in required_any:
            try:
                if bool(has_scopes([scope])):
                    return True
            except Exception:
                continue
    return False


def _ensure_write_scope(creds: Any) -> None:
    if _has_write_scope(creds):
        return
    raise GoogleCalendarAuthError(
        "Google Calendar token is read-only. Set ROBOT_GOOGLE_CALENDAR_SCOPES=https://www.googleapis.com/auth/calendar "
        "and re-authorize with: python scripts/google_calendar_auth.py"
    )


def authorize_google_calendar(settings: Settings, *, open_browser: bool = True) -> str:
    if not settings.google_calendar_enabled:
        raise GoogleCalendarAuthError(
            "Google Calendar integration is disabled. Set ROBOT_GOOGLE_CALENDAR_ENABLED=1 first."
        )
    credentials_path = settings.google_calendar_credentials_path
    if not credentials_path.exists():
        raise GoogleCalendarAuthError(f"Credentials file not found: {credentials_path}")
    _request_cls, _credentials_cls, flow_cls, _build, _http_error_cls = _import_google_modules()
    flow = flow_cls.from_client_secrets_file(
        str(credentials_path),
        list(settings.google_calendar_scopes),
    )
    if open_browser:
        creds = flow.run_local_server(port=0, open_browser=True)
    else:
        if not hasattr(flow, "run_console"):
            raise GoogleCalendarAuthError("Console OAuth flow is not available in this environment.")
        creds = flow.run_console()
    _write_token(settings.google_calendar_token_path, creds)
    return "\n".join(
        [
            "Google Calendar authorization completed.",
            f"token_path: {settings.google_calendar_token_path}",
            f"calendar_id: {settings.google_calendar_calendar_id}",
            f"scopes: {', '.join(settings.google_calendar_scopes)}",
        ]
    )


def google_calendar_status_text(settings: Settings) -> str:
    lines = [
        "google calendar status",
        f"enabled: {settings.google_calendar_enabled}",
        f"calendar_id: {settings.google_calendar_calendar_id}",
        f"credentials_path: {settings.google_calendar_credentials_path}",
        f"token_path: {settings.google_calendar_token_path}",
        f"scopes: {', '.join(settings.google_calendar_scopes)}",
        f"credentials_file_exists: {settings.google_calendar_credentials_path.exists()}",
        f"token_file_exists: {settings.google_calendar_token_path.exists()}",
    ]
    if not settings.google_calendar_enabled:
        lines.append("state: disabled")
        lines.append("hint: set ROBOT_GOOGLE_CALENDAR_ENABLED=1")
        return "\n".join(lines)

    try:
        token_state, token_detail = _inspect_token_state(settings)
    except GoogleCalendarDependencyError as exc:
        lines.append("state: missing_dependencies")
        lines.append(f"error: {exc}")
        return "\n".join(lines)

    lines.append(f"token_state: {token_state}")
    lines.append(f"token_detail: {token_detail}")
    if token_state == "ready":
        lines.append("state: ready")
        lines.append("hint: use /gcalupcoming or /gcalsync")
    elif settings.google_calendar_credentials_path.exists():
        lines.append("state: needs_authorization")
        lines.append("hint: run python scripts/google_calendar_auth.py")
    else:
        lines.append("state: missing_credentials")
        lines.append(
            "hint: place OAuth client JSON at ROBOT_GOOGLE_CALENDAR_CREDENTIALS_PATH, then run python scripts/google_calendar_auth.py"
        )
    return "\n".join(lines)


def _format_event_start(item: dict[str, Any]) -> str:
    start = item.get("start") if isinstance(item.get("start"), dict) else {}
    start_dt = start.get("dateTime")
    if isinstance(start_dt, str) and start_dt.strip():
        text = start_dt.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return start_dt
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    start_date = start.get("date")
    if isinstance(start_date, str) and start_date.strip():
        return f"{start_date} (all-day)"
    return "-"


def google_calendar_upcoming_text(settings: Settings, *, days: int = 7, limit: int = 10) -> str:
    if days < 1 or days > 30:
        return "days must be between 1 and 30."
    if limit < 1 or limit > 50:
        return "limit must be between 1 and 50."
    if not settings.google_calendar_enabled:
        return "Google Calendar integration is disabled. Set ROBOT_GOOGLE_CALENDAR_ENABLED=1 first."
    try:
        service, _creds, _http_error_cls = _build_calendar_service(settings)
        now = datetime.now(timezone.utc)
        max_time = now + timedelta(days=days)
        result = (
            service.events()
            .list(
                calendarId=settings.google_calendar_calendar_id,
                timeMin=now.isoformat(),
                timeMax=max_time.isoformat(),
                maxResults=limit,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = result.get("items", [])
    except GoogleCalendarError as exc:
        return f"Google Calendar not ready.\n{exc}"
    except Exception as exc:
        return f"Google Calendar request failed.\n{exc}"

    lines = [
        f"google calendar upcoming ({days}d, limit={limit})",
        f"calendar_id: {settings.google_calendar_calendar_id}",
    ]
    if not events:
        lines.append("- no events")
        return "\n".join(lines)

    for event in events:
        if not isinstance(event, dict):
            continue
        start_text = _format_event_start(event)
        summary = str(event.get("summary") or "(no title)")
        location = str(event.get("location") or "").strip()
        if location:
            lines.append(f"- {start_text} | {summary} @ {location}")
        else:
            lines.append(f"- {start_text} | {summary}")
    return "\n".join(lines)


def _to_bool_text(value: bool) -> str:
    return "1" if value else "0"


def _parse_bool_text(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _strip_robot_prefix(summary: str) -> str:
    text = summary.strip()
    if text.lower().startswith(ROBOT_SUMMARY_PREFIX.strip().lower()):
        return text[len(ROBOT_SUMMARY_PREFIX) :].strip()
    return text


def _event_window_from_run_at(run_at: str) -> tuple[str, str]:
    try:
        when = datetime.fromisoformat(run_at)
    except ValueError as exc:
        raise GoogleCalendarError(f"Invalid schedule run_at: {run_at}") from exc
    if when.tzinfo is None:
        local_tz = datetime.now().astimezone().tzinfo or timezone.utc
        when = when.replace(tzinfo=local_tz)
    end = when + timedelta(minutes=30)
    return when.isoformat(), end.isoformat()


def _run_at_from_event(item: dict[str, Any]) -> str | None:
    start = item.get("start") if isinstance(item.get("start"), dict) else {}
    start_dt = start.get("dateTime")
    if isinstance(start_dt, str) and start_dt.strip():
        text = start_dt.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text).astimezone()
        except ValueError:
            return None
        return dt.replace(tzinfo=None).isoformat(timespec="minutes")
    return None


def _build_schedule_event_body(chat_id: int, schedule_job: dict[str, Any]) -> dict[str, Any]:
    goal = str(schedule_job.get("goal") or "").strip() or "(no goal)"
    run_at = str(schedule_job.get("run_at") or "").strip()
    start_iso, end_iso = _event_window_from_run_at(run_at)
    profile = str(schedule_job.get("profile") or "").strip()
    config_path = str(schedule_job.get("config_path") or "").strip()
    project_path = str(schedule_job.get("project_path") or "").strip()
    private_props = {
        ROBOT_MANAGED_KEY: "1",
        ROBOT_CHAT_ID_KEY: str(chat_id),
        ROBOT_GOAL_KEY: goal,
        ROBOT_JOB_ID_KEY: str(schedule_job.get("job_id") or ""),
        ROBOT_PROFILE_KEY: profile,
        ROBOT_CONFIG_PATH_KEY: config_path,
        ROBOT_ENABLE_COMMIT_KEY: _to_bool_text(bool(schedule_job.get("enable_commit"))),
        ROBOT_ENABLE_PUSH_KEY: _to_bool_text(bool(schedule_job.get("enable_push"))),
        ROBOT_ENABLE_PR_KEY: _to_bool_text(bool(schedule_job.get("enable_pr"))),
        ROBOT_DISABLE_POST_RUN_KEY: _to_bool_text(bool(schedule_job.get("disable_post_run"))),
        ROBOT_PROJECT_PATH_KEY: project_path,
    }
    description_lines = [
        "Managed by robot schedule sync.",
        f"goal: {goal}",
    ]
    if project_path:
        description_lines.append(f"project_path: {project_path}")
    return {
        "summary": f"{ROBOT_SUMMARY_PREFIX}{goal}",
        "description": "\n".join(description_lines),
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso},
        "extendedProperties": {"private": private_props},
    }


def upsert_google_calendar_schedule_event(
    settings: Settings,
    *,
    chat_id: int,
    schedule_job: dict[str, Any],
) -> tuple[str, bool]:
    if not settings.google_calendar_enabled:
        raise GoogleCalendarAuthError(
            "Google Calendar integration is disabled. Set ROBOT_GOOGLE_CALENDAR_ENABLED=1 first."
        )
    service, creds, http_error_cls = _build_calendar_service(settings)
    _ensure_write_scope(creds)
    body = _build_schedule_event_body(chat_id, schedule_job)
    event_id = str(schedule_job.get("gcal_event_id") or "").strip()
    if event_id:
        try:
            updated = (
                service.events()
                .update(
                    calendarId=settings.google_calendar_calendar_id,
                    eventId=event_id,
                    body=body,
                )
                .execute()
            )
            resolved = str(updated.get("id") or event_id).strip()
            return resolved or event_id, False
        except http_error_cls as exc:
            if _http_status(exc) != 404:
                raise GoogleCalendarError(f"Failed to update Google event {event_id}: {exc}") from exc
        except Exception as exc:
            raise GoogleCalendarError(f"Failed to update Google event {event_id}: {exc}") from exc

    try:
        created = (
            service.events()
            .insert(
                calendarId=settings.google_calendar_calendar_id,
                body=body,
            )
            .execute()
        )
    except Exception as exc:
        raise GoogleCalendarError(f"Failed to create Google event: {exc}") from exc
    resolved = str(created.get("id") or "").strip()
    if not resolved:
        raise GoogleCalendarError("Google event created but missing event id.")
    return resolved, True


def delete_google_calendar_schedule_event(settings: Settings, *, event_id: str) -> bool:
    clean_event_id = event_id.strip()
    if not clean_event_id:
        return False
    service, creds, http_error_cls = _build_calendar_service(settings)
    _ensure_write_scope(creds)
    try:
        (
            service.events()
            .delete(
                calendarId=settings.google_calendar_calendar_id,
                eventId=clean_event_id,
            )
            .execute()
        )
        return True
    except http_error_cls as exc:
        if _http_status(exc) == 404:
            return False
        raise GoogleCalendarError(f"Failed to delete Google event {clean_event_id}: {exc}") from exc
    except Exception as exc:
        raise GoogleCalendarError(f"Failed to delete Google event {clean_event_id}: {exc}") from exc


def list_managed_google_calendar_schedule_events(
    settings: Settings,
    *,
    chat_id: int,
    days: int = 30,
    limit: int = 200,
) -> list[dict[str, Any]]:
    if days < 1 or days > 120:
        raise GoogleCalendarError("days must be between 1 and 120.")
    if limit < 1 or limit > 500:
        raise GoogleCalendarError("limit must be between 1 and 500.")
    service, _creds, _http_error_cls = _build_calendar_service(settings)
    now = datetime.now(timezone.utc)
    max_time = now + timedelta(days=days)
    result = (
        service.events()
        .list(
            calendarId=settings.google_calendar_calendar_id,
            timeMin=now.isoformat(),
            timeMax=max_time.isoformat(),
            maxResults=limit,
            singleEvents=True,
            orderBy="startTime",
            privateExtendedProperty=[
                f"{ROBOT_MANAGED_KEY}=1",
                f"{ROBOT_CHAT_ID_KEY}={chat_id}",
            ],
        )
        .execute()
    )
    items = result.get("items")
    events = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    results: list[dict[str, Any]] = []
    for event in events:
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            continue
        private = (
            event.get("extendedProperties", {}).get("private", {})
            if isinstance(event.get("extendedProperties"), dict)
            else {}
        )
        if not isinstance(private, dict):
            private = {}
        run_at = _run_at_from_event(event)
        if not run_at:
            continue
        summary = str(event.get("summary") or "").strip()
        goal = str(private.get(ROBOT_GOAL_KEY) or _strip_robot_prefix(summary) or "(no goal)")
        results.append(
            {
                "event_id": event_id,
                "run_at": run_at,
                "goal": goal,
                "profile": str(private.get(ROBOT_PROFILE_KEY) or "").strip() or None,
                "config_path": str(private.get(ROBOT_CONFIG_PATH_KEY) or "").strip() or None,
                "enable_commit": _parse_bool_text(str(private.get(ROBOT_ENABLE_COMMIT_KEY) or "")),
                "enable_push": _parse_bool_text(str(private.get(ROBOT_ENABLE_PUSH_KEY) or "")),
                "enable_pr": _parse_bool_text(str(private.get(ROBOT_ENABLE_PR_KEY) or "")),
                "disable_post_run": _parse_bool_text(str(private.get(ROBOT_DISABLE_POST_RUN_KEY) or "")),
                "project_path": str(private.get(ROBOT_PROJECT_PATH_KEY) or "").strip() or None,
            }
        )
    return results


def _build_remote_job(remote: dict[str, Any], state_defaults: dict[str, Any]) -> dict[str, Any]:
    now_marker = datetime.now().isoformat(timespec="seconds")
    return {
        "job_id": str(uuid4()),
        "kind": "auto_dev",
        "goal": str(remote.get("goal") or "(no goal)"),
        "project_name": str(state_defaults.get("project_name") or "robot"),
        "project_display": str(
            state_defaults.get("project_display")
            or state_defaults.get("project_name")
            or "robot"
        ),
        "project_path": str(state_defaults.get("project_path") or ""),
        "provider": "auto-dev",
        "model": str(remote.get("profile") or "default"),
        "thread_id": None,
        "source": "gcal-sync-pull",
        "request_id": None,
        "status_key": "gcalsync",
        "run_id": str(uuid4()),
        "profile": remote.get("profile"),
        "config_path": remote.get("config_path"),
        "resume_target": None,
        "enable_commit": bool(remote.get("enable_commit")),
        "enable_push": bool(remote.get("enable_push")),
        "enable_pr": bool(remote.get("enable_pr")),
        "disable_post_run": bool(remote.get("disable_post_run")),
        "run_at": str(remote.get("run_at") or ""),
        "gcal_event_id": str(remote.get("event_id") or ""),
        "gcal_last_synced_at": now_marker,
    }


def sync_schedule_jobs_with_google(
    settings: Settings,
    *,
    chat_id: int,
    schedules: list[dict[str, Any]],
    mode: str = "both",
    days: int = 30,
    limit: int = 200,
    state_defaults: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected_mode = mode.strip().lower()
    if selected_mode not in {"push", "pull", "both"}:
        raise GoogleCalendarError("mode must be one of push, pull, both.")
    updated: list[dict[str, Any]] = [dict(item) for item in schedules if isinstance(item, dict)]
    report: dict[str, Any] = {
        "mode": selected_mode,
        "local_before": len(updated),
        "pushed_created": 0,
        "pushed_updated": 0,
        "push_errors": 0,
        "pulled_created": 0,
        "pulled_updated": 0,
        "pull_errors": 0,
        "errors": [],
    }

    now_marker = datetime.now().isoformat(timespec="seconds")
    if selected_mode in {"push", "both"}:
        for job in updated:
            run_at = str(job.get("run_at") or "").strip()
            if not run_at:
                continue
            try:
                event_id, created = upsert_google_calendar_schedule_event(
                    settings,
                    chat_id=chat_id,
                    schedule_job=job,
                )
                job["gcal_event_id"] = event_id
                job["gcal_last_synced_at"] = now_marker
                job.pop("gcal_sync_error", None)
                if created:
                    report["pushed_created"] += 1
                else:
                    report["pushed_updated"] += 1
            except Exception as exc:
                report["push_errors"] += 1
                message = str(exc)
                job["gcal_sync_error"] = message
                report["errors"].append(f"push:{job.get('job_id') or '-'}: {message}")

    if selected_mode in {"pull", "both"}:
        try:
            remote_events = list_managed_google_calendar_schedule_events(
                settings,
                chat_id=chat_id,
                days=days,
                limit=limit,
            )
        except Exception as exc:
            report["pull_errors"] += 1
            report["errors"].append(f"pull:list_failed: {exc}")
            return updated, report

        by_event_id: dict[str, dict[str, Any]] = {}
        for job in updated:
            key = str(job.get("gcal_event_id") or "").strip()
            if key:
                by_event_id[key] = job

        defaults = state_defaults or {}
        for remote in remote_events:
            event_id = str(remote.get("event_id") or "").strip()
            if not event_id:
                continue
            existing = by_event_id.get(event_id)
            if existing is None:
                new_job = _build_remote_job(remote, defaults)
                updated.append(new_job)
                by_event_id[event_id] = new_job
                report["pulled_created"] += 1
                continue

            changed = False
            for key in (
                "run_at",
                "goal",
                "profile",
                "config_path",
                "enable_commit",
                "enable_push",
                "enable_pr",
                "disable_post_run",
            ):
                remote_value = remote.get(key)
                if existing.get(key) != remote_value:
                    existing[key] = remote_value
                    changed = True
            existing["gcal_event_id"] = event_id
            existing["gcal_last_synced_at"] = now_marker
            existing.pop("gcal_sync_error", None)
            if changed:
                report["pulled_updated"] += 1

    report["local_after"] = len(updated)
    return updated, report
