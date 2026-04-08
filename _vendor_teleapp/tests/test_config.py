from __future__ import annotations

import os
import unittest
from argparse import Namespace
from pathlib import Path

from teleapp.config import build_runtime_config, load_config


class ConfigTests(unittest.TestCase):
    def test_build_runtime_config_reads_env_defaults(self) -> None:
        old_values = {
            "TELEAPP_TOKEN": os.getenv("TELEAPP_TOKEN"),
            "TELEAPP_ALLOWED_USER_ID": os.getenv("TELEAPP_ALLOWED_USER_ID"),
            "TELEAPP_CHAT_ID": os.getenv("TELEAPP_CHAT_ID"),
            "TELEAPP_APP": os.getenv("TELEAPP_APP"),
        }
        try:
            os.environ["TELEAPP_TOKEN"] = "env-token"
            os.environ["TELEAPP_ALLOWED_USER_ID"] = "55"
            os.environ["TELEAPP_CHAT_ID"] = "99"
            os.environ["TELEAPP_APP"] = "examples/echo_app.py"
            os.environ["TELEAPP_AUTO_RESTART_ON_CRASH"] = "1"
            os.environ["TELEAPP_RESTART_BACKOFF_SECONDS"] = "3"
            os.environ["TELEAPP_WATCH_MODE"] = "app-file-only"
            config = build_runtime_config()
            self.assertEqual(config.telegram_token, "env-token")
            self.assertEqual(config.allowed_user_id, 55)
            self.assertEqual(config.telegram_chat_id, 99)
            self.assertEqual(config.app_path, Path("examples/echo_app.py").resolve())
            self.assertTrue(config.auto_restart_on_crash)
            self.assertEqual(config.restart_backoff_seconds, 3)
            self.assertEqual(config.watch_mode, "app-file-only")
            self.assertEqual(config.watch_paths, [Path("examples/echo_app.py").resolve()])
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            os.environ.pop("TELEAPP_AUTO_RESTART_ON_CRASH", None)
            os.environ.pop("TELEAPP_RESTART_BACKOFF_SECONDS", None)
            os.environ.pop("TELEAPP_WATCH_MODE", None)

    def test_load_config_defaults_watch_path_to_app_parent(self) -> None:
        config = load_config(
            Namespace(
                app="examples/echo_app.py",
                token="dummy",
                allowed_user_id=1,
                chat_id=0,
                python_executable="python",
                no_hot_reload=False,
                reload_quiet_seconds=2,
                reload_poll_seconds=1,
                watch=[],
            )
        )
        self.assertEqual(config.app_path.name, "echo_app.py")
        self.assertEqual(config.watch_paths, [config.app_path.parent])
        self.assertEqual(config.watch_mode, "app-dir")
        self.assertTrue(config.hot_reload)

    def test_load_config_uses_explicit_watch_paths(self) -> None:
        config = load_config(
            Namespace(
                app="examples/echo_app.py",
                token="dummy",
                allowed_user_id=1,
                chat_id=99,
                python_executable="python",
                no_hot_reload=True,
                no_auto_restart_on_crash=True,
                reload_quiet_seconds=5,
                reload_poll_seconds=3,
                restart_backoff_seconds=0,
                watch_mode="app-file-only",
                watch=["examples", "teleapp"],
            )
        )
        self.assertEqual(config.telegram_chat_id, 99)
        self.assertFalse(config.hot_reload)
        self.assertFalse(config.auto_restart_on_crash)
        self.assertEqual(config.reload_quiet_seconds, 5)
        self.assertEqual(config.reload_poll_seconds, 3)
        self.assertEqual(config.restart_backoff_seconds, 0)
        self.assertEqual(config.watch_mode, "app-file-only")
        self.assertEqual(
            config.watch_paths,
            [
                Path("examples").resolve(),
                Path("teleapp").resolve(),
            ],
        )


if __name__ == "__main__":
    unittest.main()
