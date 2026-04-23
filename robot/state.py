from __future__ import annotations

import json
import re
import threading
from typing import Any

from robot.config import Settings, normalize_model, normalize_provider
from robot.projects import get_default_workspace
from robot.text import normalize_text

CONTACT_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ChatStateStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.RLock()
        self._state = self._load()

    def _default_state(self) -> dict[str, Any]:
        return {"chats": {}}

    def _load(self) -> dict[str, Any]:
        path = self._settings.session_state_path
        if not path.exists():
            return self._default_state()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._default_state()
        return data if isinstance(data, dict) else self._default_state()

    def _save(self) -> None:
        def _sanitize(value: Any) -> Any:
            if isinstance(value, str):
                return normalize_text(value)
            if isinstance(value, dict):
                return {k: _sanitize(v) for k, v in value.items()}
            if isinstance(value, list):
                return [_sanitize(item) for item in value]
            return value

        try:
            self._state = _sanitize(self._state)
            self._settings.state_home.mkdir(parents=True, exist_ok=True)
            self._settings.session_state_path.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except (OSError, UnicodeEncodeError, TypeError, ValueError):
            return

    def _address_book(self) -> dict[str, Any]:
        book = self._state.setdefault("address_book", {})
        if not isinstance(book, dict):
            book = {}
            self._state["address_book"] = book
        contacts = book.setdefault("contacts", {})
        if not isinstance(contacts, dict):
            contacts = {}
            book["contacts"] = contacts
        return book

    @staticmethod
    def _normalize_contact_key(key: str) -> str:
        return str(key or "").strip().lower()

    @staticmethod
    def _normalize_alias(alias: str) -> str:
        return str(alias or "").strip().lower()

    @staticmethod
    def _normalize_email(email: str) -> str:
        return str(email or "").strip().lower()

    @staticmethod
    def _is_valid_email(email: str) -> bool:
        return bool(EMAIL_PATTERN.match(email))

    def _ensure_contact_key(self, key: str) -> str:
        normalized = self._normalize_contact_key(key)
        if not CONTACT_KEY_PATTERN.match(normalized):
            raise ValueError("contact key must match: [a-z0-9][a-z0-9_-]{0,31}")
        return normalized

    def _bucket(self, chat_id: int) -> dict[str, Any]:
        chats = self._state.setdefault("chats", {})
        bucket = chats.setdefault(str(chat_id), {})
        if not isinstance(bucket, dict):
            bucket = {}
            chats[str(chat_id)] = bucket

        default_workspace = get_default_workspace(self._settings)
        provider = normalize_provider(bucket.get("provider") or self._settings.default_provider)
        models = bucket.setdefault("models", {})
        if not isinstance(models, dict):
            models = {}
            bucket["models"] = models
        threads = bucket.setdefault("threads", {})
        if not isinstance(threads, dict):
            threads = {}
            bucket["threads"] = threads

        models[provider] = normalize_model(provider, models.get(provider) or self._settings.default_model)
        bucket["provider"] = provider
        bucket.setdefault("project_key", default_workspace.key)
        bucket.setdefault("project_name", default_workspace.label)
        bucket.setdefault("project_path", str(default_workspace.path))
        queue = bucket.setdefault("agent_queue", [])
        if not isinstance(queue, list):
            bucket["agent_queue"] = []
        schedules = bucket.setdefault("agent_schedules", [])
        if not isinstance(schedules, list):
            bucket["agent_schedules"] = []
        bucket.setdefault("agent_current_run", None)
        bucket.setdefault("agent_last_run", None)
        bucket.setdefault("last_provider_timing", {})
        bucket.setdefault("ui_flow", None)
        bucket.setdefault("last_schedule_candidate", None)
        last_schedule_results = bucket.setdefault("last_schedule_results", [])
        if not isinstance(last_schedule_results, list):
            bucket["last_schedule_results"] = []
        automation = bucket.setdefault("brain_automation", {})
        if not isinstance(automation, dict):
            automation = {}
            bucket["brain_automation"] = automation
        automation.setdefault("enabled", True)
        automation.setdefault("daily_time", "21:00")
        automation.setdefault("weekly_day", 0)
        automation.setdefault("weekly_time", "09:00")
        automation.setdefault("last_daily_date", "")
        automation.setdefault("last_weekly_key", "")
        automation.setdefault("last_schedule_alert_key", "")
        automation.setdefault("schedule_alert_window_minutes", 60)
        return bucket

    def get_chat_state(self, chat_id: int) -> dict[str, Any]:
        with self._lock:
            bucket = self._bucket(chat_id)
            provider = bucket["provider"]
            return {
                "provider": provider,
                "model": normalize_model(provider, bucket["models"].get(provider)),
                "thread_id": bucket["threads"].get(provider) or None,
                "project_key": bucket.get("project_key") or None,
                "project_name": bucket.get("project_name") or None,
                "project_path": bucket.get("project_path") or None,
                "agent_current_run": bucket.get("agent_current_run"),
                "agent_last_run": bucket.get("agent_last_run"),
                "last_provider_timing": bucket.get("last_provider_timing") if isinstance(bucket.get("last_provider_timing"), dict) else {},
            }

    def set_provider(self, chat_id: int, provider: str) -> dict[str, Any]:
        normalized = normalize_provider(provider)
        with self._lock:
            bucket = self._bucket(chat_id)
            bucket["provider"] = normalized
            bucket["models"][normalized] = normalize_model(
                normalized,
                bucket["models"].get(normalized) or self._settings.default_model,
            )
            self._save()
            return self.get_chat_state(chat_id)

    def set_model(self, chat_id: int, model: str) -> dict[str, Any]:
        with self._lock:
            bucket = self._bucket(chat_id)
            provider = bucket["provider"]
            bucket["models"][provider] = normalize_model(provider, model)
            self._save()
            return self.get_chat_state(chat_id)

    def set_project(self, chat_id: int, key: str, name: str, path: str) -> dict[str, Any]:
        with self._lock:
            bucket = self._bucket(chat_id)
            bucket["project_key"] = key
            bucket["project_name"] = name
            bucket["project_path"] = path
            self._save()
            return self.get_chat_state(chat_id)

    def set_thread_id(self, chat_id: int, provider: str, thread_id: str | None) -> None:
        normalized = normalize_provider(provider)
        with self._lock:
            bucket = self._bucket(chat_id)
            bucket["threads"][normalized] = thread_id or None
            self._save()

    def clear_thread_id(self, chat_id: int) -> None:
        with self._lock:
            bucket = self._bucket(chat_id)
            provider = bucket["provider"]
            bucket["threads"][provider] = None
            self._save()

    def get_agent_queue(self, chat_id: int) -> list[dict[str, Any]]:
        with self._lock:
            bucket = self._bucket(chat_id)
            queue = bucket.get("agent_queue")
            return [item for item in queue if isinstance(item, dict)] if isinstance(queue, list) else []

    def enqueue_agent_job(self, chat_id: int, job: dict[str, Any]) -> int:
        with self._lock:
            bucket = self._bucket(chat_id)
            queue = bucket.setdefault("agent_queue", [])
            if not isinstance(queue, list):
                queue = []
                bucket["agent_queue"] = queue
            queue.append(job)
            self._save()
            return len(queue)

    def pop_agent_job(self, chat_id: int) -> dict[str, Any] | None:
        with self._lock:
            bucket = self._bucket(chat_id)
            queue = bucket.get("agent_queue")
            if not isinstance(queue, list) or not queue:
                return None
            job = queue.pop(0)
            self._save()
            return job if isinstance(job, dict) else None

    def clear_agent_queue(self, chat_id: int) -> None:
        with self._lock:
            bucket = self._bucket(chat_id)
            bucket["agent_queue"] = []
            self._save()

    def recover_agent_current_run(self, chat_id: int) -> dict[str, Any] | None:
        with self._lock:
            bucket = self._bucket(chat_id)
            current = bucket.get("agent_current_run")
            if not isinstance(current, dict):
                return None

            queue = bucket.setdefault("agent_queue", [])
            if not isinstance(queue, list):
                queue = []
                bucket["agent_queue"] = queue

            current_job_id = str(current.get("job_id") or "").strip()
            exists = False
            if current_job_id:
                for item in queue:
                    if isinstance(item, dict) and str(item.get("job_id") or "").strip() == current_job_id:
                        exists = True
                        break

            recovered = dict(current)
            recovered["source"] = str(recovered.get("source") or "recovered")
            recovered["recovered_after_restart"] = True
            if not exists:
                queue.insert(0, recovered)

            bucket["agent_current_run"] = None
            self._save()
            return recovered

    def get_agent_schedules(self, chat_id: int) -> list[dict[str, Any]]:
        with self._lock:
            bucket = self._bucket(chat_id)
            schedules = bucket.get("agent_schedules")
            return [item for item in schedules if isinstance(item, dict)] if isinstance(schedules, list) else []

    def add_agent_schedule(self, chat_id: int, job: dict[str, Any]) -> int:
        with self._lock:
            bucket = self._bucket(chat_id)
            schedules = bucket.setdefault("agent_schedules", [])
            if not isinstance(schedules, list):
                schedules = []
                bucket["agent_schedules"] = schedules
            schedules.append(job)
            self._save()
            return len(schedules)

    def set_agent_schedules(self, chat_id: int, jobs: list[dict[str, Any]]) -> None:
        with self._lock:
            bucket = self._bucket(chat_id)
            bucket["agent_schedules"] = [job for job in jobs if isinstance(job, dict)]
            self._save()

    def clear_agent_schedules(self, chat_id: int) -> None:
        with self._lock:
            bucket = self._bucket(chat_id)
            bucket["agent_schedules"] = []
            self._save()

    def panic_clear_agent_runtime(self, chat_id: int) -> dict[str, int | bool]:
        with self._lock:
            bucket = self._bucket(chat_id)
            queue = bucket.get("agent_queue")
            schedules = bucket.get("agent_schedules")
            queued_jobs = len([item for item in queue if isinstance(item, dict)]) if isinstance(queue, list) else 0
            scheduled_jobs = len([item for item in schedules if isinstance(item, dict)]) if isinstance(schedules, list) else 0
            current = bucket.get("agent_current_run")
            had_current_run = isinstance(current, dict)

            bucket["agent_current_run"] = None
            bucket["agent_queue"] = []
            bucket["agent_schedules"] = []
            self._save()
            return {
                "had_current_run": had_current_run,
                "queued_jobs": queued_jobs,
                "scheduled_jobs": scheduled_jobs,
            }

    def set_agent_current_run(self, chat_id: int, run: dict[str, Any] | None) -> None:
        with self._lock:
            bucket = self._bucket(chat_id)
            bucket["agent_current_run"] = run
            self._save()

    def set_agent_last_run(self, chat_id: int, run: dict[str, Any] | None) -> None:
        with self._lock:
            bucket = self._bucket(chat_id)
            bucket["agent_last_run"] = run
            self._save()

    def set_last_provider_timing(self, chat_id: int, timing: dict[str, Any] | None) -> None:
        with self._lock:
            bucket = self._bucket(chat_id)
            bucket["last_provider_timing"] = timing if isinstance(timing, dict) else {}
            self._save()

    def get_ui_flow(self, chat_id: int) -> dict[str, Any] | None:
        with self._lock:
            bucket = self._bucket(chat_id)
            flow = bucket.get("ui_flow")
            return flow if isinstance(flow, dict) else None

    def set_ui_flow(self, chat_id: int, flow: dict[str, Any] | None) -> None:
        with self._lock:
            bucket = self._bucket(chat_id)
            bucket["ui_flow"] = flow if isinstance(flow, dict) else None
            self._save()

    def clear_ui_flow(self, chat_id: int) -> None:
        self.set_ui_flow(chat_id, None)

    def get_last_schedule_candidate(self, chat_id: int) -> dict[str, Any] | None:
        with self._lock:
            bucket = self._bucket(chat_id)
            candidate = bucket.get("last_schedule_candidate")
            return candidate if isinstance(candidate, dict) else None

    def set_last_schedule_candidate(self, chat_id: int, candidate: dict[str, Any] | None) -> None:
        with self._lock:
            bucket = self._bucket(chat_id)
            bucket["last_schedule_candidate"] = candidate if isinstance(candidate, dict) else None
            self._save()

    def clear_last_schedule_candidate(self, chat_id: int) -> None:
        self.set_last_schedule_candidate(chat_id, None)

    def get_last_schedule_results(self, chat_id: int) -> list[dict[str, Any]]:
        with self._lock:
            bucket = self._bucket(chat_id)
            results = bucket.get("last_schedule_results")
            return [dict(item) for item in results if isinstance(item, dict)] if isinstance(results, list) else []

    def set_last_schedule_results(self, chat_id: int, results: list[dict[str, Any]]) -> None:
        with self._lock:
            bucket = self._bucket(chat_id)
            bucket["last_schedule_results"] = [dict(item) for item in results if isinstance(item, dict)]
            self._save()

    def clear_last_schedule_results(self, chat_id: int) -> None:
        self.set_last_schedule_results(chat_id, [])

    def get_brain_automation(self, chat_id: int) -> dict[str, Any]:
        with self._lock:
            bucket = self._bucket(chat_id)
            automation = bucket.get("brain_automation")
            return dict(automation) if isinstance(automation, dict) else {}

    def update_brain_automation(self, chat_id: int, **changes: Any) -> dict[str, Any]:
        with self._lock:
            bucket = self._bucket(chat_id)
            automation = bucket.setdefault("brain_automation", {})
            if not isinstance(automation, dict):
                automation = {}
                bucket["brain_automation"] = automation
            automation.update(changes)
            self._save()
            return dict(automation)

    def list_chat_ids(self) -> list[int]:
        with self._lock:
            chats = self._state.setdefault("chats", {})
            result: list[int] = []
            for raw in chats.keys():
                try:
                    result.append(int(raw))
                except ValueError:
                    continue
            return sorted(result)

    def list_contacts(self) -> list[dict[str, Any]]:
        with self._lock:
            contacts = self._address_book().get("contacts", {})
            if not isinstance(contacts, dict):
                return []
            results: list[dict[str, Any]] = []
            for key in sorted(contacts.keys()):
                raw = contacts.get(key)
                if not isinstance(raw, dict):
                    continue
                aliases = raw.get("aliases")
                alias_items = (
                    [str(item) for item in aliases if isinstance(item, str)]
                    if isinstance(aliases, list)
                    else []
                )
                results.append(
                    {
                        "key": str(key),
                        "name": str(raw.get("name") or ""),
                        "email": str(raw.get("email") or ""),
                        "aliases": alias_items,
                        "note": str(raw.get("note") or ""),
                    }
                )
            return results

    def get_contact(self, key: str) -> dict[str, Any] | None:
        normalized_key = self._normalize_contact_key(key)
        with self._lock:
            contacts = self._address_book().get("contacts", {})
            if not isinstance(contacts, dict):
                return None
            raw = contacts.get(normalized_key)
            if not isinstance(raw, dict):
                return None
            aliases = raw.get("aliases")
            alias_items = (
                [str(item) for item in aliases if isinstance(item, str)]
                if isinstance(aliases, list)
                else []
            )
            return {
                "key": normalized_key,
                "name": str(raw.get("name") or ""),
                "email": str(raw.get("email") or ""),
                "aliases": alias_items,
                "note": str(raw.get("note") or ""),
            }

    def upsert_contact(
        self,
        *,
        key: str,
        email: str,
        name: str,
        aliases: list[str] | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        normalized_key = self._ensure_contact_key(key)
        normalized_email = self._normalize_email(email)
        normalized_name = str(name or "").strip()
        if not normalized_name:
            raise ValueError("name is required.")
        if not self._is_valid_email(normalized_email):
            raise ValueError("invalid email format.")

        normalized_aliases: list[str] = []
        for candidate in aliases or []:
            clean = self._normalize_alias(candidate)
            if clean and clean not in normalized_aliases:
                normalized_aliases.append(clean)

        with self._lock:
            book = self._address_book()
            contacts = book.get("contacts", {})
            assert isinstance(contacts, dict)
            for existing_key, existing_raw in contacts.items():
                if not isinstance(existing_raw, dict):
                    continue
                existing_email = self._normalize_email(str(existing_raw.get("email") or ""))
                if existing_email and existing_email == normalized_email and str(existing_key) != normalized_key:
                    raise ValueError(f"email already used by contact: {existing_key}")

            contacts[normalized_key] = {
                "name": normalized_name,
                "email": normalized_email,
                "aliases": normalized_aliases,
                "note": str(note or "").strip(),
            }
            self._save()
            current = self.get_contact(normalized_key)
            assert current is not None
            return current

    def remove_contact(self, key: str) -> bool:
        normalized_key = self._normalize_contact_key(key)
        with self._lock:
            contacts = self._address_book().get("contacts", {})
            if not isinstance(contacts, dict):
                return False
            if normalized_key not in contacts:
                return False
            del contacts[normalized_key]
            self._save()
            return True

    def add_contact_alias(self, key: str, alias: str) -> dict[str, Any]:
        normalized_key = self._normalize_contact_key(key)
        normalized_alias = self._normalize_alias(alias)
        if not normalized_alias:
            raise ValueError("alias is required.")
        with self._lock:
            contacts = self._address_book().get("contacts", {})
            if not isinstance(contacts, dict):
                raise ValueError("contact not found.")
            target = contacts.get(normalized_key)
            if not isinstance(target, dict):
                raise ValueError("contact not found.")

            for existing_key, existing_raw in contacts.items():
                if not isinstance(existing_raw, dict) or str(existing_key) == normalized_key:
                    continue
                aliases = existing_raw.get("aliases")
                if not isinstance(aliases, list):
                    continue
                if normalized_alias in [self._normalize_alias(str(item)) for item in aliases]:
                    raise ValueError(f"alias already used by contact: {existing_key}")

            aliases = target.get("aliases")
            alias_items = (
                [self._normalize_alias(str(item)) for item in aliases if self._normalize_alias(str(item))]
                if isinstance(aliases, list)
                else []
            )
            if normalized_alias not in alias_items:
                alias_items.append(normalized_alias)
            target["aliases"] = alias_items
            self._save()
            current = self.get_contact(normalized_key)
            assert current is not None
            return current

    def resolve_contacts(self, tokens: list[str]) -> dict[str, Any]:
        with self._lock:
            contacts = self.list_contacts()

        email_to_contact: dict[str, dict[str, Any]] = {}
        key_to_contact: dict[str, dict[str, Any]] = {}
        name_to_contacts: dict[str, list[dict[str, Any]]] = {}
        alias_to_contacts: dict[str, list[dict[str, Any]]] = {}
        for item in contacts:
            email = self._normalize_email(str(item.get("email") or ""))
            key = self._normalize_contact_key(str(item.get("key") or ""))
            name = self._normalize_alias(str(item.get("name") or ""))
            if email:
                email_to_contact[email] = item
            if key:
                key_to_contact[key] = item
            if name:
                name_to_contacts.setdefault(name, []).append(item)
            for alias in item.get("aliases") or []:
                normalized_alias = self._normalize_alias(str(alias))
                if normalized_alias:
                    alias_to_contacts.setdefault(normalized_alias, []).append(item)

        resolved_emails: list[str] = []
        resolved_contacts: list[dict[str, str]] = []
        unresolved: list[str] = []
        ambiguous: dict[str, list[str]] = {}
        for raw_token in tokens:
            token = str(raw_token or "").strip()
            if not token:
                continue
            token_lower = self._normalize_alias(token)
            if self._is_valid_email(token_lower):
                if token_lower not in resolved_emails:
                    resolved_emails.append(token_lower)
                    if token_lower in email_to_contact:
                        match = email_to_contact[token_lower]
                        resolved_contacts.append(
                            {
                                "token": token,
                                "key": str(match.get("key") or ""),
                                "email": token_lower,
                            }
                        )
                    else:
                        resolved_contacts.append(
                            {
                                "token": token,
                                "key": "",
                                "email": token_lower,
                            }
                        )
                continue

            direct = key_to_contact.get(token_lower)
            if direct is not None:
                email = self._normalize_email(str(direct.get("email") or ""))
                if email and email not in resolved_emails:
                    resolved_emails.append(email)
                resolved_contacts.append(
                    {
                        "token": token,
                        "key": str(direct.get("key") or ""),
                        "email": email,
                    }
                )
                continue

            candidates: list[dict[str, Any]] = []
            candidates.extend(alias_to_contacts.get(token_lower, []))
            candidates.extend(name_to_contacts.get(token_lower, []))
            dedup: dict[str, dict[str, Any]] = {}
            for candidate in candidates:
                candidate_key = str(candidate.get("key") or "")
                if candidate_key and candidate_key not in dedup:
                    dedup[candidate_key] = candidate
            if len(dedup) == 1:
                found = next(iter(dedup.values()))
                email = self._normalize_email(str(found.get("email") or ""))
                if email and email not in resolved_emails:
                    resolved_emails.append(email)
                resolved_contacts.append(
                    {
                        "token": token,
                        "key": str(found.get("key") or ""),
                        "email": email,
                    }
                )
                continue
            if len(dedup) > 1:
                ambiguous[token] = sorted(dedup.keys())
                continue
            unresolved.append(token)

        return {
            "emails": resolved_emails,
            "resolved": resolved_contacts,
            "unresolved": unresolved,
            "ambiguous": ambiguous,
        }
