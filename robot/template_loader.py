"""多語系 + 多平台顯示模板載入層"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class TemplateNotFoundError(KeyError):
    """找不到指定的 locale + platform 組合"""


class TemplateKeyMissingError(KeyError):
    """模板檔案缺少必要 key"""


@dataclass(frozen=True)
class DisplayModeTemplates:
    """
    單一 locale + platform 的 display_mode 模板集合。
    所有實例由 TemplateRegistry 統一管理。
    """
    locale: str
    platform: str
    _raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def _v(self, *keys: str) -> Any:
        """依序取嵌套 dict 值。"""
        d = self._raw
        for k in keys:
            d = d[k]
        return d

    # ── mode_labels ──────────────────────────────
    def mode_label(self, mode: str) -> str:
        return self._v("mode_labels", mode)

    # ── mode_changed ─────────────────────────────
    def mode_changed(self, mode: str) -> str:
        return self._v("mode_changed", mode)

    # ── mode_status ──────────────────────────────
    def mode_status_current(self, label: str) -> str:
        return self._v("mode_status", "current_label").format(label=label)

    def mode_status_content(self, mode: str) -> str:
        return self._v("mode_status", f"{mode}_content")

    def mode_status_usage(self) -> str:
        return self._v("mode_status", "usage")

    # ── user_progress ────────────────────────────
    def user_progress_processing(self, tag: str, elapsed: str) -> str:
        return self._v("user_progress", "processing").format(tag=tag, elapsed=elapsed)

    def user_progress_received(self, tag: str) -> str:
        return self._v("user_progress", "received").format(tag=tag)

    # ── project_tag ─────────────────────────────
    def project_tag_with_branch(self, name: str, branch: str) -> str:
        return self._v("project_tag", "with_branch").format(name=name, branch=branch)

    def project_tag_without_branch(self, text: str) -> str:
        return self._v("project_tag", "without_branch").format(text=text)

    # ── recovered_run ───────────────────────────
    def recovered_run(self, mode: str) -> str:
        return self._v("recovered_run", mode)

    # ── run_stopped ─────────────────────────────
    def run_stopped(self, mode: str, tag: str, elapsed: str) -> str:
        return self._v("run_stopped", mode).format(tag=tag, elapsed=elapsed)

    def run_stopped_developer(self) -> str:
        return self._v("run_stopped", "developer")

    # ── output_text ──────────────────────────────
    def output_cancelled(self) -> str:
        return self._v("output_text", "cancelled")

    def output_success(self) -> str:
        return self._v("output_text", "success")

    def output_failure(self) -> str:
        return self._v("output_text", "failure")

    # ── wrapper_strip ───────────────────────────
    def wrapper_project_prefix(self) -> str:
        return self._v("wrapper_strip", "project_prefix")

    def wrapper_completion_success(self) -> str:
        return self._v("wrapper_strip", "completion_success")

    def wrapper_completion_failure(self) -> str:
        return self._v("wrapper_strip", "completion_failure")

    def wrapper_completion_cancelled(self) -> str:
        return self._v("wrapper_strip", "completion_cancelled")

    def wrapper_icons(self) -> tuple[str, ...]:
        return tuple(self._v("wrapper_strip", "icons"))

    # ── footer_prefixes ─────────────────────────
    def footer_prefixes(self) -> tuple[str, ...]:
        return tuple(self._v("footer_prefixes"))

    def footer_prefixes_normalized(self) -> tuple[str, ...]:
        return tuple(p.lower() for p in self._v("footer_prefixes"))

    # ── footer_origin ────────────────────────────
    def footer_origin(self, origin: str) -> str:
        return self._v("footer_origin", "template").format(origin=origin)

    # ── developer_templates ─────────────────────
    def developer_run_started(self, kind: str, **kwargs: str) -> str:
        key = "run_started_auto" if kind == "auto_dev" else "run_started_provider"
        return self._v("developer_templates", key).format(**kwargs)

    def developer_run_queued(self, kind: str, **kwargs: str) -> str:
        key = "run_queued_auto" if kind == "auto_dev" else "run_queued_provider"
        return self._v("developer_templates", key).format(**kwargs)

    def developer_queue_waiting(self, **kwargs: str) -> str:
        return self._v("developer_templates", "queue_waiting").format(**kwargs)

    def developer_worker_started(self, **kwargs: str) -> str:
        return self._v("developer_templates", "worker_started").format(**kwargs)

    def developer_heartbeat(self, **kwargs: str) -> str:
        return self._v("developer_templates", "heartbeat").format(**kwargs)

    def developer_run_finished(self, **kwargs: str) -> str:
        return self._v("developer_templates", "run_finished").format(**kwargs)

    def developer_recovered_run(self, **kwargs: str) -> str:
        return self._v("developer_templates", "recovered_run").format(**kwargs)


class TemplateRegistry:
    """
    全域模板 registry。
    懶惰載入：首次請求 locale/platform 時才讀取 YAML。
    已載入的模板會快取。
    """
    REQUIRED_KEYS = frozenset({
        "mode_labels", "mode_changed", "mode_status",
        "user_progress", "project_tag", "recovered_run",
        "run_stopped", "output_text", "wrapper_strip",
        "footer_prefixes", "footer_origin", "developer_templates",
    })

    def __init__(self, templates_root: Path | None = None) -> None:
        if templates_root is None:
            templates_root = Path(__file__).parent / "templates"
        object.__setattr__(self, "_root", templates_root)
        object.__setattr__(self, "_cache", {})

    def get(self, locale: str, platform: str) -> DisplayModeTemplates:
        """取得指定 locale + platform 的模板實例。"""
        cache_key = (locale, platform)
        if cache_key in self._cache:
            return self._cache[cache_key]

        tmpl = self._load(locale, platform)
        self._cache[cache_key] = tmpl
        return tmpl

    def _load(self, locale: str, platform: str) -> DisplayModeTemplates:
        # Normalize locale: zh-cn → zh_cn (underscores for filesystem compat)
        filename = locale.replace("-", "_")
        path = self._root / "display_mode" / platform / f"{filename}.yaml"
        if not path.exists():
            raise TemplateNotFoundError(
                f"Template not found: {path}. "
                f"Check that locale '{locale}' and platform '{platform}' are supported."
            )

        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML in {path}: {exc}") from exc

        if not isinstance(raw, dict):
            raise ValueError(f"Expected dict root in {path}, got {type(raw).__name__}")

        missing = self.REQUIRED_KEYS - raw.keys()
        if missing:
            raise TemplateKeyMissingError(
                f"Template {path} is missing required keys: {sorted(missing)}"
            )

        return DisplayModeTemplates(locale=locale, platform=platform, _raw=raw)

    def available_locales(self, platform: str) -> list[str]:
        """列出指定平台下所有可用的 locale"""
        platform_dir = self._root / "display_mode" / platform
        if not platform_dir.is_dir():
            return []
        return sorted(
            p.stem for p in platform_dir.iterdir()
            if p.suffix in {".yaml", ".yml"} and p.is_file()
        )

    def available_platforms(self) -> list[str]:
        """列出所有可用的 platform"""
        base = self._root / "display_mode"
        if not base.is_dir():
            return []
        return sorted(
            d.name for d in base.iterdir()
            if d.is_dir()
        )

    def clear_cache(self) -> None:
        """清除所有已快取的模板。"""
        self._cache.clear()

    def clear_cache_for_locale(self, locale: str, platform: str) -> None:
        """清除指定 locale + platform 的快取（下次請求時會重新載入）。"""
        self._cache.pop((locale, platform), None)


# ── 全域單例 ──────────────────────────────────────────────
_DEFAULT_REGISTRY: TemplateRegistry | None = None


def get_templates(
    locale: str = "zh_TW",
    platform: str = "telegram",
    registry: TemplateRegistry | None = None,
) -> DisplayModeTemplates:
    """取得模板實例的便捷函式。預設使用全域 registry。"""
    if registry is not None:
        return registry.get(locale, platform)
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = TemplateRegistry()
    return _DEFAULT_REGISTRY.get(locale, platform)


def clear_templates_cache() -> None:
    """清除全域 registry 的所有快取（驅動 locale 切換）。"""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is not None:
        _DEFAULT_REGISTRY.clear_cache()