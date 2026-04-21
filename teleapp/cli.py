from __future__ import annotations

import sys

from teleapp.app import TeleApp
from teleapp.config import build_parser, load_config
from teleapp.scaffold import create_project
from teleapp.singleton import SingletonInstanceError, acquire_singleton


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "init":
        target = create_project(sys.argv[2])
        print(f"Created teleapp project at {target}")
        return

    parser = build_parser()
    args = parser.parse_args()
    config = load_config(args)
    try:
        lock_path = acquire_singleton(config.app_path)
    except SingletonInstanceError as exc:
        print(f"[teleapp] singleton guard blocked launch: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc

    app = TeleApp.from_config(config)
    print(
        "[teleapp] cli launch "
        f"app={app.config.app_path or '-'} "
        f"hot_reload={'on' if app.config.hot_reload else 'off'} "
        f"python={app.config.python_executable} "
        f"lock={lock_path}",
        file=sys.stderr,
        flush=True,
    )
    app.run_polling()
