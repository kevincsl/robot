"""Audit completeness of structured question-to-law links."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models import Law, Question, QuestionLawArticleRef


def main() -> None:
    db = SessionLocal()
    try:
        questions = db.query(Question).all()
        laws = db.query(Law).all()
        refs = db.query(QuestionLawArticleRef).all()

        legacy_questions = 0
        total_legacy_refs = 0
        total_structured_refs = 0
        missing_structured: list[int] = []
        expanded_ranges: list[tuple[int, int, int]] = []
        broken_refs: list[int] = []
        unused_laws: list[tuple[str, str]] = []

        for question in questions:
            law_refs = question.law_refs or []
            if not isinstance(law_refs, list) or not law_refs:
                continue
            legacy_questions += 1
            legacy_count = len(law_refs)
            structured_count = len(question.law_article_refs)
            total_legacy_refs += legacy_count
            total_structured_refs += structured_count
            if structured_count == 0:
                missing_structured.append(question.id)
            if structured_count > legacy_count:
                expanded_ranges.append((question.id, legacy_count, structured_count))

        for ref in refs:
            if ref.question is None or ref.law is None or ref.law_article is None:
                broken_refs.append(ref.id)

        for law in laws:
            if not law.question_refs:
                unused_laws.append((law.code, law.name))

        print("Law Link Audit")
        print(f"questions: {len(questions)}")
        print(f"legacy_questions: {legacy_questions}")
        print(f"total_legacy_refs: {total_legacy_refs}")
        print(f"total_structured_refs: {total_structured_refs}")
        print(f"missing_structured_questions: {missing_structured}")
        print(f"broken_ref_ids: {broken_refs}")
        print(f"expanded_range_questions: {expanded_ranges}")
        print("unused_laws:")
        for code, name in unused_laws:
            print(f"- {code} {name}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
