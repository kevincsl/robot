"""Database setup."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base
from app.services.auth import get_or_create_default_admin, get_or_create_default_user

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "house_agent.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
    _migrate_legacy_schema()


def _migrate_legacy_schema() -> None:
    inspector = inspect(engine)
    user_columns = {column["name"] for column in inspector.get_columns("users")} if inspector.has_table("users") else set()
    attempt_columns = {column["name"] for column in inspector.get_columns("attempts")} if inspector.has_table("attempts") else set()
    identity_columns = (
        {column["name"] for column in inspector.get_columns("user_identities")}
        if inspector.has_table("user_identities")
        else set()
    )
    audit_log_columns = (
        {column["name"] for column in inspector.get_columns("audit_logs")}
        if inspector.has_table("audit_logs")
        else set()
    )
    with engine.begin() as conn:
        if inspector.has_table("users") and "is_admin" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0"))
        if inspector.has_table("users") and "status" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN status VARCHAR(16) DEFAULT 'active'"))
        if inspector.has_table("users") and "login_policy" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN login_policy VARCHAR(32) DEFAULT 'local_or_oauth'"))
        if "user_id" not in attempt_columns:
            conn.execute(text("ALTER TABLE attempts ADD COLUMN user_id INTEGER"))
        if inspector.has_table("user_identities") and "avatar_url" not in identity_columns:
            conn.execute(text("ALTER TABLE user_identities ADD COLUMN avatar_url VARCHAR(512)"))
        if inspector.has_table("audit_logs") and "details" not in audit_log_columns:
            conn.execute(text("ALTER TABLE audit_logs ADD COLUMN details JSON"))
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_question_law_relink_runs_idempotency_key "
                "ON question_law_relink_runs (idempotency_key)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_question_law_relink_results_run_question "
                "ON question_law_relink_results (run_id, question_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_question_law_relink_diffs_run_question "
                "ON question_law_relink_diffs (run_id, question_id)"
            )
        )
    db = SessionLocal()
    try:
        default_user = get_or_create_default_user(db)
        get_or_create_default_admin(db)
        if inspector.has_table("users"):
            db.execute(text("UPDATE users SET status = 'active' WHERE status IS NULL OR status = ''"))
            db.execute(text("UPDATE users SET login_policy = 'local_or_oauth' WHERE login_policy IS NULL OR login_policy = ''"))
            db.commit()
        if inspector.has_table("attempts"):
            db.execute(
                text("UPDATE attempts SET user_id = :user_id WHERE user_id IS NULL"),
                {"user_id": default_user.id},
            )
            db.commit()
    finally:
        db.close()


def get_session() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
