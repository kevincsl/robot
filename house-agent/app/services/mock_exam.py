"""Mock exam assembly and grading helpers."""
from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models import Question, QuestionType, Subject
from app.services.law_links import question_importance_details


@dataclass
class MockExamPaper:
    questions: list[Question]
    per_subject_target: int


def build_mock_exam(
    db: Session,
    *,
    per_subject: int = 25,
    seed: int | None = None,
) -> MockExamPaper:
    rng = random.Random(seed)
    subjects = db.query(Subject).order_by(Subject.id).all()
    selected: list[Question] = []

    for subject in subjects:
        pool = (
            db.query(Question)
            .filter(
                Question.subject_id == subject.id,
                Question.type == QuestionType.CHOICE,
                Question.answer.is_not(None),
            )
            .all()
        )
        if not pool:
            continue
        chosen = list(pool) if len(pool) <= per_subject else rng.sample(pool, per_subject)
        chosen.sort(key=lambda item: ((item.year or 0), item.id))
        selected.extend(chosen)

    selected.sort(key=lambda item: (item.subject_id, (item.year or 0), item.id))
    return MockExamPaper(questions=selected, per_subject_target=per_subject)


def grade_mock_exam(
    db: Session,
    *,
    question_ids: list[int],
    answers: dict[int, str],
    record_attempt,
    user_id: int | None = None,
) -> dict[str, Any]:
    questions = [db.get(Question, qid) for qid in question_ids]
    questions = [question for question in questions if question is not None and question.type == QuestionType.CHOICE]
    question_map = {question.id: question for question in questions}
    ordered_questions = [question_map[qid] for qid in question_ids if qid in question_map]
    details = question_importance_details(db, [question.id for question in ordered_questions])

    total = len(ordered_questions)
    correct = 0
    by_subject: dict[int, dict[str, Any]] = defaultdict(
        lambda: {
            "subject_id": 0,
            "subject_name": "",
            "total": 0,
            "correct": 0,
            "score": 0.0,
            "wrong_questions": [],
            "study_priority_score": 0.0,
        }
    )

    for question in ordered_questions:
        user_answer = (answers.get(question.id) or "").strip().upper()
        correct_answer = (question.answer or "").strip().upper()
        is_correct = user_answer == correct_answer
        if is_correct:
            correct += 1

        record_attempt(
            db,
            question_id=question.id,
            user_answer=user_answer or None,
            correct=is_correct,
            user_id=user_id,
        )

        importance = details.get(question.id, {"score": 0.0, "weight": 1.0, "level": "敺敞蝛?"})
        item = {
            "question": question,
            "user_answer": user_answer,
            "correct_answer": correct_answer,
            "correct": is_correct,
            "importance_score": float(importance["score"]),
            "importance_weight": float(importance["weight"]),
            "importance_level": str(importance["level"]),
        }

        subject_row = by_subject[question.subject_id]
        subject_row["subject_id"] = question.subject_id
        subject_row["subject_name"] = question.subject.name
        subject_row["total"] += 1
        if is_correct:
            subject_row["correct"] += 1
        else:
            subject_row["wrong_questions"].append(item)
            subject_row["study_priority_score"] += float(importance["weight"])

    for row in by_subject.values():
        row["score"] = round((row["correct"] / row["total"]) * 100, 1) if row["total"] else 0.0
        row["wrong_questions"].sort(
            key=lambda item: (item["importance_weight"], item["importance_score"], item["question"].id),
            reverse=True,
        )

    score = round((correct / total) * 100, 1) if total else 0.0
    subject_breakdown = sorted(
        by_subject.values(),
        key=lambda row: (row["study_priority_score"], row["subject_id"]),
        reverse=True,
    )
    study_recommendations = [row for row in subject_breakdown if row["wrong_questions"]]
    return {
        "total_questions": total,
        "correct_count": correct,
        "wrong_count": total - correct,
        "score": score,
        "passed": score >= 60.0,
        "subject_breakdown": subject_breakdown,
        "study_recommendations": study_recommendations,
    }
