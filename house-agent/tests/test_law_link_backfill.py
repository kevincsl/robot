"""Tests for parsing and backfilling legacy law_refs into structured links."""
from __future__ import annotations

from app.models import LawArticle, QuestionLawArticleRef
from app.services.law_links import backfill_question_law_refs, parse_law_ref, relink_question_law_article_ids


def test_parse_law_ref_extracts_name_and_article():
    parsed = parse_law_ref("Civil Code 第758條")
    assert parsed == ("Civil Code", "758")


def test_backfill_question_law_refs_creates_structured_link(db, seeded_db):
    question = seeded_db["question"]
    article = seeded_db["law_article"]
    question.law_refs = [f"{seeded_db['law'].name} 第{article.article_no}條"]

    stats = backfill_question_law_refs(db, questions=[question], source="test_backfill")

    assert stats["questions"] == 1
    assert stats["refs_seen"] == 1
    assert stats["created"] == 1
    links = db.query(QuestionLawArticleRef).all()
    assert len(links) == 1
    assert links[0].question_id == question.id
    assert links[0].article_no == "758"
    assert links[0].source == "test_backfill"


def test_backfill_question_law_refs_is_idempotent(db, seeded_db):
    question = seeded_db["question"]
    article = seeded_db["law_article"]
    question.law_refs = [f"{seeded_db['law'].name} 第{article.article_no}條"]

    first = backfill_question_law_refs(db, questions=[question], source="test_backfill")
    second = backfill_question_law_refs(db, questions=[question], source="test_backfill")

    assert first["created"] == 1
    assert second["created"] == 0
    assert second["skipped_existing"] == 1


def test_relink_question_law_article_ids_updates_stale_article_id(db, seeded_db):
    question = seeded_db["question"]
    article = seeded_db["law_article"]
    stale = QuestionLawArticleRef(
        question_id=question.id,
        law_id=seeded_db["law"].id,
        law_article_id=None,
        article_no=article.article_no,
        source="test",
    )
    db.add(stale)
    db.commit()

    replacement = LawArticle(law_id=seeded_db["law"].id, article_no="9999", body="other")
    db.add(replacement)
    db.commit()

    stats = relink_question_law_article_ids(db)

    db.refresh(stale)
    assert stats["updated"] == 1
    assert stale.law_article_id == article.id
