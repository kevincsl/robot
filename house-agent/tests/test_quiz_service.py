"""Tests for quiz service logic."""
from __future__ import annotations

import pytest

from app.models import Attempt, Question, QuestionType
from app.services.quiz import (
    accuracy_buckets,
    coverage_by_subject,
    pick_choice_question,
    record_attempt,
    wrong_questions,
)


class TestPickQuestion:
    def test_returns_none_when_empty(self, db):
        assert pick_choice_question(db) is None

    def test_returns_question(self, db, seeded_db):
        q = pick_choice_question(db)
        assert q is not None
        assert q.type == QuestionType.CHOICE

    def test_subject_filter(self, db, seeded_db):
        subj_id = seeded_db["subject"].id
        q = pick_choice_question(db, subject_id=subj_id)
        assert q is not None
        assert q.subject_id == subj_id

    def test_invalid_subject_returns_none(self, db, seeded_db):
        q = pick_choice_question(db, subject_id=99999)
        assert q is None

    def test_chapter_filter(self, db, seeded_db):
        chap_id = seeded_db["chapter"].id
        q = pick_choice_question(db, chapter_id=chap_id)
        assert q is not None
        assert q.chapter_id == chap_id


class TestRecordAttempt:
    def test_records_correct(self, db, seeded_db):
        q = seeded_db["question"]
        attempt = record_attempt(db, question_id=q.id, user_answer="C", correct=True, time_spent_ms=1500)
        assert attempt.id is not None
        assert attempt.correct is True
        assert attempt.time_spent_ms == 1500

    def test_records_wrong(self, db, seeded_db):
        q = seeded_db["question"]
        attempt = record_attempt(db, question_id=q.id, user_answer="A", correct=False)
        assert attempt.correct is False

    def test_records_with_score(self, db, seeded_db):
        q = seeded_db["essay"]
        attempt = record_attempt(db, question_id=q.id, user_answer="some answer", correct=True, score=75.0)
        assert attempt.score == 75.0


class TestCoverage:
    def test_empty_db(self, db):
        cov = coverage_by_subject(db)
        assert cov == []

    def test_zero_coverage_before_attempts(self, db, seeded_db):
        cov = coverage_by_subject(db)
        assert len(cov) == 1
        assert cov[0]["total"] == 1
        assert cov[0]["seen"] == 0
        assert cov[0]["coverage"] == 0.0

    def test_coverage_after_attempt(self, db, seeded_db):
        q = seeded_db["question"]
        record_attempt(db, question_id=q.id, user_answer="C", correct=True)
        cov = coverage_by_subject(db)
        assert cov[0]["seen"] == 1
        assert cov[0]["coverage"] == 1.0

    def test_coverage_not_double_counts(self, db, seeded_db):
        q = seeded_db["question"]
        record_attempt(db, question_id=q.id, user_answer="C", correct=True)
        record_attempt(db, question_id=q.id, user_answer="A", correct=False)
        cov = coverage_by_subject(db)
        assert cov[0]["seen"] == 1


class TestAccuracyBuckets:
    def test_empty_returns_empty(self, db):
        assert accuracy_buckets(db, days=30) == {}

    def test_buckets_with_data(self, db, seeded_db):
        q = seeded_db["question"]
        record_attempt(db, question_id=q.id, user_answer="C", correct=True)
        record_attempt(db, question_id=q.id, user_answer="A", correct=False)
        result = accuracy_buckets(db, days=30)
        assert len(result) > 0
        val = list(result.values())[0]
        assert 0.0 <= val <= 1.0


class TestWrongQuestions:
    def test_empty_when_no_wrong(self, db, seeded_db):
        q = seeded_db["question"]
        record_attempt(db, question_id=q.id, user_answer="C", correct=True)
        wrong = wrong_questions(db)
        assert len(wrong) == 0

    def test_shows_wrong_questions(self, db, seeded_db):
        q = seeded_db["question"]
        record_attempt(db, question_id=q.id, user_answer="A", correct=False)
        record_attempt(db, question_id=q.id, user_answer="B", correct=False)
        wrong = wrong_questions(db)
        assert len(wrong) == 1
        assert wrong[0]["wrong"] == 2
        assert wrong[0]["wrong_rate"] == 100.0

    def test_wrong_questions_are_user_isolated(self, db, seeded_db, two_users):
        q = seeded_db["question"]
        alice, bob = two_users
        record_attempt(db, question_id=q.id, user_answer="A", correct=False, user_id=alice.id)
        record_attempt(db, question_id=q.id, user_answer="C", correct=True, user_id=bob.id)
        rows = wrong_questions(db, user_id=alice.id)
        assert len(rows) == 1
        assert rows[0]["wrong"] == 1
        assert wrong_questions(db, user_id=bob.id) == []
