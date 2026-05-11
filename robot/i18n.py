"""
i18n — internationalization helper.

Loads locale-specific JSON files at import time and provides a simple
`tr(key, **kwargs)` interface, where `key` is a dot-separated path
into the loaded JSON tree.

Usage:
    from robot.i18n import tr

    # Simple lookup
    tr("brain.no_results", text="AI")

    # With locale switch (future)
    from robot.i18n import set_locale
    set_locale("en")
    tr("brain.no_results", text="AI")
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_I18N_DIR = Path(__file__).parent / "i18n"
_DEFAULT_LOCALE = "zh"
_current_locale: str = _DEFAULT_LOCALE
_cache: dict[str, Any] = {}


def _load(locale: str) -> dict[str, Any]:
    """Load (and cache) a locale file."""
    if locale in _cache:
        return _cache[locale]
    path = _I18N_DIR / locale / "ui_strings.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    else:
        # Fallback: root ui_strings.json
        root = _I18N_DIR / "ui_strings.json"
        if root.exists():
            with open(root, encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {}
    _cache[locale] = data
    return data


def _get(data: dict[str, Any], path: str) -> str:
    """Traverse `data` along dot-separated `path`, return last segment."""
    parts = path.split(".")
    try:
        for part in parts:
            data = data[part]  # type: ignore[index]
        if not isinstance(data, str):
            raise TypeError(f"tr path '{path}' resolved to non-string: {type(data)}")
        return data
    except (KeyError, TypeError):
        return f"[i18n missing: {path}]"


def tr(key: str, **kwargs: Any) -> str:
    """
    Look up `key` in the current locale's ui_strings.json and format
    it with `**kwargs` via str.format().

    Returns a placeholder string if the key is missing.
    """
    data = _load(_current_locale)
    template = _get(data, key)
    if kwargs:
        try:
            return template.format(**kwargs)
        except KeyError as e:
            return f"[i18n format error: {e}]"
    return template


def set_locale(locale: str) -> None:
    """Switch the active locale (e.g. 'en' or 'zh')."""
    global _current_locale
    _current_locale = locale


def get_locale() -> str:
    """Return the currently active locale."""
    return _current_locale


def tr_tokens(key: str) -> list[str]:
    """Return a list from ui_strings (e.g. detect_skip_tokens)."""
    data = _load(_current_locale)
    val = _get(data, key)
    if isinstance(val, list):
        return val
    return []


# ── Provider ────────────────────────────────────────────────────────────────

_PROVIDERS: dict[str, dict[str, str]] | None = None


def _load_providers() -> dict[str, dict[str, str]]:
    global _PROVIDERS
    if _PROVIDERS is None:
        path = _I18N_DIR / "providers.json"
        with open(path, encoding="utf-8") as f:
            _PROVIDERS = json.load(f)
    return _PROVIDERS  # type: ignore[return-value]


def provider_name(provider_id: str) -> str:
    """Return the localized display name for a provider (e.g. 'Codex')."""
    data = _load_providers()
    entry = data.get(provider_id, {})
    # Try locale-specific key, then zh fallback for zh-cn/zh-hk, then generic name
    candidates = [f"name_{_current_locale}"]
    if _current_locale in ("zh-cn", "zh-hk"):
        candidates.append("name_zh")
    candidates.append("name")
    for key in candidates:
        if key in entry:
            return entry[key]
    return provider_id


def provider_attr(provider_id: str, attr: str) -> str | None:
    """Return a specific attribute for a provider, or None."""
    data = _load_providers()
    return data.get(provider_id, {}).get(attr)


# ── Models ────────────────────────────────────────────────────────────────────

_MODELS: dict[str, list[dict[str, Any]]] | None = None


def _load_models() -> dict[str, list[dict[str, Any]]]:
    global _MODELS
    if _MODELS is None:
        path = _I18N_DIR / "models.json"
        with open(path, encoding="utf-8") as f:
            _MODELS = json.load(f)
    return _MODELS  # type: ignore[return-value]


def model_list(provider_id: str) -> list[dict[str, Any]]:
    """Return the model list for a provider."""
    return _load_models().get(provider_id, [])


def model_description(provider_id: str, model_id: str) -> str:
    """Return the localized description for a (provider, model) pair."""
    candidates = [f"description_{_current_locale}"]
    if _current_locale in ("zh-cn", "zh-hk"):
        candidates.append("description_zh")
    candidates.append("description")
    for m in _load_models().get(provider_id, []):
        if m.get("id") == model_id:
            for key in candidates:
                if key in m:
                    return m[key]
            return model_id
    return model_id


def model_attr(provider_id: str, model_id: str, attr: str) -> Any:
    """Return a specific attribute for a model, or a placeholder."""
    for m in _load_models().get(provider_id, []):
        if m.get("id") == model_id:
            return m.get(attr, "")
    return ""


# ── VALID_PROVIDER_MODEL_COMBOS ──────────────────────────────────────────────

def valid_combos() -> set[tuple[str, str]]:
    """Return all valid (provider, model) pairs, built from models.json."""
    combos: set[tuple[str, str]] = set()
    for provider, models in _load_models().items():
        for m in models:
            if mid := m.get("id"):
                combos.add((provider, mid))
    return combos


def is_valid_combo(provider: str, model: str) -> bool:
    """Return True if (provider, model) is a known valid combination."""
    return (provider, model) in valid_combos()
