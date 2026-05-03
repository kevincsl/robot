from __future__ import annotations

import json
import os
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from robot.config import MODEL_DESCRIPTIONS, SUPPORTED_MODELS, Settings, normalize_provider

MODEL_DISCOVERY_TIMEOUT_SECONDS = 15
VISIBLE_MODEL_VISIBILITIES = {"list", "picker"}


@dataclass(frozen=True)
class CatalogModel:
    name: str
    description: str | None = None


@dataclass(frozen=True)
class ModelCatalog:
    provider: str
    items: tuple[CatalogModel, ...]
    source: str
    note: str | None = None


def get_model_catalog(settings: Settings, provider: str) -> ModelCatalog:
    normalized = normalize_provider(provider)
    if normalized == "codex":
        return _load_codex_catalog(settings)
    if normalized == "claude":
        return _load_claude_catalog()
    return _static_catalog(
        normalized,
        source="static fallback",
        note=f"Dynamic discovery is not implemented for {normalized} yet.",
    )


def catalog_model_names(settings: Settings, provider: str) -> set[str]:
    catalog = get_model_catalog(settings, provider)
    return {item.name for item in catalog.items}


def is_catalog_model(settings: Settings, provider: str, model: str) -> bool:
    normalized_model = (model or "").strip()
    if not normalized_model:
        return False
    return normalized_model in catalog_model_names(settings, provider)


def is_custom_model(settings: Settings, model: str) -> bool:
    normalized_model = (model or "").strip()
    if not normalized_model:
        return False
    return normalized_model in {item.strip() for item in settings.custom_models if item.strip()}


def validate_selected_model(settings: Settings, provider: str, model: str) -> tuple[bool, str | None]:
    normalized_provider = normalize_provider(provider)
    normalized_model = (model or "").strip()
    if not normalized_model or normalized_model == "custom":
        return False, None
    if is_catalog_model(settings, normalized_provider, normalized_model):
        return True, None
    if is_custom_model(settings, normalized_model):
        return False, None
    if normalized_provider == "claude" and normalized_model.startswith("claude-"):
        return True, (
            f"Model not available for {normalized_provider}: {normalized_model}\n"
            "Use /models to view available models, then choose again with /model <name>."
        )
    return False, None


def _load_codex_catalog(settings: Settings) -> ModelCatalog:
    command = [*settings.provider_commands["codex"], "debug", "models"]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=MODEL_DISCOVERY_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return _static_catalog(
            "codex",
            source="static fallback",
            note="codex CLI was not found; using static fallback.",
        )
    except OSError as exc:
        return _static_catalog(
            "codex",
            source="static fallback",
            note=f"codex model discovery failed ({exc.__class__.__name__}); using static fallback.",
        )
    except subprocess.TimeoutExpired:
        return _static_catalog(
            "codex",
            source="static fallback",
            note="codex model discovery timed out; using static fallback.",
        )

    if completed.returncode != 0:
        detail = _first_line((completed.stderr or completed.stdout or "").strip())
        note = "codex model discovery failed; using static fallback."
        if detail:
            note = f"{note} {detail}"
        return _static_catalog("codex", source="static fallback", note=note)

    stdout_text = (completed.stdout or "").strip()
    if not stdout_text:
        return _static_catalog(
            "codex",
            source="static fallback",
            note="codex model discovery returned no output; using static fallback.",
        )

    try:
        payload = json.loads(stdout_text)
    except json.JSONDecodeError:
        return _static_catalog(
            "codex",
            source="static fallback",
            note="codex model discovery returned invalid JSON; using static fallback.",
        )

    raw_items = payload.get("models")
    if not isinstance(raw_items, list):
        return _static_catalog(
            "codex",
            source="static fallback",
            note="codex model discovery returned an unexpected payload; using static fallback.",
        )

    ranked_items: list[tuple[int, str, CatalogModel]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        visibility = str(raw_item.get("visibility") or "").strip().lower()
        if visibility and visibility not in VISIBLE_MODEL_VISIBILITIES:
            continue
        name = str(raw_item.get("slug") or "").strip()
        if not name:
            continue
        description = str(raw_item.get("description") or "").strip() or None
        priority_value = raw_item.get("priority")
        try:
            priority = int(priority_value)
        except (TypeError, ValueError):
            priority = 1_000_000
        ranked_items.append((priority, name.casefold(), CatalogModel(name=name, description=description)))

    if not ranked_items:
        return _static_catalog(
            "codex",
            source="static fallback",
            note="codex model discovery returned no visible models; using static fallback.",
        )

    ranked_items.sort(key=lambda item: (item[0], item[1]))
    return ModelCatalog(
        provider="codex",
        items=tuple(item[2] for item in ranked_items),
        source="codex debug models",
        note=None,
    )


def _load_claude_catalog() -> ModelCatalog:
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        return _static_catalog(
            "claude",
            source="static fallback",
            note="ANTHROPIC_API_KEY is not set; using static fallback.",
        )

    base_url = (os.getenv("ROBOT_CLAUDE_API_URL") or "https://api.anthropic.com").strip().rstrip("/")
    url = f"{base_url}/v1/models?limit=1000"
    request = urllib.request.Request(
        url,
        headers={
            "anthropic-version": "2023-06-01",
            "x-api-key": api_key,
            "accept": "application/json",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=MODEL_DISCOVERY_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = _extract_http_error_detail(exc)
        note = "claude model discovery failed; using static fallback."
        if detail:
            note = f"{note} {detail}"
        return _static_catalog("claude", source="static fallback", note=note)
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError, json.JSONDecodeError) as exc:
        return _static_catalog(
            "claude",
            source="static fallback",
            note=f"claude model discovery failed ({exc.__class__.__name__}); using static fallback.",
        )

    raw_items = payload.get("data")
    if not isinstance(raw_items, list):
        return _static_catalog(
            "claude",
            source="static fallback",
            note="claude model discovery returned an unexpected payload; using static fallback.",
        )

    items: list[CatalogModel] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        name = str(raw_item.get("id") or "").strip()
        if not name or name in seen or not name.startswith("claude-"):
            continue
        seen.add(name)
        description = str(raw_item.get("display_name") or "").strip() or None
        items.append(CatalogModel(name=name, description=description))

    if not items:
        return _static_catalog(
            "claude",
            source="static fallback",
            note="claude model discovery returned no models; using static fallback.",
        )

    return ModelCatalog(
        provider="claude",
        items=tuple(items),
        source="anthropic models api",
        note=None,
    )


def _static_catalog(provider: str, *, source: str, note: str | None) -> ModelCatalog:
    descriptions = MODEL_DESCRIPTIONS.get(provider, {})
    items = tuple(
        CatalogModel(name=model_name, description=descriptions.get(model_name))
        for model_name in SUPPORTED_MODELS.get(provider, [])
        if model_name != "custom"
    )
    return ModelCatalog(
        provider=provider,
        items=items,
        source=source,
        note=note,
    )


def _extract_http_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "").strip()
            if message:
                return message
    return f"HTTP {exc.code}"


def _first_line(text: str) -> str:
    if not text:
        return ""
    return text.splitlines()[0].strip()
