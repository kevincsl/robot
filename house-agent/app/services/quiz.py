"""Quiz logic: random selection with error-weighted SRS, stats."""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Integer, case, func, select
from sqlalchemy.orm import Session

from app.models import Attempt, Chapter, Question, QuestionType, Subject
from app.services.auth import get_or_create_default_user
from app.services.law_links import question_importance_details, question_importance_scores


def _attempt_user_filter(db: Session, user_id: int | None):
    if user_id is None:
        default_user = get_or_create_default_user(db)
        return ((Attempt.user_id == default_user.id) | (Attempt.user_id.is_(None)))
    return Attempt.user_id == user_id


def _question_stats(db: Session, question_ids: list[int], *, user_id: int | None = None) -> dict[int, dict[str, int]]:
    if not question_ids:
        return {}
    wrong_expr = func.sum(case((Attempt.correct == False, 1), else_=0))  # noqa: E712
    rows = db.execute(
        select(
            Attempt.question_id,
            func.count(Attempt.id),
            wrong_expr,
        ).where(
            Attempt.question_id.in_(question_ids),
            _attempt_user_filter(db, user_id),
        ).group_by(Attempt.question_id)
    ).all()
    out: dict[int, dict[str, int]] = {qid: {"attempts": 0, "wrong": 0} for qid in question_ids}
    for qid, total, wrong in rows:
        out[qid] = {"attempts": int(total or 0), "wrong": int(wrong or 0)}
    return out


def pick_choice_question(
    db: Session,
    subject_id: int | None = None,
    chapter_id: int | None = None,
    user_id: int | None = None,
) -> Question | None:
    """Pick next choice question — favor unseen and high-error questions."""
    stmt = select(Question).where(Question.type == QuestionType.CHOICE)
    if subject_id:
        stmt = stmt.where(Question.subject_id == subject_id)
    if chapter_id:
        stmt = stmt.where(Question.chapter_id == chapter_id)
    questions = list(db.execute(stmt).scalars())
    if not questions:
        return None

    qids = [q.id for q in questions]
    stats = _question_stats(db, qids, user_id=user_id)
    importance_scores = question_importance_scores(db, qids)

    weights: list[float] = []
    for q in questions:
        s = stats.get(q.id, {"attempts": 0, "wrong": 0})
        if s["attempts"] == 0:
            w = 5.0
        else:
            wrong_rate = s["wrong"] / max(s["attempts"], 1)
            w = 1.0 + 4.0 * wrong_rate
        w *= 1.0 + (importance_scores.get(q.id, 0.0) / 100.0)
        weights.append(w)

    return random.choices(questions, weights=weights, k=1)[0]


def record_attempt(
    db: Session,
    question_id: int,
    user_answer: str | None,
    correct: bool,
    user_id: int | None = None,
    score: float | None = None,
    feedback: str | None = None,
    time_spent_ms: int | None = None,
) -> Attempt:
    if user_id is None:
        user_id = get_or_create_default_user(db).id
    attempt = Attempt(
        user_id=user_id,
        question_id=question_id,
        user_answer=user_answer,
        correct=correct,
        score=score,
        feedback=feedback,
        time_spent_ms=time_spent_ms,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def coverage_by_subject(db: Session, *, user_id: int | None = None) -> list[dict[str, Any]]:
    """Per-subject coverage: how many questions have at least one attempt."""
    subjects = list(db.execute(select(Subject)).scalars())
    result: list[dict[str, Any]] = []
    for subj in subjects:
        total = db.execute(
            select(func.count(Question.id)).where(
                Question.subject_id == subj.id,
                Question.type == QuestionType.CHOICE,
            )
        ).scalar_one()
        seen = db.execute(
            select(func.count(func.distinct(Attempt.question_id)))
            .join(Question, Question.id == Attempt.question_id)
            .where(
                Question.subject_id == subj.id,
                Question.type == QuestionType.CHOICE,
                _attempt_user_filter(db, user_id),
            )
        ).scalar_one()
        result.append(
            {
                "subject": subj.name,
                "subject_id": subj.id,
                "total": total or 0,
                "seen": seen or 0,
                "coverage": (seen / total) if total else 0.0,
            }
        )
    return result


def wrong_questions(db: Session, limit: int = 50, *, user_id: int | None = None) -> list[dict]:
    """Return questions with highest wrong-attempt counts, for the review page."""
    from sqlalchemy import desc
    wrong_expr = func.sum(case((Attempt.correct == False, 1), else_=0))  # noqa: E712
    rows = db.execute(
        select(
            Attempt.question_id,
            func.count(Attempt.id).label("total"),
            wrong_expr.label("wrong"),
        )
        .where(_attempt_user_filter(db, user_id))
        .group_by(Attempt.question_id)
        .having(wrong_expr > 0)
        .order_by(desc(wrong_expr))
        .limit(limit)
    ).all()

    out = []
    question_ids = [qid for qid, _total, _wrong in rows]
    importance = question_importance_details(db, question_ids)
    for qid, total, wrong in rows:
        q = db.get(Question, qid)
        if q and q.type == QuestionType.CHOICE:
            meta = importance.get(q.id, {"score": 0.0, "weight": 1.0, "level": "待累積"})
            out.append({
                "question": q,
                "total": int(total),
                "wrong": int(wrong),
                "wrong_rate": round(wrong / total * 100, 1),
                "importance_score": float(meta["score"]),
                "importance_weight": float(meta["weight"]),
                "importance_level": str(meta["level"]),
                "priority_score": round((wrong / total) * float(meta["weight"]), 3),
            })
    out.sort(key=lambda item: (item["priority_score"], item["wrong"], item["total"]), reverse=True)
    return out[:limit]


def accuracy_buckets(db: Session, days: int, *, user_id: int | None = None) -> dict[str, float]:
    """Aggregate accuracy for last N days, bucketed by week or day."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = db.execute(
        select(Attempt.created_at, Attempt.correct).where(Attempt.created_at >= cutoff, _attempt_user_filter(db, user_id))
    ).all()
    if not rows:
        return {}
    bucket: dict[str, list[bool]] = defaultdict(list)
    for ts, ok in rows:
        key = ts.strftime("%Y-%m-%d") if days <= 31 else ts.strftime("%Y-W%W")
        bucket[key].append(bool(ok))
    return {k: round(sum(v) / len(v), 4) for k, v in sorted(bucket.items())}
