"""Tests for structured question-to-law article links."""
from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Question, QuestionLawArticleRef, QuestionType, Subject
from app.services.law_links import law_frequency_stats, linked_law_refs, linked_questions_for_law


def test_question_can_link_to_law_article(db, seeded_db):
    question = seeded_db["question"]
    law = seeded_db["law"]
    article = seeded_db["law_article"]

    ref = QuestionLawArticleRef(
        question_id=question.id,
        law_id=law.id,
        law_article_id=article.id,
        article_no=article.article_no,
        source="seed",
        confidence=1.0,
    )
    db.add(ref)
    db.commit()
    db.refresh(ref)

    assert ref.id is not None
    assert ref.question.id == question.id
    assert ref.law.id == law.id
    assert ref.law_article.id == article.id


def test_duplicate_question_law_article_link_is_rejected(db, seeded_db):
    question = seeded_db["question"]
    law = seeded_db["law"]
    article = seeded_db["law_article"]

    db.add(
        QuestionLawArticleRef(
            question_id=question.id,
            law_id=law.id,
            law_article_id=article.id,
            article_no=article.article_no,
            source="seed",
        )
    )
    db.commit()

    db.add(
        QuestionLawArticleRef(
            question_id=question.id,
            law_id=law.id,
            law_article_id=article.id,
            article_no=article.article_no,
            source="manual",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_linked_questions_for_law_includes_raw_law_refs_fallback(db, seeded_db):
    law = seeded_db["law"]
    question = Question(
        subject_id=seeded_db["subject"].id,
        chapter_id=seeded_db["chapter"].id,
        type=QuestionType.CHOICE,
        year=114,
        body="依民法規定，下列何者正確？",
        options=[{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}],
        answer="A",
        law_refs=[law.name],
        source="moex:test",
    )
    db.add(question)
    db.commit()

    rows = linked_questions_for_law(db, law.id)
    assert any(item.id == question.id for item in rows)


def test_linked_law_refs_returns_clickable_url(db, seeded_db):
    law = seeded_db["law"]
    article = seeded_db["law_article"]
    question = seeded_db["question"]
    question.law_refs = [f"{law.name} 第{article.article_no}條"]

    refs = linked_law_refs(db, question)

    assert refs[0]["label"] == f"{law.name} 第{article.article_no}條"
    assert refs[0]["url"] == f"/laws/{law.id}#article-{article.article_no}"


def test_law_frequency_stats_counts_linked_questions(db, seeded_db):
    law = seeded_db["law"]
    article = seeded_db["law_article"]
    question = seeded_db["question"]
    question.law_refs = [f"{law.name} 第{article.article_no}條"]

    stats = law_frequency_stats(db)

    assert stats[law.id]["question_count"] >= 1
    assert float(stats[law.id]["importance_score"]) > 0
    assert float(stats[law.id]["weight"]) > 1.0


def test_law_frequency_stats_can_scope_by_subject(db, seeded_db):
    law = seeded_db["law"]
    article = seeded_db["law_article"]
    question = seeded_db["question"]
    question.law_refs = [f"{law.name} 第{article.article_no}條"]

    other_subject = Subject(code="other", name="其他科目")
    db.add(other_subject)
    db.flush()
    other_question = Question(
        subject_id=other_subject.id,
        type=QuestionType.CHOICE,
        year=114,
        body="其他科目題目",
        options=[{"key": "A", "text": "甲"}],
        answer="A",
        law_refs=[f"{law.name} 第{article.article_no}條"],
    )
    db.add(other_question)
    db.commit()

    scoped = law_frequency_stats(db, subject_id=seeded_db["subject"].id)
    all_stats = law_frequency_stats(db)

    assert scoped[law.id]["question_count"] == 1
    assert all_stats[law.id]["question_count"] >= 2
