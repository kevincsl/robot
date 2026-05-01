"""Audit the local law catalog against the current expected exam scope."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.law_catalog import LAW_CATALOG, LAW_CATALOG_BY_NAME, expected_law_names
from app.models import Law, QuestionLawArticleRef

REVISION_DATE_RE = re.compile(
    r"\u4fee\u6b63\u65e5\u671f[:\uff1a]\s*\u6c11\u570b\s*(\d+)\s*\u5e74\s*(\d+)\s*\u6708\s*(\d+)\s*\u65e5"
)


def _official_revision_date(url: str) -> str:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        html = client.get(url).text
    text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
    match = REVISION_DATE_RE.search(text)
    if not match:
        return "unknown"
    roc_year, month, day = match.groups()
    return f"ROC {roc_year}-{int(month):02d}-{int(day):02d}"


def main() -> None:
    db = SessionLocal()
    try:
        laws = db.query(Law).order_by(Law.code).all()
        actual_names = {law.name for law in laws}
        expected = expected_law_names()

        print(f"catalog_laws={len(LAW_CATALOG)}")
        print(f"expected_laws={len(expected)}")
        print(f"loaded_laws={len(laws)}")
        print(f"missing_expected={sorted(expected - actual_names)}")
        print(f"extra_loaded={sorted(actual_names - expected)}")
        broken_refs = (
            db.query(QuestionLawArticleRef)
            .filter(QuestionLawArticleRef.law_article_id.is_(None))
            .count()
        )
        print(f"unbound_question_article_refs={broken_refs}")
        print("---")

        for law in laws:
            revision = _official_revision_date(str(law.source_url or ""))
            scope = LAW_CATALOG_BY_NAME.get(law.name).scope if law.name in LAW_CATALOG_BY_NAME else "unknown"
            print(
                "\t".join(
                    [
                        law.code,
                        law.name,
                        scope,
                        revision,
                        str(law.fetched_at or ""),
                        str(law.source_url or ""),
                    ]
                )
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
