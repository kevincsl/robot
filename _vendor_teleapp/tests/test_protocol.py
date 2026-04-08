from __future__ import annotations

import json
import unittest

from teleapp.protocol import decode_output_line, encode_input_event


class ProtocolTests(unittest.TestCase):
    def test_encode_input_event_includes_request_id(self) -> None:
        payload = json.loads(encode_input_event(123, "hello", request_id="req-1"))
        self.assertEqual(payload["chat_id"], 123)
        self.assertEqual(payload["text"], "hello")
        self.assertEqual(payload["request_id"], "req-1")

    def test_decode_output_line_parses_request_id(self) -> None:
        event = decode_output_line(
            '{"type":"output","chat_id":123,"request_id":"req-1","text":"ok"}',
            stream="stdout",
        )
        assert event is not None
        self.assertEqual(event.type, "output")
        self.assertEqual(event.chat_id, 123)
        self.assertEqual(event.request_id, "req-1")
        self.assertEqual(event.text, "ok")

    def test_encode_input_event_replaces_invalid_surrogates(self) -> None:
        raw = "ok\ud83d\ud800x"
        payload = json.loads(encode_input_event(123, raw, request_id="req-2"))
        self.assertEqual(payload["text"], "ok??x")


if __name__ == "__main__":
    unittest.main()
