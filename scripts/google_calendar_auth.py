from __future__ import annotations

import argparse
import sys

from robot.config import load_settings
from robot.google_calendar import (
    GoogleCalendarError,
    authorize_google_calendar,
    google_calendar_status_text,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Authorize Google Calendar access for robot.")
    parser.add_argument("--status-only", action="store_true", help="Only print current Google Calendar status.")
    parser.add_argument("--no-browser", action="store_true", help="Use console auth flow instead of opening browser.")
    args = parser.parse_args()

    settings = load_settings()
    if args.status_only:
        print(google_calendar_status_text(settings))
        return 0

    try:
        message = authorize_google_calendar(settings, open_browser=not args.no_browser)
    except GoogleCalendarError as exc:
        print(f"Authorization failed: {exc}", file=sys.stderr)
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
