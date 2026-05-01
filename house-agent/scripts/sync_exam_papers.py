"""Sync downloaded exam-paper manifests into SQLite index tables.

Run:
    python scripts/sync_exam_papers.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal, init_db
from app.services.exam_papers import sync_exam_paper_index


def run() -> None:
    init_db()
    db = SessionLocal()
    try:
        stats = sync_exam_paper_index(db)
        print(stats)
    finally:
        db.close()


if __name__ == "__main__":
    run()
