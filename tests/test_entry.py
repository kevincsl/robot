from __future__ import annotations

import os
import unittest
from io import StringIO
from unittest.mock import patch

from robot import entry


class EntryTests(unittest.TestCase):
    def test_default_mode_exits_with_supervisor_hint(self) -> None:
        stderr = StringIO()
        with (
            patch("sys.argv", ["robot"]),
            patch("sys.stderr", stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            entry.main()
        self.assertEqual(raised.exception.code, 2)
        output = stderr.getvalue()
        self.assertIn("Use teleapp supervisor mode instead", output)
        self.assertIn("teleapp robot.py", output)

    def test_standalone_mode_sets_env_and_calls_app_main(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("sys.argv", ["robot", "--standalone"]),
            patch("robot.app.main") as app_main,
        ):
            entry.main()
            app_main.assert_called_once_with()
            self.assertEqual(os.environ.get("ROBOT_ALLOW_DIRECT_POLLING"), "1")


if __name__ == "__main__":
    unittest.main()
