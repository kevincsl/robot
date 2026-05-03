"""Pytest configuration and fixtures for house-agent tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.models import Base, Chapter, Law, LawArticle, Question, QuestionType, Subject, User
from app.services.rate_limit import reset_rate_limits


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def client(db):
    from app.db import get_session
    from app.main import app

    def _override():
        yield db

    app.dependency_overrides[get_session] = _override
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def reset_security_state():
    reset_rate_limits()
    yield
    reset_rate_limits()


@pytest.fixture
def post_with_csrf(client):
    def _post(path: str, *, data: dict | None = None, fetch_path: str = "/login", follow_redirects: bool = True):
        client.get(fetch_path)
        token = client.cookies.get("house_agent_csrf_token")
        payload = dict(data or {})
        payload["csrf_token"] = token
        return client.post(path, data=payload, follow_redirects=follow_redirects)

    return _post


@pytest.fixture
def seeded_db(db):
    """DB with one subject, chapter, and questions."""
    subj = Subject(code="civil_law", name="民法概要")
    db.add(subj)
    db.flush()
    chap = Chapter(subject_id=subj.id, code="物權編", name="物權編")
    db.add(chap)
    db.flush()
    q = Question(
        subject_id=subj.id,
        chapter_id=chap.id,
        type=QuestionType.CHOICE,
        year=112,
        body="甲將不動產移轉登記予乙，乙何時取得所有權？",
        options=[
            {"key": "A", "text": "合意時"},
            {"key": "B", "text": "交付時"},
            {"key": "C", "text": "登記完畢時"},
            {"key": "D", "text": "公證時"},
        ],
        answer="C",
        explanation="民法第758條：非經登記，不生效力。",
        law_refs=["民法 §758"],
    )
    db.add(q)
    essay = Question(
        subject_id=subj.id,
        type=QuestionType.ESSAY,
        year=111,
        body="試說明不動產物權登記之效力。",
        answer="重點：登記生效主義（民法§758）",
        law_refs=[],
    )
    db.add(essay)
    law = Law(code="B0000001", name="民法")
    db.add(law)
    db.flush()
    article = LawArticle(law_id=law.id, article_no="758", body="Sample law article body.")
    db.add(article)
    db.commit()
    return {
        "subject": subj,
        "chapter": chap,
        "question": q,
        "essay": essay,
        "law": law,
        "law_article": article,
    }


@pytest.fixture
def two_users(db):
    users = [
        User(username="alice", display_name="Alice", password_hash="x"),
        User(username="bob", display_name="Bob", password_hash="y"),
    ]
    db.add_all(users)
    db.commit()
    return users
