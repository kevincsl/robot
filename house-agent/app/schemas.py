"""Pydantic schemas for API I/O."""
from __future__ import annotations

from pydantic import BaseModel


class ChoiceSubmit(BaseModel):
    question_id: int
    user_answer: str
    time_spent_ms: int | None = None


class EssaySubmit(BaseModel):
    question_id: int
    user_answer: str


class QuestionOut(BaseModel):
    id: int
    type: str
    subject: str
    chapter: str | None
    body: str
    options: list | None
    year: int | None

    model_config = {"from_attributes": True}


class GradingOut(BaseModel):
    score: int
    dimensions: dict
    strengths: list[str]
    weaknesses: list[str]
    improved_answer: str
    key_law_refs: list[str]
