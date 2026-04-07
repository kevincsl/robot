from __future__ import annotations

import json
import threading
from typing import Any

from robot.config import Settings, normalize_model, normalize_provider
from robot.projects import get_default_workspace


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
        try:
            self._settings.state_home.mkdir(parents=True, exist_ok=True)
            self._settings.session_state_path.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            return

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
