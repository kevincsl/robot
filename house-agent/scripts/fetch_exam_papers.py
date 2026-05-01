"""Fetch MOEX exam-paper files for broker exam papers.

This collector focuses on raw coverage first:
- discover broker exam codes by year
- query each exam result page
- extract only broker-category rows
- download original question/answer PDFs

Run:
    python scripts/fetch_exam_papers.py
    python scripts/fetch_exam_papers.py --roc-year-from 91 --roc-year-to 115
    python scripts/fetch_exam_papers.py --year-from 2002 --year-to 2026
    python scripts/fetch_exam_papers.py --metadata-only
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from urllib3.exceptions import InsecureRequestWarning

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE = "https://wwwq.moex.gov.tw/exam/wFrmExamQandASearch.aspx"
FILE_BASE = "https://wwwq.moex.gov.tw/exam/"
RAW_DIR = ROOT / "data" / "raw" / "exam_papers" / "moex"

BROKER_EXAM_NAME_KEYWORD = "\u666e\u901a\u8003\u8a66\u4e0d\u52d5\u7522\u7d93\u7d00\u4eba"
BROKER_LEGACY_EXAM_NAME_KEYWORD = "\u4e0d\u52d5\u7522\u7d93\u7d00\u4eba"
BROKER_CATEGORY_KEYWORD = "\u4e0d\u52d5\u7522\u7d93\u7d00\u4eba"
ROC_YEAR_OFFSET = 1911

warnings.simplefilter("ignore", InsecureRequestWarning)


@dataclass
class ExamTarget:
    year: int
    exam_code: str
    exam_name: str


def normalize_space(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def canonical_year(value: int) -> int:
    """Accept ROC years (e.g. 91) and Gregorian years (e.g. 2002)."""
    return value + ROC_YEAR_OFFSET if value < ROC_YEAR_OFFSET else value


def to_roc_year(gregorian_year: int) -> int:
    return gregorian_year - ROC_YEAR_OFFSET


def is_target_exam_name(exam_name: str) -> bool:
    return (
        BROKER_EXAM_NAME_KEYWORD in exam_name
        or BROKER_LEGACY_EXAM_NAME_KEYWORD in exam_name
    )


def is_target_category(category_name: str) -> bool:
    return BROKER_CATEGORY_KEYWORD in category_name


def form_data(soup: BeautifulSoup) -> dict[str, str]:
    data: dict[str, str] = {}
    for tag in soup.select("input[name], select[name], textarea[name]"):
        name = tag.get("name")
        if not name:
            continue
        if tag.name == "select":
            selected = tag.find("option", selected=True)
            data[name] = selected.get("value", "") if selected else ""
            continue
        input_type = (tag.get("type") or "").lower()
        if input_type in {"checkbox", "radio"} and not tag.has_attr("checked"):
            continue
        data[name] = tag.get("value", "")
    return data


def discover_targets(year_from: int, year_to: int) -> list[ExamTarget]:
    session = requests.Session()
    response = session.get(BASE, verify=False, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    available_years = [
        int(option.get("value", "0"))
        for option in soup.select("#ctl00_holderContent_wUctlExamYearStart_ddlExamYear option")
        if option.get("value")
    ]
    wanted_years = [year for year in available_years if year_from <= year <= year_to]

    targets: list[ExamTarget] = []
    for year in wanted_years:
        payload = form_data(soup)
        payload["ctl00$holderContent$wUctlExamYearStart$ddlExamYear"] = str(year)
        payload["ctl00$holderContent$wUctlExamYearEnd$ddlExamYear"] = str(year)
        payload["ctl00$holderContent$btnYear"] = "\u4f9d\u8003\u8a66\u5e74\u5ea6\u8a2d\u5b9a\u8003\u8a66\u7c21\u7a31"
        response = session.post(BASE, data=payload, verify=False, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        for option in soup.select("#ctl00_holderContent_ddlExamCode option"):
            exam_code = option.get("value", "").strip()
            exam_name = normalize_space(option.get_text(" ", strip=True))
            if not exam_code:
                continue
            if is_target_exam_name(exam_name):
                targets.append(ExamTarget(year=year, exam_code=exam_code, exam_name=exam_name))

    return targets


def fetch_exam_payload(page, year: int, exam_code: str) -> dict[str, Any]:
    page.goto(BASE, wait_until="networkidle")
    page.locator("#ctl00_holderContent_ibtnFull").click()
    page.wait_for_load_state("networkidle")

    page.select_option("#ctl00_holderContent_wUctlExamYearStart_ddlExamYear", str(year))
    page.select_option("#ctl00_holderContent_wUctlExamYearEnd_ddlExamYear", str(year))
    page.evaluate("document.getElementById('ctl00_holderContent_btnYear').click()")
    page.wait_for_load_state("networkidle")
    page.wait_for_function(
        "document.querySelectorAll('#ctl00_holderContent_ddlExamCode option').length > 1"
    )

    page.select_option("#ctl00_holderContent_ddlExamCode", exam_code)
    page.locator("#ctl00_holderContent_btnQuery").click()
    page.wait_for_load_state("networkidle")

    return page.evaluate(
        """() => {
            const normalize = (s) => (s || '').replace(/\\s+/g, ' ').trim();
            const uniqueLinks = (td) => {
                const seen = new Set();
                const out = [];
                for (const a of td.querySelectorAll('a[href]')) {
                    const href = a.getAttribute('href');
                    if (!href || seen.has(href)) continue;
                    seen.add(href);
                    out.push({ text: normalize(a.textContent), href });
                }
                return out;
            };
            const textWithoutLinks = (td) => {
                const clone = td.cloneNode(true);
                clone.querySelectorAll('a').forEach((a) => a.remove());
                return normalize(clone.textContent);
            };
            const rows = [];
            for (const tr of document.querySelectorAll('#ctl00_holderContent_tblExamQand tr')) {
                const tds = [...tr.querySelectorAll(':scope > td')];
                if (tds.length !== 1) continue;
                const td = tds[0];
                rows.push({
                    text: normalize(td.textContent),
                    label: textWithoutLinks(td),
                    links: uniqueLinks(td),
                });
            }
            return {
                html: document.documentElement.outerHTML,
                stats: normalize(document.querySelector('#ctl00_holderContent_lblStatistics')?.textContent),
                rows,
            };
        }"""
    )


def filter_relevant_rows(payload: dict[str, Any]) -> dict[str, Any]:
    exam_title = ""
    overall_links: list[dict[str, str]] = []
    current_category = ""
    items: list[dict[str, Any]] = []

    for row in payload.get("rows", []):
        text = normalize_space(row.get("text"))
        label = normalize_space(row.get("label"))
        links = row.get("links", [])

        if not links:
            if not exam_title:
                exam_title = text
            else:
                current_category = text
            continue

        if not exam_title:
            exam_title = label or text
            overall_links = links
            continue

        if is_target_category(current_category):
            items.append(
                {
                    "category": current_category,
                    "subject": label or text,
                    "links": links,
                }
            )

    return {
        "exam_title": exam_title,
        "stats": payload.get("stats", ""),
        "overall_links": overall_links,
        "items": items,
    }


def download_file(
    session: requests.Session,
    href: str,
    destination: Path,
) -> None:
    response = session.get(urljoin(FILE_BASE, href), verify=False, timeout=60)
    response.raise_for_status()
    destination.write_bytes(response.content)


def save_exam_bundle(
    session: requests.Session,
    target: ExamTarget,
    parsed: dict[str, Any],
    html: str,
    metadata_only: bool,
) -> dict[str, Any]:
    exam_dir = RAW_DIR / f"{target.year}_{target.exam_code}"
    exam_dir.mkdir(parents=True, exist_ok=True)

    html_path = exam_dir / "result.html"
    html_path.write_text(html, encoding="utf-8")

    manifest: dict[str, Any] = {
        "year": target.year,
        "exam_code": target.exam_code,
        "exam_name": target.exam_name,
        "exam_title": parsed["exam_title"],
        "stats": parsed["stats"],
        "overall_links": parsed["overall_links"],
        "items": [],
    }

    if parsed["overall_links"] and not metadata_only:
        for index, link in enumerate(parsed["overall_links"], start=1):
            suffix = "pdf"
            out = exam_dir / f"overall_{index:02d}.pdf"
            download_file(session, link["href"], out)

    for cat_index, item in enumerate(parsed["items"], start=1):
        out_item = {
            "category_index": cat_index,
            "category": item["category"],
            "subject": item["subject"],
            "files": [],
        }
        for file_index, link in enumerate(item["links"], start=1):
            kind = link["text"] or f"file_{file_index}"
            file_record = {
                "kind": kind,
                "href": link["href"],
            }
            if not metadata_only:
                out = exam_dir / f"cat_{cat_index:03d}_file_{file_index:02d}.pdf"
                download_file(session, link["href"], out)
                file_record["path"] = str(out.relative_to(ROOT))
            out_item["files"].append(file_record)
        manifest["items"].append(out_item)

    manifest_path = exam_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def run(year_from: int, year_to: int, metadata_only: bool, max_codes: int | None) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    start_year = canonical_year(year_from)
    end_year = canonical_year(year_to)

    print(
        "[discover] "
        f"years={start_year}-{end_year} "
        f"(ROC {to_roc_year(start_year)}-{to_roc_year(end_year)}) "
        f"exam='{BROKER_EXAM_NAME_KEYWORD}' "
        f"category='{BROKER_CATEGORY_KEYWORD}'"
    )
    targets = discover_targets(year_from=start_year, year_to=end_year)
    if max_codes is not None:
        targets = targets[:max_codes]
    print(f"[discover] matched exam codes={len(targets)}")

    discovery_path = RAW_DIR / "discovery.json"
    discovery_path.write_text(
        json.dumps([target.__dict__ for target in targets], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    session = requests.Session()
    collected: list[dict[str, Any]] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for index, target in enumerate(targets, start=1):
                print(f"[query {index}/{len(targets)}] {target.year} {target.exam_code}")
                page = browser.new_page(ignore_https_errors=True)
                try:
                    payload = fetch_exam_payload(page, target.year, target.exam_code)
                    parsed = filter_relevant_rows(payload)
                    manifest = save_exam_bundle(
                        session=session,
                        target=target,
                        parsed=parsed,
                        html=payload["html"],
                        metadata_only=metadata_only,
                    )
                    collected.append(manifest)
                    print(
                        f"[saved] items={len(manifest['items'])} "
                        f"dir={RAW_DIR / f'{target.year}_{target.exam_code}'}"
                    )
                except PlaywrightTimeoutError as exc:
                    print(f"[warn] timeout for {target.exam_code}: {exc}")
                finally:
                    page.close()
                time.sleep(0.2)
        finally:
            browser.close()

    summary = {
        "year_from": start_year,
        "year_to": end_year,
        "roc_year_from": to_roc_year(start_year),
        "roc_year_to": to_roc_year(end_year),
        "exam_name_keyword": BROKER_EXAM_NAME_KEYWORD,
        "category_keyword": BROKER_CATEGORY_KEYWORD,
        "metadata_only": metadata_only,
        "exam_code_count": len(targets),
        "saved_exam_count": len(collected),
        "total_subject_rows": sum(len(item["items"]) for item in collected),
    }
    (RAW_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("[summary]", json.dumps(summary, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year-from", type=int, default=91)
    parser.add_argument("--year-to", type=int, default=115)
    parser.add_argument("--roc-year-from", type=int, default=None)
    parser.add_argument("--roc-year-to", type=int, default=None)
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--max-codes", type=int, default=None)
    args = parser.parse_args()
    year_from = args.roc_year_from if args.roc_year_from is not None else args.year_from
    year_to = args.roc_year_to if args.roc_year_to is not None else args.year_to
    run(
        year_from=year_from,
        year_to=year_to,
        metadata_only=args.metadata_only,
        max_codes=args.max_codes,
    )


if __name__ == "__main__":
    main()
