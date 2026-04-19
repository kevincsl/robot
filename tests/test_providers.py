from __future__ import annotations

import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from robot.config import load_settings
from robot.providers import _run_codex


class ProvidersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        (root / "README.md").write_text("# robot\n", encoding="utf-8")
        self.settings = load_settings(root)
        self.workdir = root

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_run_codex_uses_partial_delta_when_stream_disconnects(self) -> None:
        stdout = "\n".join(
            [
                '{"type":"thread.started","thread_id":"thread-123"}',
                '{"type":"response.output_text.delta","delta":"hello"}',
                '{"type":"response.output_text.delta","delta":" world"}',
                '{"type":"error","message":"stream disconnected before completion: stream closed before response.completed"}',
            ]
        )
        completed = subprocess.CompletedProcess(
            ["codex"],
            1,
            stdout,
            "",
        )

        async def fake_run_process(*args, **kwargs):
            return completed

        with patch("robot.providers._run_process", side_effect=fake_run_process):
            result = asyncio.run(
                _run_codex(
                    self.settings,
                    model="gpt-5.4",
                    prompt="hello",
                    thread_id=None,
                    workdir=self.workdir,
                    project_label="robot",
                    invocation=None,
                )
            )

        self.assertEqual(result.thread_id, "thread-123")
        self.assertEqual(result.return_code, 1)
        self.assertIn("Codex failed (code 1).", result.final_text)
        self.assertIn("hello world", result.final_text)

    def test_run_codex_reads_text_from_response_completed(self) -> None:
        stdout = "\n".join(
            [
                '{"type":"thread.started","thread_id":"thread-xyz"}',
                '{"type":"response.completed","response":{"output":[{"type":"message","content":[{"type":"output_text","text":"final answer text"}]}]}}',
            ]
        )
        completed = subprocess.CompletedProcess(
            ["codex"],
            0,
            stdout,
            "",
        )

        async def fake_run_process(*args, **kwargs):
            return completed

        with patch("robot.providers._run_process", side_effect=fake_run_process):
            result = asyncio.run(
                _run_codex(
                    self.settings,
                    model="gpt-5.4",
                    prompt="hello",
                    thread_id=None,
                    workdir=self.workdir,
                    project_label="robot",
                    invocation=None,
                )
            )

        self.assertEqual(result.thread_id, "thread-xyz")
        self.assertEqual(result.return_code, 0)
        self.assertIn("final answer text", result.final_text)

    def test_run_codex_accepts_data_prefix_json_lines(self) -> None:
        stdout = "\n".join(
            [
                'data: {"type":"thread.started","thread_id":"thread-data"}',
                'data: {"type":"response.output_text.delta","delta":"hello data"}',
            ]
        )
        completed = subprocess.CompletedProcess(["codex"], 0, stdout, "")

        async def fake_run_process(*args, **kwargs):
            return completed

        with patch("robot.providers._run_process", side_effect=fake_run_process):
            result = asyncio.run(
                _run_codex(
                    self.settings,
                    model="gpt-5.4",
                    prompt="hello",
                    thread_id=None,
                    workdir=self.workdir,
                    project_label="robot",
                    invocation=None,
                )
            )

        self.assertEqual(result.thread_id, "thread-data")
        self.assertIn("hello data", result.final_text)

    def test_run_codex_extracts_message_item_without_agent_message_type(self) -> None:
        stdout = "\n".join(
            [
                '{"type":"item.completed","item":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"assistant via message item"}]}}',
            ]
        )
        completed = subprocess.CompletedProcess(["codex"], 0, stdout, "")

        async def fake_run_process(*args, **kwargs):
            return completed

        with patch("robot.providers._run_process", side_effect=fake_run_process):
            result = asyncio.run(
                _run_codex(
                    self.settings,
                    model="gpt-5.4",
                    prompt="hello",
                    thread_id=None,
                    workdir=self.workdir,
                    project_label="robot",
                    invocation=None,
                )
            )

        self.assertIn("assistant via message item", result.final_text)

    def test_run_codex_retries_once_on_stream_disconnect_without_text(self) -> None:
        first = subprocess.CompletedProcess(
            ["codex"],
            1,
            '{"type":"error","message":"stream disconnected before completion: stream closed before response.completed"}',
            "",
        )
        second = subprocess.CompletedProcess(
            ["codex"],
            0,
            '{"type":"response.output_text.delta","delta":"retry success"}',
            "",
        )

        async def fake_run_process(*args, **kwargs):
            call_count = getattr(fake_run_process, "count", 0) + 1
            fake_run_process.count = call_count
            return first if call_count == 1 else second

        with patch("robot.providers._run_process", side_effect=fake_run_process):
            result = asyncio.run(
                _run_codex(
                    self.settings,
                    model="gpt-5.4",
                    prompt="hello",
                    thread_id=None,
                    workdir=self.workdir,
                    project_label="robot",
                    invocation=None,
                )
            )

        self.assertEqual(getattr(fake_run_process, "count", 0), 2)
        self.assertEqual(result.return_code, 0)
        self.assertIn("retry success", result.final_text)

    def test_run_codex_retries_with_fresh_thread_on_context_window_exhausted(self) -> None:
        first = subprocess.CompletedProcess(
            ["codex"],
            1,
            '{"type":"error","message":"Codex ran out of room in the model\'s context window. Start a new thread or clear earlier history before retrying."}',
            "",
        )
        second = subprocess.CompletedProcess(
            ["codex"],
            0,
            '\n'.join(
                [
                    '{"type":"thread.started","thread_id":"thread-fresh-1"}',
                    '{"type":"response.output_text.delta","delta":"fresh thread success"}',
                ]
            ),
            "",
        )
        seen_commands: list[list[str]] = []

        async def fake_run_process(command, *args, **kwargs):
            seen_commands.append(list(command))
            call_count = len(seen_commands)
            return first if call_count == 1 else second

        with patch("robot.providers._run_process", side_effect=fake_run_process):
            result = asyncio.run(
                _run_codex(
                    self.settings,
                    model="gpt-5.4",
                    prompt="hello",
                    thread_id="thread-old-ctx",
                    workdir=self.workdir,
                    project_label="robot",
                    invocation=None,
                )
            )

        self.assertEqual(len(seen_commands), 2)
        self.assertIn("resume", seen_commands[0])
        self.assertNotIn("resume", seen_commands[1])
        self.assertEqual(result.return_code, 0)
        self.assertEqual(result.thread_id, "thread-fresh-1")
        self.assertIn("fresh thread success", result.final_text)


if __name__ == "__main__":
    unittest.main()
