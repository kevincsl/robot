from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from robot.config import load_settings
from robot.model_catalog import get_model_catalog, validate_selected_model


class ModelCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "README.md").write_text("# robot\n", encoding="utf-8")
        self.settings = load_settings(self.root)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_codex_catalog_uses_dynamic_models_and_filters_hidden_entries(self) -> None:
        payload = {
            "models": [
                {
                    "slug": "gpt-5.4",
                    "visibility": "list",
                    "description": "Strong model for everyday coding.",
                    "priority": 10,
                },
                {
                    "slug": "codex-auto-review",
                    "visibility": "hide",
                    "description": "Hidden review model.",
                    "priority": 0,
                },
                {
                    "slug": "gpt-5.5",
                    "visibility": "list",
                    "description": "Frontier model for complex work.",
                    "priority": 0,
                },
            ]
        }
        completed = subprocess.CompletedProcess(
            ["codex", "debug", "models"],
            0,
            json.dumps(payload),
            "",
        )

        with patch("robot.model_catalog.subprocess.run", return_value=completed) as mock_run:
            catalog = get_model_catalog(self.settings, "codex")

        self.assertEqual(catalog.source, "codex debug models")
        self.assertIsNone(catalog.note)
        self.assertEqual([item.name for item in catalog.items], ["gpt-5.5", "gpt-5.4"])
        self.assertEqual(
            [item.description for item in catalog.items],
            ["Frontier model for complex work.", "Strong model for everyday coding."],
        )
        mock_run.assert_called_once()

    def test_codex_catalog_falls_back_to_static_when_json_is_invalid(self) -> None:
        completed = subprocess.CompletedProcess(
            ["codex", "debug", "models"],
            0,
            "{not-json}",
            "",
        )

        with patch("robot.model_catalog.subprocess.run", return_value=completed):
            catalog = get_model_catalog(self.settings, "codex")

        self.assertEqual(catalog.source, "static fallback")
        self.assertIn("invalid JSON", catalog.note or "")
        self.assertIn("gpt-5.3-codex", [item.name for item in catalog.items])

    def test_claude_catalog_uses_models_api(self) -> None:
        payload = {
            "data": [
                {"id": "claude-opus-4-7", "display_name": "Claude Opus 4.7"},
                {"id": "claude-sonnet-4-6", "display_name": "Claude Sonnet 4.6"},
            ]
        }

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return json.dumps(payload).encode("utf-8")

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}, clear=True):
            with patch("robot.model_catalog.urllib.request.urlopen", return_value=_Response()) as mock_urlopen:
                catalog = get_model_catalog(self.settings, "claude")

        self.assertEqual(catalog.source, "anthropic models api")
        self.assertIsNone(catalog.note)
        self.assertEqual([item.name for item in catalog.items], ["claude-opus-4-7", "claude-sonnet-4-6"])
        self.assertEqual([item.description for item in catalog.items], ["Claude Opus 4.7", "Claude Sonnet 4.6"])
        mock_urlopen.assert_called_once()

    def test_claude_catalog_falls_back_to_static_without_api_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            catalog = get_model_catalog(self.settings, "claude")

        self.assertEqual(catalog.source, "static fallback")
        self.assertIn("ANTHROPIC_API_KEY is not set", catalog.note or "")
        self.assertEqual(
            [item.name for item in catalog.items],
            ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"],
        )

    def test_validate_selected_model_rejects_missing_claude_catalog_model(self) -> None:
        with patch("robot.model_catalog.get_model_catalog") as mock_catalog:
            mock_catalog.return_value = type("Catalog", (), {"items": (), "provider": "claude", "source": "test", "note": None})()
            is_catalog_model, error = validate_selected_model(self.settings, "claude", "claude-not-real")

        self.assertTrue(is_catalog_model)
        self.assertIsNotNone(error)
        self.assertIn("Model not available for claude", error or "")

    def test_validate_selected_model_keeps_custom_models_allowed(self) -> None:
        with patch.dict("os.environ", {"ROBOT_CUSTOM_MODELS": "deepseek-chat"}, clear=True):
            settings = load_settings(self.root)
        is_catalog_model, error = validate_selected_model(settings, "claude", "deepseek-chat")
        self.assertFalse(is_catalog_model)
        self.assertIsNone(error)

    def test_validate_selected_model_does_not_block_non_claude_unknowns(self) -> None:
        is_catalog_model, error = validate_selected_model(self.settings, "codex", "gpt-unknown-custom")
        self.assertFalse(is_catalog_model)
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
