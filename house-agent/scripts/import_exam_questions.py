"""Import parsed exam-paper questions into the main question bank.

Run:
    python scripts/import_exam_questions.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal, init_db
from app.services.exam_papers import sync_exam_paper_index
from app.services.exam_question_import import import_exam_questions


def run() -> None:
    init_db()
    db = SessionLocal()
    try:
        sync_stats = sync_exam_paper_index(db)
        import_stats = import_exam_questions(db)
        print({"sync": sync_stats, "import": import_stats})
    finally:
        db.close()


if __name__ == "__main__":
    run()
