"""Versioned law relink runs and diff tracking."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.law_catalog import LAW_CATALOG
from app.models import (
    LawSnapshotRun,
    Question,
    QuestionLawArticleRef,
    QuestionLawRelinkDiff,
    QuestionLawRelinkResult,
    QuestionLawRelinkRun,
)
from app.services.law_links import backfill_question_law_refs, relink_question_law_article_ids


def _catalog_hash() -> str:
    payload = [f"{entry.code}:{entry.name}:{entry.scope}" for entry in LAW_CATALOG]
    return hashlib.sha256("|".join(payload).encode("utf-8")).hexdigest()


def start_snapshot_run(db: Session, *, trigger_type: str, note: str | None = None) -> LawSnapshotRun:
    run = LawSnapshotRun(
        trigger_type=trigger_type,
        catalog_hash=_catalog_hash(),
        status="running",
        note=note,
        started_at=datetime.utcnow(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _normalized_ref_strings(question: Question) -> list[str]:
    refs: list[str] = []
    for ref in sorted(question.law_article_refs, key=lambda item: (item.law_id, item.article_no, item.id)):
        refs.append(f"{ref.law_id}:{ref.article_no}")
    return refs


def _raw_ref_strings(question: Question) -> list[str]:
    raw = question.law_refs or []
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _classify_flip_type(old_refs: list[str], new_refs: list[str]) -> str:
    if old_refs and not new_refs:
        return "correct_to_incorrect"
    if (not old_refs) and new_refs:
        return "incorrect_to_correct"
    return "link_only_changed"


def diff_question_refs(old_refs: list[str], new_refs: list[str]) -> list[dict[str, str]]:
    old_set = set(old_refs)
    new_set = set(new_refs)
    events: list[dict[str, str]] = []
    for old_ref in sorted(old_set - new_set):
        events.append({"diff_type": "removed", "old_ref": old_ref, "new_ref": ""})
    for new_ref in sorted(new_set - old_set):
        events.append({"diff_type": "added", "old_ref": "", "new_ref": new_ref})
    return events


def run_relink(
    db: Session,
    *,
    snapshot_run_id: int | None,
    scope: str,
    idempotency_key: str,
    source: str = "relink_run",
) -> QuestionLawRelinkRun:
    existing = (
        db.query(QuestionLawRelinkRun)
        .filter(QuestionLawRelinkRun.idempotency_key == idempotency_key)
        .first()
    )
    if existing is not None and existing.status == "succeeded":
        return existing

    run = QuestionLawRelinkRun(
        snapshot_run_id=snapshot_run_id,
        scope=scope,
        idempotency_key=idempotency_key,
        status="running",
        started_at=datetime.utcnow(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    questions = list(db.query(Question).all())
    before = {question.id: _normalized_ref_strings(question) for question in questions}

    backfill_stats = backfill_question_law_refs(db, questions=questions, source=source, confidence=0.9)
    relink_stats = relink_question_law_article_ids(db)

    changed = 0
    diffs = 0
    flip_counts = {
        "correct_to_incorrect": 0,
        "incorrect_to_correct": 0,
        "link_only_changed": 0,
    }
    high_risk_question_ids: list[int] = []

    for question in questions:
        old_refs = before.get(question.id, [])
        new_refs = _normalized_ref_strings(question)
        events = diff_question_refs(old_refs, new_refs)
        has_change = bool(events)
        flip_type = _classify_flip_type(old_refs, new_refs) if has_change else "link_only_changed"
        needs_review = flip_type == "correct_to_incorrect"
        db.add(
            QuestionLawRelinkResult(
                run_id=run.id,
                question_id=question.id,
                old_refs=old_refs,
                new_refs=new_refs,
                changed=has_change,
                needs_review=needs_review,
            )
        )
        if has_change:
            changed += 1
            flip_counts[flip_type] += 1
            if flip_type == "correct_to_incorrect":
                high_risk_question_ids.append(question.id)
        for event in events:
            diffs += 1
            db.add(
                QuestionLawRelinkDiff(
                    run_id=run.id,
                    question_id=question.id,
                    diff_type=event["diff_type"],
                    flip_type=flip_type,
                    old_ref=event["old_ref"] or None,
                    new_ref=event["new_ref"] or None,
                    evidence={
                        "raw_refs": _raw_ref_strings(question),
                        "old_refs": old_refs,
                        "new_refs": new_refs,
                        "event": event,
                    },
                )
            )

    run.status = "succeeded"
    run.finished_at = datetime.utcnow()
    run.stats_json = {
        "questions": len(questions),
        "changed_questions": changed,
        "diff_events": diffs,
        "flip_counts": flip_counts,
        "high_risk_question_ids": high_risk_question_ids,
        "backfill": backfill_stats,
        "relink": relink_stats,
    }
    db.commit()

    if snapshot_run_id is not None:
        snapshot = db.get(LawSnapshotRun, snapshot_run_id)
        if snapshot is not None:
            snapshot.status = "succeeded"
            snapshot.finished_at = datetime.utcnow()
            db.commit()

    return run


def latest_relink_run(db: Session) -> QuestionLawRelinkRun | None:
    return (
        db.query(QuestionLawRelinkRun)
        .order_by(QuestionLawRelinkRun.started_at.desc(), QuestionLawRelinkRun.id.desc())
        .first()
    )


def run_to_view(run: QuestionLawRelinkRun | None) -> dict | None:
    if run is None:
        return None
    stats = run.stats_json or {}
    return {
        "id": run.id,
        "status": run.status,
        "scope": run.scope,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "stats": stats,
        "stats_json": json.dumps(stats, ensure_ascii=False),
    }
