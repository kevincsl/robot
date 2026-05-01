from __future__ import annotations

from app.models import Attempt, Chapter, Law, LawArticle, Question, QuestionType, Subject
from app.services.quiz import wrong_questions


def test_wrong_questions_prioritizes_importance_weight(db):
    subj = Subject(code="civil_law", name="民法概要")
    db.add(subj)
    db.flush()
    chap = Chapter(subject_id=subj.id, code="c1", name="總則")
    db.add(chap)
    law = Law(code="B0000001", name="民法")
    db.add(law)
    db.flush()
    db.add(LawArticle(law_id=law.id, article_no="758", body="sample"))

    high = Question(
        subject_id=subj.id,
        chapter_id=chap.id,
        type=QuestionType.CHOICE,
        year=114,
        body="高權重題，依民法第758條，下列何者正確？",
        options=[{"key": "A", "text": "甲"}],
        answer="A",
        law_refs=["民法 第758條"],
    )
    low = Question(
        subject_id=subj.id,
        chapter_id=chap.id,
        type=QuestionType.CHOICE,
        year=114,
        body="低權重題",
        options=[{"key": "A", "text": "甲"}],
        answer="A",
        law_refs=[],
    )
    db.add_all([high, low])
    db.flush()

    db.add_all(
        [
            Attempt(question_id=high.id, user_answer="B", correct=False),
            Attempt(question_id=high.id, user_answer="B", correct=False),
            Attempt(question_id=high.id, user_answer="A", correct=True),
            Attempt(question_id=low.id, user_answer="B", correct=False),
            Attempt(question_id=low.id, user_answer="A", correct=True),
        ]
    )
    db.commit()

    rows = wrong_questions(db, limit=10)

    assert rows[0]["question"].id == high.id
    assert rows[0]["importance_weight"] > rows[1]["importance_weight"]
