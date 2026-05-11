#!/usr/bin/env python3
"""robotctl — thin CLI wrapper over robot.control."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    from robot.control import create_parser, main as control_main

    parser = create_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help(sys.stderr)
        return 1

    return control_main()


if __name__ == "__main__":
    raise SystemExit(main())
