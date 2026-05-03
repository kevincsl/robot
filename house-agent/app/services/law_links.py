"""Helpers for structured links between questions and law articles."""
from __future__ import annotations

import re
from collections.abc import Iterable
from math import sqrt

from sqlalchemy.orm import Session

from app.models import Law, LawArticle, Question, QuestionLawArticleRef

ARTICLE_NO_PATTERN = re.compile(r"(\d+(?:-\d+)?)")
NAME_NORMALIZE_PATTERN = re.compile(r"[\s\u3000:：()（）\[\]「」『』,，。．、]")
TRAILING_MARKER_PATTERN = re.compile(r"(?:第|條|条|款|項|项|目|號|号|禮|礼|§)+\s*$")


def normalize_law_name(text: str) -> str:
    return NAME_NORMALIZE_PATTERN.sub("", str(text or "")).strip().lower()


def extract_article_no(text: str) -> str | None:
    matches = ARTICLE_NO_PATTERN.findall(str(text or ""))
    if not matches:
        return None
    return matches[-1]


def extract_article_nos(text: str) -> list[str]:
    seen: list[str] = []
    for match in ARTICLE_NO_PATTERN.findall(str(text or "")):
        if match not in seen:
            seen.append(match)
    return seen


def parse_law_ref(ref_text: str) -> tuple[str, str] | None:
    raw = str(ref_text or "").strip()
    if not raw:
        return None
    article_no = extract_article_no(raw)
    if not article_no:
        return None
    idx = raw.rfind(article_no)
    if idx < 0:
        return None
    law_name = raw[:idx].rstrip(" :-：")
    if "§" in law_name:
        law_name = law_name.split("§", 1)[0].strip()
    law_name = TRAILING_MARKER_PATTERN.sub("", law_name).strip()
    law_name = law_name.strip()
    return law_name, article_no


def find_law_by_name(db: Session, law_name: str) -> Law | None:
    needle = normalize_law_name(law_name)
    if not needle:
        return None
    laws = list(db.query(Law).all())
    exact = next((law for law in laws if normalize_law_name(law.name) == needle), None)
    if exact is not None:
        return exact
    return next(
        (
            law
            for law in laws
            if needle in normalize_law_name(law.name) or normalize_law_name(law.name) in needle
        ),
        None,
    )


def _find_law_by_name_cached(laws: list[Law], law_name: str) -> Law | None:
    needle = normalize_law_name(law_name)
    if not needle:
        return None
    exact = next((law for law in laws if normalize_law_name(law.name) == needle), None)
    if exact is not None:
        return exact
    return next(
        (
            law
            for law in laws
            if needle in normalize_law_name(law.name) or normalize_law_name(law.name) in needle
        ),
        None,
    )


def find_law_article(db: Session, law_id: int, article_no: str) -> LawArticle | None:
    target = extract_article_no(article_no)
    if not target:
        return None
    articles = db.query(LawArticle).filter(LawArticle.law_id == law_id).all()
    return next((article for article in articles if extract_article_no(article.article_no) == target), None)


def serialize_question_law_refs(question: Question) -> list[str]:
    refs: list[str] = []
    for ref in question.law_article_refs:
        law_name = str(ref.law.name or "").strip() if ref.law is not None else ""
        article_no = str(ref.article_no or "").strip()
        if not law_name or not article_no:
            continue
        label = f"{law_name} 第{article_no}條"
        if label not in refs:
            refs.append(label)
    if refs:
        return refs
    raw = question.law_refs or []
    return [str(item) for item in raw if str(item).strip()]


def article_anchor(article_no: str) -> str:
    value = re.sub(r"[^0-9-]+", "", str(article_no or ""))
    return f"article-{value}" if value else "article"


def linked_law_refs(db: Session, question: Question) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for ref in question.law_article_refs:
        law_name = str(ref.law.name or "").strip() if ref.law is not None else ""
        article_no = str(ref.article_no or "").strip()
        if not law_name:
            continue
        label = f"{law_name} 第{article_no}條" if article_no else law_name
        url = f"/laws/{ref.law_id}"
        if article_no:
            url += f"#{article_anchor(article_no)}"
        refs.append({"label": label, "url": url})
    if refs:
        return refs

    for raw_ref in question.law_refs or []:
        text = str(raw_ref or "").strip()
        if not text:
            continue
        parsed = parse_law_ref(text)
        if parsed is not None:
            law_name, article_no = parsed
            law = find_law_by_name(db, law_name)
            if law is not None:
                refs.append(
                    {
                        "label": f"{law.name} 第{article_no}條",
                        "url": f"/laws/{law.id}#{article_anchor(article_no)}",
                    }
                )
                continue
        law = find_law_by_name(db, text)
        if law is not None:
            refs.append({"label": law.name, "url": f"/laws/{law.id}"})
        else:
            refs.append({"label": text, "url": ""})
    return refs


def linked_questions_for_law(db: Session, law_id: int, limit: int = 100) -> list[Question]:
    rows = (
        db.query(Question)
        .join(QuestionLawArticleRef, QuestionLawArticleRef.question_id == Question.id)
        .filter(QuestionLawArticleRef.law_id == law_id)
        .distinct()
        .all()
    )
    law = db.get(Law, law_id)
    if law is None:
        return rows[:limit]

    seen_ids = {question.id for question in rows}
    fallback_rows = []
    needle = normalize_law_name(law.name)
    if needle:
        for question in db.query(Question).all():
            if question.id in seen_ids:
                continue
            raw_refs = question.law_refs or []
            if not isinstance(raw_refs, list):
                continue
            normalized_refs = [normalize_law_name(str(item)) for item in raw_refs if str(item).strip()]
            if any(needle in ref or ref in needle for ref in normalized_refs if ref):
                fallback_rows.append(question)

    combined = rows + fallback_rows
    combined.sort(key=lambda question: ((question.year or 0), question.id), reverse=True)
    return combined[:limit]


def _importance_level(score: float) -> str:
    if score >= 80:
        return "核心重點"
    if score >= 50:
        return "高頻重點"
    if score >= 25:
        return "中頻重點"
    if score > 0:
        return "低頻重點"
    return "待累積"


def law_frequency_stats(
    db: Session,
    *,
    subject_id: int | None = None,
) -> dict[int, dict[str, float | int | str]]:
    laws = list(db.query(Law).all())
    question_law_ids = question_law_ids_map(db, subject_ids=[subject_id] if subject_id is not None else None)

    counts = {
        law.id: len({question_id for question_id, law_ids in question_law_ids.items() if law.id in law_ids})
        for law in laws
    }
    max_count = max(counts.values(), default=0)
    if max_count <= 0:
        return {
            law.id: {
                "question_count": 0,
                "importance_score": 0.0,
                "weight": 1.0,
                "level": "待累積",
            }
            for law in laws
        }

    stats: dict[int, dict[str, float | int | str]] = {}
    for law in laws:
        count = counts.get(law.id, 0)
        ratio = sqrt(count / max_count) if count else 0.0
        score = round(ratio * 100, 1)
        level = _importance_level(score)
        stats[law.id] = {
            "question_count": count,
            "importance_score": score,
            "weight": round(1.0 + score / 100.0, 3),
            "level": level,
        }
    return stats


def question_law_ids_map(
    db: Session,
    question_ids: list[int] | None = None,
    subject_ids: list[int] | None = None,
) -> dict[int, set[int]]:
    rows = list(db.query(Question).all())
    if question_ids is not None:
        allowed = set(question_ids)
        rows = [question for question in rows if question.id in allowed]
    if subject_ids is not None:
        allowed_subjects = set(subject_ids)
        rows = [question for question in rows if question.subject_id in allowed_subjects]
    laws = list(db.query(Law).all())
    mapping: dict[int, set[int]] = {question.id: set() for question in rows}

    structured = db.query(QuestionLawArticleRef).all()
    for ref in structured:
        if ref.question_id not in mapping:
            continue
        mapping.setdefault(ref.question_id, set()).add(ref.law_id)

    for question in rows:
        last_law_name = ""
        for raw_ref in question.law_refs or []:
            text = str(raw_ref or "").strip()
            if not text:
                continue
            parsed = parse_law_ref(text)
            law_name = ""
            if parsed is not None:
                law_name = parsed[0]
            else:
                law_name = text
            if law_name:
                last_law_name = law_name
            elif last_law_name:
                law_name = last_law_name
            law = _find_law_by_name_cached(laws, law_name)
            if law is not None:
                mapping.setdefault(question.id, set()).add(law.id)
    return mapping


def question_importance_scores(
    db: Session,
    question_ids: list[int],
) -> dict[int, float]:
    questions = [question for question in db.query(Question).all() if question.id in set(question_ids)]
    by_subject: dict[int, list[int]] = {}
    for question in questions:
        by_subject.setdefault(question.subject_id, []).append(question.id)

    scores: dict[int, float] = {}
    for subject_id, scoped_question_ids in by_subject.items():
        law_stats = law_frequency_stats(db, subject_id=subject_id)
        question_laws = question_law_ids_map(
            db,
            question_ids=scoped_question_ids,
            subject_ids=[subject_id],
        )
        for question_id in scoped_question_ids:
            linked_ids = question_laws.get(question_id, set())
            if not linked_ids:
                scores[question_id] = 0.0
                continue
            best = max(float(law_stats.get(law_id, {}).get("importance_score", 0.0)) for law_id in linked_ids)
            scores[question_id] = best
    for question_id in question_ids:
        scores.setdefault(question_id, 0.0)
    return scores


def question_importance_details(
    db: Session,
    question_ids: list[int],
) -> dict[int, dict[str, float | str]]:
    questions = [question for question in db.query(Question).all() if question.id in set(question_ids)]
    details: dict[int, dict[str, float | str]] = {}
    by_subject: dict[int, list[int]] = {}
    for question in questions:
        by_subject.setdefault(question.subject_id, []).append(question.id)

    for subject_id, scoped_question_ids in by_subject.items():
        subject_stats = law_frequency_stats(db, subject_id=subject_id)
        question_laws = question_law_ids_map(
            db,
            question_ids=scoped_question_ids,
            subject_ids=[subject_id],
        )
        for question_id in scoped_question_ids:
            linked_ids = question_laws.get(question_id, set())
            if not linked_ids:
                details[question_id] = {"score": 0.0, "weight": 1.0, "level": _importance_level(0.0)}
                continue
            best = max(float(subject_stats.get(law_id, {}).get("importance_score", 0.0)) for law_id in linked_ids)
            details[question_id] = {
                "score": round(best, 1),
                "weight": round(1.0 + best / 100.0, 3),
                "level": _importance_level(best),
            }
    return details


def backfill_question_law_refs(
    db: Session,
    *,
    questions: Iterable[Question] | None = None,
    source: str = "backfill",
    confidence: float = 0.9,
) -> dict[str, int]:
    stats = {
        "questions": 0,
        "refs_seen": 0,
        "created": 0,
        "skipped_existing": 0,
        "unresolved_law": 0,
        "unresolved_article": 0,
        "malformed": 0,
    }
    target_questions = list(questions) if questions is not None else list(db.query(Question).all())
    for question in target_questions:
        stats["questions"] += 1
        refs = question.law_refs or []
        if not isinstance(refs, list):
            continue
        last_law_name = ""
        for ref_text in refs:
            stats["refs_seen"] += 1
            text = str(ref_text)
            parsed = parse_law_ref(text)
            if parsed is None:
                stats["malformed"] += 1
                continue
            law_name, _article_no = parsed
            article_nos = extract_article_nos(text)
            if not article_nos:
                stats["malformed"] += 1
                continue
            if law_name:
                last_law_name = law_name
            elif last_law_name:
                law_name = last_law_name
            else:
                stats["unresolved_law"] += 1
                continue
            law = find_law_by_name(db, law_name)
            if law is None:
                stats["unresolved_law"] += 1
                continue
            for article_no in article_nos:
                existing = (
                    db.query(QuestionLawArticleRef)
                    .filter(
                        QuestionLawArticleRef.question_id == question.id,
                        QuestionLawArticleRef.law_id == law.id,
                        QuestionLawArticleRef.article_no == article_no,
                    )
                    .first()
                )
                if existing is not None:
                    stats["skipped_existing"] += 1
                    continue
                article = find_law_article(db, law.id, article_no)
                if article is None:
                    stats["unresolved_article"] += 1
                    continue
                db.add(
                    QuestionLawArticleRef(
                        question_id=question.id,
                        law_id=law.id,
                        law_article_id=article.id,
                        article_no=article_no,
                        source=source,
                        confidence=confidence,
                        note=text,
                    )
                )
                stats["created"] += 1
    db.commit()
    return stats


def relink_question_law_article_ids(db: Session) -> dict[str, int]:
    stats = {"total_refs": 0, "updated": 0, "cleared": 0}
    refs = list(db.query(QuestionLawArticleRef).all())
    for ref in refs:
        stats["total_refs"] += 1
        article = find_law_article(db, ref.law_id, ref.article_no)
        if article is None:
            if ref.law_article_id is not None:
                ref.law_article_id = None
                stats["cleared"] += 1
            continue
        if ref.law_article_id != article.id:
            ref.law_article_id = article.id
            stats["updated"] += 1
    db.commit()
    return stats
