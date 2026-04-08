from __future__ import annotations

import sys

from teleapp.app import TeleApp
from teleapp.scaffold import create_project


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "init":
        target = create_project(sys.argv[2])
        print(f"Created teleapp project at {target}")
        return
    app = TeleApp.from_cli()
    print(
        "[teleapp] cli launch "
        f"app={app.config.app_path or '-'} "
        f"hot_reload={'on' if app.config.hot_reload else 'off'} "
        f"python={app.config.python_executable}",
        file=sys.stderr,
        flush=True,
    )
    app.run_polling()
