"""Admin-only helpers for law refresh and audits."""
from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.law_catalog import LAW_CATALOG, LAW_CATALOG_BY_NAME, expected_law_names
from app.models import Law, QuestionLawArticleRef
from app.services.law_links import relink_question_law_article_ids
from scripts.fetch_laws import fetch_law

REVISION_DATE_RE = re.compile(
    r"\u4fee\u6b63\u65e5\u671f[:\uff1a]\s*\u6c11\u570b\s*(\d+)\s*\u5e74\s*(\d+)\s*\u6708\s*(\d+)\s*\u65e5"
)


def refresh_all_laws() -> dict[str, int]:
    for entry in LAW_CATALOG:
        fetch_law(entry.code, dry_run=False, from_cache=False)
    return {"catalog_laws": len(LAW_CATALOG)}


def _official_revision_date(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return "unknown"
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        html = client.get(url).text
    text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
    match = REVISION_DATE_RE.search(text)
    if not match:
        return "unknown"
    roc_year, month, day = match.groups()
    return f"ROC {roc_year}-{int(month):02d}-{int(day):02d}"


def audit_laws(db: Session) -> dict:
    laws = db.query(Law).order_by(Law.code).all()
    actual_names = {law.name for law in laws}
    expected = expected_law_names()
    relink_stats = relink_question_law_article_ids(db)
    rows = []
    for law in laws:
        meta = LAW_CATALOG_BY_NAME.get(law.name)
        rows.append(
            {
                "code": law.code,
                "name": law.name,
                "scope": meta.scope if meta is not None else "unknown",
                "official_revision": _official_revision_date(str(law.source_url or "")),
                "fetched_at": law.fetched_at,
                "source_url": law.source_url,
                "article_count": len(law.articles),
            }
        )
    return {
        "catalog_laws": len(LAW_CATALOG),
        "expected_laws": len(expected),
        "loaded_laws": len(laws),
        "missing_expected": sorted(expected - actual_names),
        "extra_loaded": sorted(actual_names - expected),
        "unbound_question_article_refs": db.query(QuestionLawArticleRef).filter(QuestionLawArticleRef.law_article_id.is_(None)).count(),
        "relink_stats": relink_stats,
        "rows": rows,
    }
