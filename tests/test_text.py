from __future__ import annotations

import unittest

from robot.text import normalize_text


class TextTests(unittest.TestCase):
    def test_normalize_text_keeps_cjk_text(self) -> None:
        text = "好接受你的建議開始吧"
        self.assertEqual(normalize_text(text), text)

    def test_normalize_text_coerces_none(self) -> None:
        self.assertEqual(normalize_text(None), "")

    def test_normalize_text_normalizes_combining_sequence(self) -> None:
        self.assertEqual(normalize_text("e\u0301"), "é")


if __name__ == "__main__":
    unittest.main()
