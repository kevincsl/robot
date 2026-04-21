from __future__ import annotations

import asyncio
import os
import subprocess
import threading
import time
from pathlib import Path

from teleapp.protocol import AppEvent, decode_output_line, encode_input_event


class ProcessRunner:
    def __init__(self, *, loop: asyncio.AbstractEventLoop, python_executable: str, app_path: Path) -> None:
        self._loop = loop
        self._python_executable = python_executable
        self._app_path = app_path
        self._process: subprocess.Popen[str] | None = None
        self._stdin_lock = threading.Lock()
        self._queue: asyncio.Queue[AppEvent] = asyncio.Queue()

    @property
    def queue(self) -> asyncio.Queue[AppEvent]:
        return self._queue

    @property
    def process(self) -> subprocess.Popen[str] | None:
        return self._process

    def start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return

        env = os.environ.copy()
        teleapp_root = str(Path(__file__).resolve().parent.parent)
        current_pythonpath = env.get("PYTHONPATH", "")
        if current_pythonpath.strip():
            env["PYTHONPATH"] = teleapp_root + os.pathsep + current_pythonpath
        else:
            env["PYTHONPATH"] = teleapp_root
        # Force child Python stdio to UTF-8 so JSON payloads keep CJK text intact on Windows.
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        self._process = subprocess.Popen(
            [self._python_executable, str(self._app_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        assert self._process.stdout is not None
        assert self._process.stderr is not None
        pid = self._process.pid

        threading.Thread(
            target=self._read_stream,
            args=(self._process.stdout, "stdout", pid),
            daemon=True,
            name="teleapp-stdout",
        ).start()
        threading.Thread(
            target=self._read_stream,
            args=(self._process.stderr, "stderr", pid),
            daemon=True,
            name="teleapp-stderr",
        ).start()
        threading.Thread(
            target=self._wait_for_exit,
            args=(pid,),
            daemon=True,
            name="teleapp-exit",
        ).start()

    def stop(self) -> int | None:
        if self._process is None:
            return None

        process = self._process
        self._process = None

        if process.poll() is None:
            self._terminate_process_tree(process)

        self._close_streams(process)
        return process.pid

    def _terminate_process_tree(self, process: subprocess.Popen[str]) -> None:
        try:
            process.terminate()
            process.wait(timeout=3)
            return
        except subprocess.TimeoutExpired:
            pass

        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
            except OSError:
                pass
            self._wait_for_process_exit(process, timeout=5)
            return

        process.kill()
        process.wait(timeout=5)

    @staticmethod
    def _wait_for_process_exit(process: subprocess.Popen[str], timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return
            time.sleep(0.1)
        try:
            process.kill()
        except OSError:
            pass
        process.wait(timeout=5)

    def send_input(
        self,
        *,
        chat_id: int,
        text: str,
        request_id: str,
        command: str | None = None,
        raw: dict | None = None,
    ) -> None:
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            raise RuntimeError("Hosted app is not running.")

        line = encode_input_event(chat_id, text, request_id=request_id, command=command, raw=raw)
        with self._stdin_lock:
            process.stdin.write(line + "\n")
            process.stdin.flush()

    def _emit(self, event: AppEvent) -> None:
        self._loop.call_soon_threadsafe(self._queue.put_nowait, event)

    def _read_stream(self, stream, stream_name: str, pid: int) -> None:
        for line in iter(stream.readline, ""):
            event = decode_output_line(line, stream=stream_name)
            if event is not None:
                event.process_pid = pid
                self._emit(event)

    def _wait_for_exit(self, pid: int) -> None:
        process = self._process
        if process is None or process.pid != pid:
            return
        return_code = process.wait()
        self._close_streams(process)
        self._emit(
            AppEvent(
                type="status",
                text=f"Hosted app exited with code {return_code}.",
                process_pid=pid,
                stream="system",
                raw={"return_code": return_code},
            )
        )

    @staticmethod
    def _close_streams(process: subprocess.Popen[str]) -> None:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is None:
                continue
            try:
                stream.close()
            except OSError:
                continue
