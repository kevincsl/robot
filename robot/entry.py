from __future__ import annotations

import argparse
import os
import sys


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="robot",
        description="Robot launch entrypoint",
    )
    parser.add_argument(
        "--standalone",
        action="store_true",
        help="Run direct Telegram polling mode (dev only).",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if not args.standalone:
        parser.print_usage(sys.stderr)
        sys.stderr.write(
            "Use teleapp supervisor mode instead:\n"
            "- Foreground: robotctl run [config]\n"
            "- Background: robotctl start <config|all>\n"
            "- Direct: teleapp robot.py\n"
            "Pass --standalone only for explicit dev/debug direct polling.\n"
        )
        raise SystemExit(2)

    os.environ["ROBOT_ALLOW_DIRECT_POLLING"] = "1"
    from robot.app import main as app_main

    app_main()


if __name__ == "__main__":
    main()
