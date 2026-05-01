"""SQLAlchemy ORM models."""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    UniqueConstraint,
    String,
    Text,
    JSON,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class QuestionType(str, enum.Enum):
    CHOICE = "choice"
    ESSAY = "essay"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    password_hash: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    login_policy: Mapped[str] = mapped_column(String(32), default="local_or_oauth", index=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    attempts: Mapped[list["Attempt"]] = relationship(back_populates="user")
    identities: Mapped[list["UserIdentity"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    audit_logs_as_actor: Mapped[list["AuditLog"]] = relationship(
        back_populates="actor_user",
        foreign_keys="AuditLog.actor_user_id",
    )
    audit_logs_as_target: Mapped[list["AuditLog"]] = relationship(
        back_populates="target_user",
        foreign_keys="AuditLog.target_user_id",
    )


class UserIdentity(Base):
    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_user_identity_provider_subject"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    provider_user_id: Mapped[str] = mapped_column(String(256), index=True)
    email: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    user: Mapped[User] = relationship(back_populates="identities")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    target_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    actor_user: Mapped[User | None] = relationship(
        back_populates="audit_logs_as_actor",
        foreign_keys=[actor_user_id],
    )
    target_user: Mapped[User | None] = relationship(
        back_populates="audit_logs_as_target",
        foreign_keys=[target_user_id],
    )


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))

    chapters: Mapped[list["Chapter"]] = relationship(back_populates="subject", cascade="all, delete-orphan")
    questions: Mapped[list["Question"]] = relationship(back_populates="subject")


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(256))

    subject: Mapped[Subject] = relationship(back_populates="chapters")
    questions: Mapped[list["Question"]] = relationship(back_populates="chapter")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id"), nullable=True)
    type: Mapped[QuestionType] = mapped_column(Enum(QuestionType))
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str | None] = mapped_column(String(256), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    law_refs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    difficulty: Mapped[int] = mapped_column(Integer, default=3)

    subject: Mapped[Subject] = relationship(back_populates="questions")
    chapter: Mapped[Chapter | None] = relationship(back_populates="questions")
    attempts: Mapped[list["Attempt"]] = relationship(back_populates="question", cascade="all, delete-orphan")
    law_article_refs: Mapped[list["QuestionLawArticleRef"]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
    )


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    user_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    correct: Mapped[bool] = mapped_column(Boolean)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    time_spent_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user: Mapped[User | None] = relationship(back_populates="attempts")
    question: Mapped[Question] = relationship(back_populates="attempts")


class Law(Base):
    __tablename__ = "laws"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(128), unique=True)
    name: Mapped[str] = mapped_column(String(256))
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    articles: Mapped[list["LawArticle"]] = relationship(back_populates="law", cascade="all, delete-orphan")
    question_refs: Mapped[list["QuestionLawArticleRef"]] = relationship(back_populates="law")


class LawArticle(Base):
    __tablename__ = "law_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    law_id: Mapped[int] = mapped_column(ForeignKey("laws.id"))
    article_no: Mapped[str] = mapped_column(String(32))
    body: Mapped[str] = mapped_column(Text)

    law: Mapped[Law] = relationship(back_populates="articles")
    question_refs: Mapped[list["QuestionLawArticleRef"]] = relationship(back_populates="law_article")


class QuestionLawArticleRef(Base):
    __tablename__ = "question_law_article_refs"
    __table_args__ = (
        UniqueConstraint("question_id", "law_id", "article_no", name="uq_question_law_article_ref"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    law_id: Mapped[int] = mapped_column(ForeignKey("laws.id"), index=True)
    law_article_id: Mapped[int | None] = mapped_column(ForeignKey("law_articles.id"), nullable=True, index=True)
    article_no: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(32), default="seed")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    question: Mapped[Question] = relationship(back_populates="law_article_refs")
    law: Mapped[Law] = relationship(back_populates="question_refs")
    law_article: Mapped[LawArticle | None] = relationship(back_populates="question_refs")


class ExamPaper(Base):
    __tablename__ = "exam_papers"

    id: Mapped[int] = mapped_column(primary_key=True)
    bundle_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    roc_year: Mapped[int] = mapped_column(Integer, index=True)
    exam_code: Mapped[str] = mapped_column(String(32), index=True)
    exam_name: Mapped[str] = mapped_column(String(512))
    exam_title: Mapped[str] = mapped_column(String(512))
    stats: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_dir: Mapped[str] = mapped_column(String(512))

    subjects: Mapped[list["ExamPaperSubject"]] = relationship(
        back_populates="exam_paper",
        cascade="all, delete-orphan",
        order_by="ExamPaperSubject.sort_order",
    )
    files: Mapped[list["ExamPaperFile"]] = relationship(
        back_populates="exam_paper",
        cascade="all, delete-orphan",
        order_by="ExamPaperFile.sort_order",
    )

    @property
    def overall_files(self) -> list["ExamPaperFile"]:
        return [item for item in self.files if item.is_overall]

    @property
    def items(self) -> list["ExamPaperSubject"]:
        return self.subjects


class ExamPaperSubject(Base):
    __tablename__ = "exam_paper_subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_paper_id: Mapped[int] = mapped_column(ForeignKey("exam_papers.id"), index=True)
    category: Mapped[str] = mapped_column(String(256))
    subject: Mapped[str] = mapped_column(String(512), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    exam_paper: Mapped[ExamPaper] = relationship(back_populates="subjects")
    files: Mapped[list["ExamPaperFile"]] = relationship(
        back_populates="subject_row",
        cascade="all, delete-orphan",
        order_by="ExamPaperFile.sort_order",
    )

    @property
    def subject_row(self) -> "ExamPaperSubject":
        return self


class ExamPaperFile(Base):
    __tablename__ = "exam_paper_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_paper_id: Mapped[int] = mapped_column(ForeignKey("exam_papers.id"), index=True)
    exam_paper_subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("exam_paper_subjects.id"),
        nullable=True,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(128))
    href: Mapped[str] = mapped_column(String(512))
    local_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_overall: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    exam_paper: Mapped[ExamPaper] = relationship(back_populates="files")
    subject_row: Mapped[ExamPaperSubject | None] = relationship(back_populates="files")


class LawSnapshotRun(Base):
    __tablename__ = "law_snapshot_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    trigger_type: Mapped[str] = mapped_column(String(32), default="manual", index=True)
    triggered_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    catalog_hash: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class QuestionLawRelinkRun(Base):
    __tablename__ = "question_law_relink_runs"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_question_law_relink_runs_idempotency_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_run_id: Mapped[int | None] = mapped_column(ForeignKey("law_snapshot_runs.id"), nullable=True, index=True)
    scope: Mapped[str] = mapped_column(String(32), default="all", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    stats_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class QuestionLawRelinkResult(Base):
    __tablename__ = "question_law_relink_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("question_law_relink_runs.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    old_refs: Mapped[list] = mapped_column(JSON, default=list)
    new_refs: Mapped[list] = mapped_column(JSON, default=list)
    changed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class QuestionLawRelinkDiff(Base):
    __tablename__ = "question_law_relink_diffs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("question_law_relink_runs.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    diff_type: Mapped[str] = mapped_column(String(32), index=True)
    flip_type: Mapped[str] = mapped_column(String(32), default="link_only_changed", index=True)
    old_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
