from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from teleapp.singleton import SingletonInstanceError, acquire_singleton, release_singleton


class SingletonTests(unittest.TestCase):
    def tearDown(self) -> None:
        release_singleton()

    def test_lock_error_masks_token_in_exception_message(self) -> None:
        token = "12345:SECRET_TOKEN_VALUE"
        app_path = Path("examples/echo_app.py").resolve()
        if os.name == "nt":
            patch_target = "teleapp.singleton.msvcrt.locking"
        else:  # pragma: no cover
            patch_target = "teleapp.singleton.fcntl.flock"

        with patch(patch_target, side_effect=OSError("busy")):
            with self.assertRaises(SingletonInstanceError) as cm:
                acquire_singleton(app_path, token=token, allowed_user_id=42)

        message = str(cm.exception)
        self.assertIn("token:1234...LUE|user:42", message)
        self.assertNotIn(token, message)
        self.assertNotIn("SECRET_TOKEN_VALUE", message)


if __name__ == "__main__":
    unittest.main()
