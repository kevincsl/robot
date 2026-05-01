"""Admin-only helpers for law refresh and audits."""
from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.law_catalog import LAW_CATALOG, LAW_CATALOG_BY_NAME, expected_law_names
from app.models import Law, Question, QuestionLawArticleRef
from app.services.law_links import relink_question_law_article_ids
from app.services.law_relink_runs import latest_relink_run, run_relink, run_to_view, start_snapshot_run
from scripts.fetch_laws import fetch_law

REVISION_DATE_RE = re.compile(
    r"\u4fee\u6b63\u65e5\u671f[:\uff1a]\s*\u6c11\u570b\s*(\d+)\s*\u5e74\s*(\d+)\s*\u6708\s*(\d+)\s*\u65e5"
)


def refresh_all_laws(db: Session) -> dict[str, int]:
    snapshot = start_snapshot_run(db, trigger_type="admin_refresh")
    for entry in LAW_CATALOG:
        fetch_law(entry.code, dry_run=False, from_cache=False)
    run = run_relink(
        db,
        snapshot_run_id=snapshot.id,
        scope="all",
        idempotency_key=f"admin-refresh-{snapshot.id}",
        source="admin_refresh",
    )
    return {
        "catalog_laws": len(LAW_CATALOG),
        "relink_run_id": run.id,
    }


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


def trigger_relink(db: Session, *, trigger_type: str = "admin_manual") -> dict[str, int]:
    snapshot = start_snapshot_run(db, trigger_type=trigger_type)
    run = run_relink(
        db,
        snapshot_run_id=snapshot.id,
        scope="all",
        idempotency_key=f"{trigger_type}-{snapshot.id}",
        source=trigger_type,
    )
    return {"run_id": run.id}


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
    latest_run = run_to_view(latest_relink_run(db))
    high_risk_questions: list[dict] = []
    if latest_run is not None:
        stats = latest_run.get("stats") or {}
        for question_id in stats.get("high_risk_question_ids", [])[:10]:
            question = db.get(Question, int(question_id))
            if question is None:
                continue
            high_risk_questions.append(
                {
                    "id": question.id,
                    "body": question.body,
                    "source": question.source,
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
        "latest_relink_run": latest_run,
        "rows": rows,
    }
