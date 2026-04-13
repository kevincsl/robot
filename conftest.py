from __future__ import annotations

import os

import pytest


def _clear_teleapp_runtime_env() -> None:
    # Keep repo-local .env runtime flags from leaking into tests.
    for key in (
        "TELEAPP_HOT_RELOAD",
        "TELEAPP_AUTO_RESTART_ON_CRASH",
        "TELEAPP_RELOAD_QUIET_SECONDS",
        "TELEAPP_RELOAD_POLL_SECONDS",
        "TELEAPP_RESTART_BACKOFF_SECONDS",
    ):
        os.environ.pop(key, None)


_clear_teleapp_runtime_env()


@pytest.fixture(autouse=True)
def _isolate_teleapp_runtime_env():
    _clear_teleapp_runtime_env()
    yield
    _clear_teleapp_runtime_env()
