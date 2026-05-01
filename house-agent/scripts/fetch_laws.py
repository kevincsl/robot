"""Fetch law articles from the Ministry of Justice law database.

Run:
    python scripts/fetch_laws.py
    python scripts/fetch_laws.py --code B0000001
    python scripts/fetch_laws.py --from-cache
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal, init_db
from app.law_catalog import LAW_CATALOG, LAW_CATALOG_BY_CODE
from app.models import Law, LawArticle
from app.services.law_links import relink_question_law_article_ids

RAW_DIR = ROOT / "data" / "raw" / "laws"
RAW_DIR.mkdir(parents=True, exist_ok=True)


def _parse_and_save(pcode: str, raw: bytes) -> None:
    entry = LAW_CATALOG_BY_CODE.get(pcode)
    name = entry.name if entry is not None else pcode
    url = entry.source_url if entry is not None else f"https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={pcode}"
    soup = BeautifulSoup(raw, "html.parser")
    rows = soup.select("div.row")
    articles: list[tuple[str, str]] = []
    for row in rows:
        no_el = row.select_one(".col-no a")
        body_el = row.select_one(".col-data")
        if not no_el or not body_el:
            continue
        article_no = no_el.get_text(strip=True)
        body_text = body_el.get_text("\n", strip=True)
        articles.append((article_no, body_text))

    db = SessionLocal()
    try:
        law = db.query(Law).filter_by(code=pcode).first()
        if law is None:
            law = Law(code=pcode, name=name, source_url=url, fetched_at=datetime.utcnow())
            db.add(law)
            db.flush()
        else:
            law.name = name
            law.fetched_at = datetime.utcnow()
            law.source_url = url
            law.articles.clear()
            db.flush()
        for art_no, body in articles:
            db.add(LawArticle(law_id=law.id, article_no=art_no, body=body))
        db.commit()
        print(f"[saved] {name}: {len(articles)} articles")
    finally:
        db.close()


def fetch_law(pcode: str, dry_run: bool = False, from_cache: bool = False) -> None:
    entry = LAW_CATALOG_BY_CODE.get(pcode)
    name = entry.name if entry is not None else pcode
    url = entry.source_url if entry is not None else f"https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={pcode}"
    cache_path = RAW_DIR / f"{pcode}.html"

    if from_cache:
        if cache_path.exists():
            print(f"[cache] {name} ({pcode})")
            _parse_and_save(pcode, cache_path.read_bytes())
        else:
            print(f"[skip] {name} ({pcode}) no cached file")
        return

    print(f"[fetch] {name} ({pcode}) -> {url}")
    if dry_run:
        return

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        raw = response.content
        cache_path.write_bytes(raw)
    _parse_and_save(pcode, raw)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", help="single law pcode to fetch (default: full catalog)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--from-cache", action="store_true", help="import from cached HTMLs")
    args = parser.parse_args()

    init_db()
    codes = [args.code] if args.code else [entry.code for entry in LAW_CATALOG]
    for code in codes:
        try:
            fetch_law(code, dry_run=args.dry_run, from_cache=args.from_cache)
        except Exception as exc:
            print(f"[error] {code}: {exc}", file=sys.stderr)
    if not args.dry_run:
        db = SessionLocal()
        try:
            stats = relink_question_law_article_ids(db)
            print(f"[relink] total={stats['total_refs']} updated={stats['updated']} cleared={stats['cleared']}")
        finally:
            db.close()


if __name__ == "__main__":
    main()
