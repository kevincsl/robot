from __future__ import annotations

from app.models import Law, LawArticle, Question, QuestionLawArticleRef, QuestionType, Subject
from app.services.law_relink_runs import diff_question_refs, run_relink, start_snapshot_run


def test_diff_question_refs_reports_added_removed():
    events = diff_question_refs(["1:10", "1:20"], ["1:20", "2:30"])
    assert {item["diff_type"] for item in events} == {"removed", "added"}


def test_run_relink_creates_run_results_and_diffs(db):
    subject = Subject(code="civil_law", name="民法概要")
    db.add(subject)
    db.flush()

    law = Law(code="B0000001", name="民法")
    db.add(law)
    db.flush()
    db.add_all(
        [
            LawArticle(law_id=law.id, article_no="758", body="a"),
            LawArticle(law_id=law.id, article_no="759", body="b"),
        ]
    )
    db.flush()

    question = Question(
        subject_id=subject.id,
        type=QuestionType.CHOICE,
        body="測試題",
        options=[{"key": "A", "text": "1"}, {"key": "B", "text": "2"}],
        answer="A",
        law_refs=["民法 第758條", "民法 第759條"],
    )
    db.add(question)
    db.flush()

    db.add(
        QuestionLawArticleRef(
            question_id=question.id,
            law_id=law.id,
            law_article_id=None,
            article_no="758",
            source="seed",
        )
    )
    db.commit()

    snapshot = start_snapshot_run(db, trigger_type="test")
    run = run_relink(
        db,
        snapshot_run_id=snapshot.id,
        scope="all",
        idempotency_key="test-run-1",
        source="test",
    )

    assert run.status == "succeeded"
    assert isinstance(run.stats_json, dict)
    assert run.stats_json["questions"] >= 1

    refreshed = db.get(Question, question.id)
    assert len(refreshed.law_article_refs) == 1
    assert refreshed.law_article_refs[0].law_article_id is not None


def test_run_relink_is_idempotent_for_succeeded_run(db):
    snapshot = start_snapshot_run(db, trigger_type="test")
    first = run_relink(
        db,
        snapshot_run_id=snapshot.id,
        scope="all",
        idempotency_key="same-key",
        source="test",
    )
    second = run_relink(
        db,
        snapshot_run_id=snapshot.id,
        scope="all",
        idempotency_key="same-key",
        source="test",
    )
    assert first.id == second.id
