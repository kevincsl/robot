from __future__ import annotations

import os
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from robot.control import build_launch_spec, create_parser, discover_configs, resolve_config


class ControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "README.md").write_text("# sample\n", encoding="utf-8")
        robots_dir = self.root / ".robots"
        robots_dir.mkdir(parents=True, exist_ok=True)
        (robots_dir / "default.env").write_text(
            "\n".join(
                [
                    "TELEAPP_TOKEN=default-token",
                    "TELEAPP_ALLOWED_USER_ID=1",
                    "ROBOT_ID=robot-default",
                    "ROBOT_DEFAULT_PROVIDER=codex",
                    "ROBOT_DEFAULT_MODEL=gpt-5.4",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        (robots_dir / "robot1.env").write_text(
            "\n".join(
                [
                    "TELEAPP_TOKEN=robot1-token",
                    "TELEAPP_ALLOWED_USER_ID=2",
                    "ROBOT_ID=robot-one",
                    "ROBOT_DEFAULT_PROVIDER=claude",
                    "ROBOT_DEFAULT_MODEL=claude-sonnet-4-6",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        self._make_fake_venv()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _make_fake_venv(self) -> None:
        windows_python = self.root / ".venv" / "Scripts" / "python.exe"
        windows_python.parent.mkdir(parents=True, exist_ok=True)
        windows_python.write_text("", encoding="utf-8")

        posix_python = self.root / ".venv" / "bin" / "python"
        posix_python.parent.mkdir(parents=True, exist_ok=True)
        posix_python.write_text("", encoding="utf-8")

    def test_discover_configs_reads_only_dotrobots_envs(self) -> None:
        configs = discover_configs(self.root)
        names = [item.name for item in configs]

        self.assertEqual(names, ["default", "robot1"])
        robot1 = next(item for item in configs if item.name == "robot1")
        self.assertEqual(robot1.robot_id, "robot-one")
        self.assertEqual(robot1.env_file, (self.root / ".robots" / "robot1.env").resolve())

    def test_resolve_config_uses_dotrobots_path(self) -> None:
        resolved = resolve_config(self.root, "robot1")
        self.assertEqual(resolved.robot_id, "robot-one")
        self.assertEqual(resolved.env_file, (self.root / ".robots" / "robot1.env").resolve())

    def test_resolve_config_rejects_legacy_env_naming(self) -> None:
        (self.root / ".env.legacy").write_text(
            "TELEAPP_TOKEN=legacy-token\nROBOT_ID=legacy\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(RuntimeError, "Legacy config naming is no longer supported"):
            resolve_config(self.root, "legacy")

    def test_build_launch_spec_sets_runtime_env_defaults(self) -> None:
        resolved = resolve_config(self.root, "default")
        with patch.dict(
            os.environ,
            {
                "HTTP_PROXY": "http://proxy",
                "PYTHONPATH": "C:\\existing",
            },
            clear=True,
        ):
            spec = build_launch_spec(self.root, resolved)

        self.assertEqual(spec.teleapp_app, "robot.py")
        self.assertEqual(spec.provider, "codex")
        self.assertEqual(spec.model, "gpt-5.4")
        self.assertEqual(spec.env["ROBOT_ENV_FILE"], str((self.root / ".robots" / "default.env").resolve()))
        self.assertEqual(spec.env["TELEAPP_PYTHON"], str((self.root / ".venv" / "Scripts" / "python.exe")))
        self.assertEqual(spec.env["HTTP_PROXY"], "")
        self.assertTrue(spec.env["PYTHONPATH"].startswith(str(self.root)))
        self.assertEqual(spec.command[1:4], ["-m", "teleapp", "robot.py"])

    def test_parser_accepts_slash_h_help(self) -> None:
        parser = create_parser()
        with patch("sys.stdout", StringIO()), self.assertRaises(SystemExit) as raised:
            parser.parse_args(["/h"])
        self.assertEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
