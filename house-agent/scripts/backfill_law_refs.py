"""Backfill structured question-to-law links from legacy question.law_refs JSON."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal, init_db
from app.services.law_links import backfill_question_law_refs


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        stats = backfill_question_law_refs(db, source="legacy_law_refs")
    finally:
        db.close()
    print("Backfill completed.")
    for key, value in stats.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
