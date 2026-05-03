"""Normalize legacy question text that still contains private-use glyphs."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models import Question
from app.services.question_text import sanitize_question_record


def main() -> None:
    db = SessionLocal()
    try:
        questions = db.query(Question).all()
        changed = 0
        for question in questions:
            if sanitize_question_record(question):
                changed += 1
        db.commit()
        print(f"updated_questions={changed}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
