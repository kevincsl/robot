from __future__ import annotations

import os
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from robot.control import (
    _doctor_windows,
    _background_supervisor_command,
    _env_values,
    _is_pid_running,
    _log_file,
    _migrate_legacy_root_logs,
    _spawn_background_supervisor,
    build_launch_spec,
    cmd_doctor,
    create_parser,
    discover_configs,
    resolve_config,
)


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
        windows_pythonw = self.root / ".venv" / "Scripts" / "pythonw.exe"
        windows_pythonw.write_text("", encoding="utf-8")

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

    def test_env_values_supports_utf8_bom(self) -> None:
        path = self.root / ".robots" / "bom.env"
        path.write_text("TELEAPP_TOKEN=bom-token\n", encoding="utf-8-sig")
        values = _env_values(path)
        self.assertEqual(values.get("TELEAPP_TOKEN"), "bom-token")

    def test_parser_accepts_slash_h_help(self) -> None:
        parser = create_parser()
        with patch("sys.stdout", StringIO()), self.assertRaises(SystemExit) as raised:
            parser.parse_args(["/h"])
        self.assertEqual(raised.exception.code, 0)

    def test_parser_supports_doctor_command(self) -> None:
        parser = create_parser()
        args = parser.parse_args(["doctor"])
        self.assertEqual(args.command, "doctor")
        self.assertEqual(args.target, "all")

    def test_log_file_is_under_robot_state_logs(self) -> None:
        path = _log_file(self.root, "robot1")
        self.assertEqual(path, self.root / ".robot_state" / "logs" / "robot1.log")

    def test_legacy_root_logs_are_migrated(self) -> None:
        source = self.root / "robot.stderr.log"
        source.write_text("legacy\n", encoding="utf-8")

        moved = _migrate_legacy_root_logs(self.root)

        self.assertEqual(len(moved), 1)
        self.assertFalse(source.exists())
        self.assertTrue((self.root / ".robot_state" / "logs" / "legacy-root" / "robot.stderr.log").exists())

    def test_is_pid_running_uses_tasklist_on_windows(self) -> None:
        completed = Mock(returncode=0, stdout='"python.exe","1234","Console","1","10,000 K"\n')
        with patch("robot.control.os.name", "nt"), patch("robot.control.subprocess.run", return_value=completed):
            self.assertTrue(_is_pid_running(1234))

    def test_doctor_reports_issue_for_missing_token(self) -> None:
        bad_path = self.root / ".robots" / "bad.env"
        bad_path.write_text("TELEAPP_ALLOWED_USER_ID=9\n", encoding="utf-8")
        args = type("Args", (), {"target": "bad"})()

        with patch("sys.stdout", new_callable=StringIO) as output:
            code = cmd_doctor(create_parser(), args, self.root)

        self.assertEqual(code, 1)
        self.assertIn("bad: ISSUE", output.getvalue())
        self.assertIn("TELEAPP_TOKEN missing", output.getvalue())

    def test_doctor_windows_rejects_non_windows(self) -> None:
        with patch("robot.control.os.name", "posix"), patch("sys.stdout", new_callable=StringIO) as output:
            code = _doctor_windows()
        self.assertEqual(code, 1)
        self.assertIn("only supported on Windows", output.getvalue())

    def test_cmd_doctor_windows_path(self) -> None:
        args = type("Args", (), {"target": "windows"})()
        with patch("robot.control._doctor_windows", return_value=0) as doctor_windows:
            code = cmd_doctor(create_parser(), args, self.root)
        self.assertEqual(code, 0)
        doctor_windows.assert_called_once()

    def test_spawn_background_supervisor_uses_no_window_flags_on_windows(self) -> None:
        captured: dict[str, object] = {}

        class DummyProcess:
            pid = 43210

        def fake_popen(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return DummyProcess()

        with patch("robot.control.os.name", "nt"), patch("robot.control.subprocess.CREATE_NO_WINDOW", 0x08000000), patch(
            "robot.control.subprocess.Popen",
            side_effect=fake_popen,
        ):
            pid = _spawn_background_supervisor(
                self.root,
                "default",
                restart_policy="on-failure",
                restart_delay=3.0,
                max_restarts=0,
            )

        self.assertEqual(pid, 43210)
        creationflags = int(captured["kwargs"]["creationflags"])  # type: ignore[index]
        self.assertTrue(creationflags & 0x08000000)

    def test_background_supervisor_command_uses_python_on_windows(self) -> None:
        with patch("robot.control.os.name", "nt"):
            command = _background_supervisor_command(
                self.root,
                "default",
                restart_policy="on-failure",
                restart_delay=3.0,
                max_restarts=0,
            )
        self.assertTrue(command[0].lower().endswith("python.exe"))


if __name__ == "__main__":
    unittest.main()
