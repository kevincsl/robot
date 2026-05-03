#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def run_steps(
    steps: list[dict],
    out_dir: Path,
    headless: bool,
    timeout_ms: int,
    ignore_https_errors: bool,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    screenshots: list[Path] = []
    shot_index = 1

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(ignore_https_errors=ignore_https_errors)
        page = context.new_page()
        page.set_default_timeout(timeout_ms)

        for step in steps:
            action = str(step.get("action", "")).strip().lower()
            if action == "goto":
                page.goto(step["url"], wait_until="domcontentloaded")
            elif action == "click":
                page.locator(step["selector"]).first.click()
            elif action == "type":
                locator = page.locator(step["selector"]).first
                if step.get("clear", True):
                    locator.fill("")
                locator.type(step.get("text", ""))
            elif action == "press":
                page.keyboard.press(step.get("key", "Enter"))
            elif action == "select":
                page.locator(step["selector"]).first.select_option(step.get("value", ""))
            elif action == "wait":
                page.wait_for_timeout(int(step.get("ms", 1000)))
            elif action == "screenshot":
                name = step.get("name") or f"step-{shot_index:02d}.png"
                shot_index += 1
                path = out_dir / name
                page.screenshot(path=str(path), full_page=bool(step.get("full_page", True)))
                screenshots.append(path)
            else:
                raise ValueError(f"Unsupported action: {action}")

        context.close()
        browser.close()
    return screenshots


def main() -> None:
    parser = argparse.ArgumentParser(description="Run headless Chrome steps and save screenshots")
    parser.add_argument("--steps", required=True, help="Path to JSON array of steps")
    parser.add_argument("--out-dir", required=True, help="Screenshot output directory")
    parser.add_argument("--headed", action="store_true", help="Run with visible browser window")
    parser.add_argument("--timeout-ms", type=int, default=15000, help="Default timeout per action")
    parser.add_argument(
        "--ignore-https-errors",
        action="store_true",
        help="Ignore TLS/HTTPS certificate errors (use only for testing/self-signed certs).",
    )
    args = parser.parse_args()

    steps_path = Path(args.steps).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    steps = json.loads(steps_path.read_text(encoding="utf-8"))
    if not isinstance(steps, list):
        raise SystemExit("steps JSON must be a list")

    shots = run_steps(
        steps,
        out_dir,
        headless=not args.headed,
        timeout_ms=args.timeout_ms,
        ignore_https_errors=bool(args.ignore_https_errors),
    )
    if not shots:
        print("no screenshots generated")
        return
    for shot in shots:
        print(str(shot))


if __name__ == "__main__":
    main()
