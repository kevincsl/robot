"""Tests for FastAPI routes."""
from __future__ import annotations

import json
from pathlib import Path

from app.models import AuditLog, ExamPaper, ExamPaperSubject, QuestionLawArticleRef, UserIdentity


class TestHomepage:
    def test_home_ok(self, client, seeded_db):
        r = client.get("/")
        assert r.status_code == 200
        assert "House Agent" in r.text

    def test_home_shows_subject(self, client, seeded_db):
        r = client.get("/")
        assert "民法" in r.text


    def test_register_and_login_shows_user_name(self, client, post_with_csrf):
        r = post_with_csrf(
            "/register",
            data={"username": "alice", "display_name": "Alice", "password": "pass1234"},
            fetch_path="/login",
            follow_redirects=True,
        )
        assert r.status_code == 200
        assert "目前使用者：Alice" in r.text


class TestQuiz:
    def test_quiz_page_loads(self, client, seeded_db):
        r = client.get("/quiz")
        assert r.status_code == 200

    def test_quiz_with_subject_filter(self, client, seeded_db):
        subj_id = seeded_db["subject"].id
        r = client.get(f"/quiz?subject_id={subj_id}")
        assert r.status_code == 200

    def test_submit_correct_answer(self, client, seeded_db):
        qid = seeded_db["question"].id
        r = client.post(
            "/api/choice/submit",
            json={"question_id": qid, "user_answer": "C", "time_spent_ms": 3000},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["correct"] is True
        assert data["answer"] == "C"
        assert "民法" in (data["explanation"] or "")

    def test_submit_wrong_answer(self, client, seeded_db):
        qid = seeded_db["question"].id
        r = client.post(
            "/api/choice/submit",
            json={"question_id": qid, "user_answer": "A", "time_spent_ms": 2000},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["correct"] is False
        assert data["answer"] == "C"

    def test_submit_returns_law_refs(self, client, seeded_db):
        qid = seeded_db["question"].id
        r = client.post(
            "/api/choice/submit",
            json={"question_id": qid, "user_answer": "C"},
        )
        data = r.json()
        assert isinstance(data["law_refs"], list)
        assert len(data["law_refs"]) > 0

    def test_submit_prefers_structured_law_refs(self, client, db, seeded_db):
        qid = seeded_db["question"].id
        law = seeded_db["law"]
        article = seeded_db["law_article"]
        db.add(
            QuestionLawArticleRef(
                question_id=qid,
                law_id=law.id,
                law_article_id=article.id,
                article_no=article.article_no,
                source="test",
            )
        )
        db.commit()
        r = client.post(
            "/api/choice/submit",
            json={"question_id": qid, "user_answer": "C"},
        )
        data = r.json()
        assert data["law_refs"] == [f"{law.name} 第{article.article_no}條"]

    def test_submit_invalid_question(self, client, seeded_db):
        r = client.post(
            "/api/choice/submit",
            json={"question_id": 99999, "user_answer": "A"},
        )
        assert r.status_code == 404

    def test_answer_case_insensitive(self, client, seeded_db):
        qid = seeded_db["question"].id
        r = client.post(
            "/api/choice/submit",
            json={"question_id": qid, "user_answer": "c"},
        )
        data = r.json()
        assert data["correct"] is True


class TestEssay:
    def test_essay_page_loads(self, client, seeded_db):
        r = client.get("/essay")
        assert r.status_code == 200

    def test_essay_page_shows_question(self, client, seeded_db):
        r = client.get("/essay")
        assert "House Agent" in r.text

    def test_essay_page_prefers_structured_law_refs(self, client, db, seeded_db):
        essay = seeded_db["essay"]
        law = seeded_db["law"]
        article = seeded_db["law_article"]
        db.add(
            QuestionLawArticleRef(
                question_id=essay.id,
                law_id=law.id,
                law_article_id=article.id,
                article_no=article.article_no,
                source="test",
            )
        )
        db.commit()
        r = client.get("/essay")
        assert r.status_code == 200
        assert f"{law.name} 第{article.article_no}條" in r.text


class TestMockExam:
    def test_mock_exam_page_loads(self, client, seeded_db):
        r = client.get("/mock-exam")
        assert r.status_code == 200
        assert "模擬考" in r.text
        assert "60 分" in r.text

    def test_mock_exam_result_uses_raw_scoring(self, client, db, seeded_db, post_with_csrf):
        from app.models import Question, QuestionLawArticleRef, QuestionType, Subject

        s1 = Subject(code="civil_law_2", name="民法概要")
        s2 = Subject(code="broker_regulations", name="不動產經紀相關法規概要")
        db.add_all([s1, s2])
        db.flush()
        q1 = Question(
            subject_id=s1.id,
            type=QuestionType.CHOICE,
            body="Q1",
            options=[{"key": "A", "text": "1"}, {"key": "B", "text": "2"}],
            answer="A",
            law_refs=["測試法 第1條"],
        )
        q2 = Question(
            subject_id=s2.id,
            type=QuestionType.CHOICE,
            body="Q2",
            options=[{"key": "A", "text": "1"}, {"key": "B", "text": "2"}],
            answer="B",
            law_refs=["測試法 第2條"],
        )
        db.add_all([q1, q2])
        db.flush()
        law = seeded_db["law"]
        article = seeded_db["law_article"]
        db.add_all(
            [
                QuestionLawArticleRef(
                    question_id=q1.id,
                    law_id=law.id,
                    law_article_id=article.id,
                    article_no="758",
                    source="test",
                ),
                QuestionLawArticleRef(
                    question_id=q2.id,
                    law_id=law.id,
                    law_article_id=article.id,
                    article_no="758",
                    source="test",
                ),
            ]
        )
        db.commit()

        r = post_with_csrf(
            "/mock-exam",
            data={
                "question_ids": [str(q1.id), str(q2.id)],
                f"answer_{q1.id}": "A",
                f"answer_{q2.id}": "A",
            },
            fetch_path="/mock-exam",
        )
        assert r.status_code == 200
        assert "50.0" in r.text
        assert "未達及格" in r.text
        assert "不影響本次模擬考分數" in r.text

    def test_mock_exam_result_passes_at_60(self, client, db, post_with_csrf):
        from app.models import Question, QuestionType, Subject

        subject = Subject(code="civil_law_3", name="民法概要")
        db.add(subject)
        db.flush()
        questions = []
        for idx in range(5):
            question = Question(
                subject_id=subject.id,
                type=QuestionType.CHOICE,
                body=f"Q{idx + 1}",
                options=[{"key": "A", "text": "1"}, {"key": "B", "text": "2"}],
                answer="A",
            )
            questions.append(question)
        db.add_all(questions)
        db.commit()

        data = {"question_ids": [str(question.id) for question in questions]}
        for idx, question in enumerate(questions):
            data[f"answer_{question.id}"] = "A" if idx < 3 else "B"

        r = post_with_csrf("/mock-exam", data=data, fetch_path="/mock-exam")
        assert r.status_code == 200
        assert "60.0" in r.text
        assert "及格" in r.text


class TestWrong:
    def test_wrong_page_loads(self, client, seeded_db):
        r = client.get("/wrong")
        assert r.status_code == 200

    def test_wrong_page_shows_wrong_after_attempts(self, client, seeded_db):
        qid = seeded_db["question"].id
        for _ in range(2):
            client.post(
                "/api/choice/submit",
                json={"question_id": qid, "user_answer": "A"},
            )
        r = client.get("/wrong")
        assert r.status_code == 200
        assert "民法" in r.text or "House Agent" in r.text

    def test_wrong_page_prefers_structured_law_refs(self, client, db, seeded_db):
        qid = seeded_db["question"].id
        law = seeded_db["law"]
        article = seeded_db["law_article"]
        db.add(
            QuestionLawArticleRef(
                question_id=qid,
                law_id=law.id,
                law_article_id=article.id,
                article_no=article.article_no,
                source="test",
            )
        )
        db.commit()
        client.post(
            "/api/choice/submit",
            json={"question_id": qid, "user_answer": "A"},
        )
        r = client.get("/wrong")
        assert r.status_code == 200
        assert f"{law.name} 第{article.article_no}條" in r.text
        assert "權重" in r.text


class TestLaws:
    def test_laws_page_loads(self, client, seeded_db):
        r = client.get("/laws")
        assert r.status_code == 200
        assert "出題" in r.text

    def test_laws_page_accepts_subject_filter(self, client, seeded_db):
        r = client.get(f"/laws?subject_id={seeded_db['subject'].id}")
        assert r.status_code == 200
        assert "篩選科目" in r.text

    def test_laws_page_hides_admin_controls_from_normal_user(self, client, seeded_db):
        r = client.get("/laws")
        assert r.status_code == 200
        assert "更新法條" not in r.text
        assert "執行稽核" not in r.text
        assert "/admin/laws/refresh" not in r.text
        assert "/admin/laws/audit" not in r.text

    def test_law_detail_shows_linked_questions(self, client, db, seeded_db):
        qid = seeded_db["question"].id
        law = seeded_db["law"]
        article = seeded_db["law_article"]
        db.add(
            QuestionLawArticleRef(
                question_id=qid,
                law_id=law.id,
                law_article_id=article.id,
                article_no=article.article_no,
                source="test",
            )
        )
        db.commit()
        r = client.get(f"/laws/{law.id}")
        assert r.status_code == 200
        assert "相關題目" in r.text
        assert "學習權重" in r.text

    def test_law_detail_not_found(self, client, seeded_db):
        r = client.get("/laws/99999")
        assert r.status_code == 404

    def test_law_detail_shows_raw_law_ref_linked_questions(self, client, db, seeded_db):
        q = seeded_db["question"]
        q.source = "moex:2024_113190:subject:1:choice:1"
        q.law_refs = [seeded_db["law"].name]
        db.commit()

        r = client.get(f"/laws/{seeded_db['law'].id}")
        assert r.status_code == 200
        assert q.body[:8] in r.text


class TestExamPapers:
    @staticmethod
    def _write_manifest(root: Path, bundle_id: str, year: int, subject: str, category: str = "專技普考_不動產經紀人"):
        bundle = root / bundle_id
        bundle.mkdir(parents=True)
        (bundle / "cat_001_file_01.pdf").write_bytes(b"%PDF-1.4\n")
        manifest = {
            "year": year,
            "exam_code": bundle_id.split("_", 1)[1],
            "exam_name": f"{year}年普通考試不動產經紀人",
            "exam_title": f"{year}年普通考試不動產經紀人",
            "stats": "共 1 考試 5 科目",
            "overall_links": [],
            "items": [
                {
                    "category": category,
                    "subject": subject,
                    "files": [
                        {
                            "kind": "試題",
                            "href": f"wHandExamQandA_File.ashx?t=Q&code={bundle_id}",
                            "path": f"data\\raw\\exam_papers\\moex\\{bundle_id}\\cat_001_file_01.pdf",
                        }
                    ],
                }
            ],
        }
        (bundle / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    def test_exam_papers_page_loads(self, client, monkeypatch, tmp_path):
        from app.services import exam_papers

        self._write_manifest(tmp_path, "2024_113190", 2024, "民法概要")
        monkeypatch.setattr(exam_papers, "RAW_DIR", tmp_path)

        r = client.get("/exam-papers")
        assert r.status_code == 200
        assert "歷屆試題" in r.text
        assert "2024年普通考試不動產經紀人" in r.text
        assert "民法概要" in r.text

    def test_exam_papers_page_filters_by_query(self, client, monkeypatch, tmp_path):
        from app.services import exam_papers

        self._write_manifest(tmp_path, "2024_113190", 2024, "民法概要")
        self._write_manifest(tmp_path, "2023_112190", 2023, "不動產估價概要")
        monkeypatch.setattr(exam_papers, "RAW_DIR", tmp_path)

        r = client.get("/exam-papers?q=民法")
        assert r.status_code == 200
        assert "民法概要" in r.text
        assert "不動產估價概要" not in r.text

    def test_exam_papers_file_downloads(self, client, monkeypatch, tmp_path):
        from app.services import exam_papers

        bundle = tmp_path / "2024_113190"
        bundle.mkdir(parents=True)
        pdf_path = bundle / "cat_001_file_01.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\nhello")
        monkeypatch.setattr(exam_papers, "RAW_DIR", tmp_path)

        r = client.get("/exam-papers/files/2024_113190/cat_001_file_01.pdf")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF-1.4")

    def test_exam_paper_subject_page_shows_imported_questions(self, client, db, seeded_db):
        paper = ExamPaper(
            bundle_id="2024_113190",
            year=2024,
            roc_year=113,
            exam_code="113190",
            exam_name="113年普通考試不動產經紀人",
            exam_title="113年普通考試不動產經紀人",
            stats="共 1 考試 5 科目",
            source_dir="data/raw/exam_papers/moex/2024_113190",
        )
        db.add(paper)
        db.flush()
        subject_row = ExamPaperSubject(
            exam_paper_id=paper.id,
            category="專技普考_不動產經紀人",
            subject="民法概要",
            sort_order=1,
        )
        db.add(subject_row)
        seeded_db["question"].source = "moex:2024_113190:subject:1:choice:1"
        db.commit()

        r = client.get("/exam-papers/2024_113190/subjects/1")
        assert r.status_code == 200
        assert "民法概要" in r.text
        assert seeded_db["question"].body[:8] in r.text


class TestStats:
    def test_stats_endpoint(self, client, seeded_db):
        r = client.get("/api/stats")
        assert r.status_code == 200
        data = r.json()
        assert "coverage" in data
        assert isinstance(data["coverage"], list)

    def test_chapters_endpoint(self, client, seeded_db):
        subj_id = seeded_db["subject"].id
        r = client.get(f"/api/chapters?subject_id={subj_id}")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1

    def test_stats_are_user_isolated(self, client, db, seeded_db, post_with_csrf):
        from app.models import User
        from app.services.auth import hash_password

        alice = User(username="alice", display_name="Alice", password_hash=hash_password("pass1234"))
        bob = User(username="bob", display_name="Bob", password_hash=hash_password("pass1234"))
        db.add_all([alice, bob])
        db.commit()

        post_with_csrf("/login", data={"username": "alice", "password": "pass1234"})
        client.post("/api/choice/submit", json={"question_id": seeded_db["question"].id, "user_answer": "A"})
        data = client.get("/api/stats").json()
        assert data["coverage"][0]["seen"] == 1

        post_with_csrf("/logout", fetch_path="/")
        post_with_csrf("/login", data={"username": "bob", "password": "pass1234"})
        data = client.get("/api/stats").json()
        assert data["coverage"][0]["seen"] == 0


class TestAdmin:
    def test_admin_requires_admin_role(self, client, seeded_db):
        r = client.get("/admin")
        assert r.status_code == 403

    def test_admin_post_requires_csrf(self, client, db):
        from app.models import User
        from app.services.auth import hash_password

        admin = User(username="admin", display_name="Administrator", password_hash=hash_password("admin1234"), is_admin=True)
        user = User(username="alice", display_name="Alice", password_hash=hash_password("pass1234"), is_admin=False)
        db.add_all([admin, user])
        db.commit()

        client.get("/login")
        client.post("/login", data={"username": "admin", "password": "admin1234", "csrf_token": client.cookies.get("house_agent_csrf_token")})
        r = client.post(f"/admin/users/{user.id}/toggle-status", data={})
        assert r.status_code == 403

    def test_admin_dashboard_loads_for_admin(self, client, db, seeded_db, post_with_csrf):
        from app.models import User
        from app.services.auth import hash_password

        admin = User(username="admin", display_name="Administrator", password_hash=hash_password("admin1234"), is_admin=True)
        db.add(admin)
        db.commit()

        post_with_csrf("/login", data={"username": "admin", "password": "admin1234"})
        r = client.get("/admin")
        assert r.status_code == 200
        assert "管理後台" in r.text
        assert "法條維護" in r.text
        assert "管理使用者" in r.text

    def test_admin_users_page_loads_for_admin(self, client, db, seeded_db, post_with_csrf):
        from app.models import User, UserIdentity
        from app.services.auth import hash_password

        admin = User(username="admin", display_name="Administrator", password_hash=hash_password("admin1234"), is_admin=True)
        user = User(username="alice", display_name="Alice", password_hash=hash_password("pass1234"), is_admin=False)
        db.add_all([admin, user])
        db.flush()
        db.add(UserIdentity(user_id=user.id, provider="google", provider_user_id="google-1", email="alice@example.com"))
        db.commit()

        post_with_csrf("/login", data={"username": "admin", "password": "admin1234"})
        r = client.get("/admin/users")
        assert r.status_code == 200
        assert "使用者管理" in r.text
        assert "alice" in r.text
        assert "google" in r.text
        assert "mixed" in r.text

    def test_admin_users_page_shows_attempt_count_last_activity_and_auth_mode(self, client, db, seeded_db, post_with_csrf):
        from app.models import Attempt, User, UserIdentity
        from app.services.auth import LOGIN_POLICY_OAUTH_ONLY, hash_password

        admin = User(username="admin", display_name="Administrator", password_hash=hash_password("admin1234"), is_admin=True)
        mixed_user = User(username="alice", display_name="Alice", password_hash=hash_password("pass1234"), is_admin=False)
        oauth_user = User(username="bob", display_name="Bob", password_hash="", login_policy=LOGIN_POLICY_OAUTH_ONLY, is_admin=False)
        db.add_all([admin, mixed_user, oauth_user])
        db.flush()
        db.add_all(
            [
                UserIdentity(user_id=mixed_user.id, provider="google", provider_user_id="google-1", email="alice@example.com"),
                UserIdentity(user_id=oauth_user.id, provider="github", provider_user_id="github-1", email="bob@example.com"),
            ]
        )
        db.add(
            Attempt(
                user_id=mixed_user.id,
                question_id=seeded_db["question"].id,
                user_answer="A",
                correct=False,
            )
        )
        db.commit()

        post_with_csrf("/login", data={"username": "admin", "password": "admin1234"})
        r = client.get("/admin/users")
        assert r.status_code == 200
        assert "mixed" in r.text
        assert "oauth-only" in r.text
        assert "github" in r.text
        assert "尚無活動" in r.text
        assert "oauth_only" in r.text

    def test_admin_users_page_supports_filters_and_search(self, client, db, seeded_db, post_with_csrf):
        from app.models import User, UserIdentity
        from app.services.auth import hash_password

        admin = User(username="admin", display_name="Administrator", password_hash=hash_password("admin1234"), is_admin=True)
        alice = User(username="alice", display_name="Alice", password_hash=hash_password("pass1234"), is_admin=False)
        bob = User(username="bob", display_name="Bob", password_hash="", is_admin=False)
        db.add_all([admin, alice, bob])
        db.flush()
        db.add_all(
            [
                UserIdentity(user_id=alice.id, provider="google", provider_user_id="google-1", email="alice@example.com"),
                UserIdentity(user_id=bob.id, provider="github", provider_user_id="github-1", email="bob@example.com"),
            ]
        )
        db.commit()

        post_with_csrf("/login", data={"username": "admin", "password": "admin1234"})
        r = client.get("/admin/users?q=bob&provider=github")
        assert r.status_code == 200
        assert "bob@example.com" in r.text
        assert "alice@example.com" not in r.text

    def test_admin_users_page_supports_pagination(self, client, db, seeded_db, post_with_csrf):
        from app.models import User
        from app.services.auth import hash_password

        admin = User(username="admin", display_name="Administrator", password_hash=hash_password("admin1234"), is_admin=True)
        db.add(admin)
        db.flush()
        for idx in range(12):
            db.add(User(username=f"user{idx}", display_name=f"User {idx}", password_hash=hash_password("pass1234"), is_admin=False))
        db.commit()

        post_with_csrf("/login", data={"username": "admin", "password": "admin1234"})
        r1 = client.get("/admin/users?page=1")
        r2 = client.get("/admin/users?page=2")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert "第 1 / 2 頁" in r1.text
        assert "第 2 / 2 頁" in r2.text

    def test_admin_actions_write_audit_logs(self, client, db, seeded_db, post_with_csrf):
        from app.models import User
        from app.services.auth import USER_STATUS_ACTIVE, hash_password

        admin = User(username="admin", display_name="Administrator", password_hash=hash_password("admin1234"), status=USER_STATUS_ACTIVE, is_admin=True)
        user = User(username="alice", display_name="Alice", password_hash=hash_password("pass1234"), status=USER_STATUS_ACTIVE, is_admin=False)
        db.add_all([admin, user])
        db.commit()

        post_with_csrf("/login", data={"username": "admin", "password": "admin1234"})
        post_with_csrf(f"/admin/users/{user.id}/toggle-status", fetch_path="/admin/users", follow_redirects=False)
        log = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
        assert log is not None
        assert log.action == "toggle_status"
        assert log.details["before"] == "active"
        assert log.details["after"] == "disabled"

    def test_admin_audit_logs_page_loads_and_filters(self, client, db, seeded_db, post_with_csrf):
        from app.models import User
        from app.services.auth import USER_STATUS_ACTIVE, hash_password

        admin = User(username="admin", display_name="Administrator", password_hash=hash_password("admin1234"), status=USER_STATUS_ACTIVE, is_admin=True)
        user = User(username="alice", display_name="Alice", password_hash=hash_password("pass1234"), status=USER_STATUS_ACTIVE, is_admin=False)
        db.add_all([admin, user])
        db.commit()

        post_with_csrf("/login", data={"username": "admin", "password": "admin1234"})
        post_with_csrf(f"/admin/users/{user.id}/toggle-status", fetch_path="/admin/users", follow_redirects=False)
        post_with_csrf(f"/admin/users/{user.id}/toggle-login-policy", fetch_path="/admin/users", follow_redirects=False)

        r = client.get("/admin/audit-logs?action=toggle_status&q=Alice")
        assert r.status_code == 200
        assert "審計紀錄" in r.text
        assert "toggle_status" in r.text
        assert ">toggle_login_policy</td>" not in r.text

    def test_admin_audit_logs_page_supports_pagination(self, client, db, seeded_db, post_with_csrf):
        from app.models import User
        from app.services.auth import USER_STATUS_ACTIVE, hash_password

        admin = User(username="admin", display_name="Administrator", password_hash=hash_password("admin1234"), status=USER_STATUS_ACTIVE, is_admin=True)
        user = User(username="alice", display_name="Alice", password_hash=hash_password("pass1234"), status=USER_STATUS_ACTIVE, is_admin=False)
        db.add_all([admin, user])
        db.commit()

        for idx in range(25):
            db.add(
                AuditLog(
                    actor_user_id=admin.id,
                    target_user_id=user.id,
                    action="toggle_status",
                    details={"before": "active", "after": f"disabled_{idx}"},
                )
            )
        db.commit()

        post_with_csrf("/login", data={"username": "admin", "password": "admin1234"})
        r1 = client.get("/admin/audit-logs?page=1")
        r2 = client.get("/admin/audit-logs?page=2")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert "第 1 / 2 頁" in r1.text
        assert "第 2 / 2 頁" in r2.text

    def test_admin_can_toggle_user_status(self, client, db, seeded_db, post_with_csrf):
        from app.models import User
        from app.services.auth import USER_STATUS_ACTIVE, USER_STATUS_DISABLED, hash_password

        admin = User(username="admin", display_name="Administrator", password_hash=hash_password("admin1234"), status=USER_STATUS_ACTIVE, is_admin=True)
        user = User(username="alice", display_name="Alice", password_hash=hash_password("pass1234"), status=USER_STATUS_ACTIVE, is_admin=False)
        db.add_all([admin, user])
        db.commit()

        post_with_csrf("/login", data={"username": "admin", "password": "admin1234"})
        r = post_with_csrf(f"/admin/users/{user.id}/toggle-status", fetch_path="/admin/users", follow_redirects=False)
        db.refresh(user)
        assert r.status_code == 303
        assert user.status == USER_STATUS_DISABLED

    def test_cannot_disable_last_active_admin(self, client, db, seeded_db, post_with_csrf):
        from app.models import User
        from app.services.auth import USER_STATUS_ACTIVE, hash_password

        admin = User(username="admin", display_name="Administrator", password_hash=hash_password("admin1234"), status=USER_STATUS_ACTIVE, is_admin=True)
        db.add(admin)
        db.commit()

        post_with_csrf("/login", data={"username": "admin", "password": "admin1234"})
        r = post_with_csrf(f"/admin/users/{admin.id}/toggle-status", fetch_path="/admin/users", follow_redirects=False)
        assert r.status_code == 400

    def test_admin_can_toggle_login_policy(self, client, db, seeded_db, post_with_csrf):
        from app.models import User
        from app.services.auth import LOGIN_POLICY_LOCAL_OR_OAUTH, LOGIN_POLICY_OAUTH_ONLY, USER_STATUS_ACTIVE, hash_password

        admin = User(username="admin", display_name="Administrator", password_hash=hash_password("admin1234"), status=USER_STATUS_ACTIVE, login_policy=LOGIN_POLICY_LOCAL_OR_OAUTH, is_admin=True)
        user = User(username="alice", display_name="Alice", password_hash=hash_password("pass1234"), status=USER_STATUS_ACTIVE, login_policy=LOGIN_POLICY_LOCAL_OR_OAUTH, is_admin=False)
        db.add_all([admin, user])
        db.commit()

        post_with_csrf("/login", data={"username": "admin", "password": "admin1234"})
        r = post_with_csrf(f"/admin/users/{user.id}/toggle-login-policy", fetch_path="/admin/users", follow_redirects=False)
        db.refresh(user)
        assert r.status_code == 303
        assert user.login_policy == LOGIN_POLICY_OAUTH_ONLY

    def test_cannot_remove_local_login_from_last_active_admin(self, client, db, seeded_db, post_with_csrf):
        from app.models import User
        from app.services.auth import LOGIN_POLICY_LOCAL_OR_OAUTH, USER_STATUS_ACTIVE, hash_password

        admin = User(username="admin", display_name="Administrator", password_hash=hash_password("admin1234"), status=USER_STATUS_ACTIVE, login_policy=LOGIN_POLICY_LOCAL_OR_OAUTH, is_admin=True)
        db.add(admin)
        db.commit()

        post_with_csrf("/login", data={"username": "admin", "password": "admin1234"})
        r = post_with_csrf(f"/admin/users/{admin.id}/toggle-login-policy", fetch_path="/admin/users", follow_redirects=False)
        assert r.status_code == 400

    def test_admin_can_toggle_user_role(self, client, db, seeded_db, post_with_csrf):
        from app.models import User
        from app.services.auth import hash_password

        admin = User(username="admin", display_name="Administrator", password_hash=hash_password("admin1234"), is_admin=True)
        user = User(username="alice", display_name="Alice", password_hash=hash_password("pass1234"), is_admin=False)
        db.add_all([admin, user])
        db.commit()

        post_with_csrf("/login", data={"username": "admin", "password": "admin1234"})
        r = post_with_csrf(f"/admin/users/{user.id}/toggle-admin", fetch_path="/admin/users", follow_redirects=False)
        db.refresh(user)
        assert r.status_code == 303
        assert user.is_admin is True


class TestOAuth:
    def test_login_page_shows_google_entry_when_enabled(self, client, seeded_db, monkeypatch):
        import app.main as main_module

        monkeypatch.setattr(main_module, "google_oauth_enabled", lambda: True)
        monkeypatch.setattr(main_module, "github_oauth_enabled", lambda: False)
        r = client.get("/login")
        assert r.status_code == 200
        assert "使用 Google 登入" in r.text

    def test_login_page_shows_github_entry_when_enabled(self, client, seeded_db, monkeypatch):
        import app.main as main_module

        monkeypatch.setattr(main_module, "google_oauth_enabled", lambda: False)
        monkeypatch.setattr(main_module, "github_oauth_enabled", lambda: True)
        r = client.get("/login")
        assert r.status_code == 200
        assert "使用 GitHub 登入" in r.text

    def test_google_start_redirects_and_sets_state_cookie(self, client, monkeypatch):
        import app.main as main_module

        monkeypatch.setattr(
            main_module,
            "build_google_authorize_url",
            lambda request: ("https://accounts.google.com/o/oauth2/v2/auth?state=test-state", "test-state"),
        )
        r = client.get("/auth/google/start", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"].startswith("https://accounts.google.com/")
        assert "house_agent_oauth_state=test-state" in r.headers.get("set-cookie", "")

    def test_google_callback_creates_user_identity_and_logs_in(self, client, db, monkeypatch):
        import app.main as main_module

        monkeypatch.setattr(main_module, "validate_oauth_state", lambda request, state: None)
        monkeypatch.setattr(
            main_module,
            "exchange_google_code_for_profile",
            lambda request, code: {
                "sub": "google-sub-123",
                "email": "alice@example.com",
                "name": "Alice OAuth",
                "picture": "https://example.com/alice.png",
            },
        )
        client.cookies.set("house_agent_oauth_state", "state-ok")
        r = client.get("/auth/google/callback?code=abc&state=state-ok", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/"
        user = db.query(UserIdentity).filter(UserIdentity.provider == "google").first()
        assert user is not None
        assert user.email == "alice@example.com"
        assert user.user.display_name == "Alice OAuth"
        assert "house_agent_user_id=" in r.headers.get("set-cookie", "")

    def test_disabled_google_user_is_blocked_on_callback(self, client, db, monkeypatch):
        import app.main as main_module

        from app.models import User, UserIdentity
        from app.services.auth import USER_STATUS_DISABLED

        user = User(username="alice", display_name="Alice", password_hash="", status=USER_STATUS_DISABLED, is_admin=False)
        db.add(user)
        db.flush()
        db.add(UserIdentity(user_id=user.id, provider="google", provider_user_id="google-sub-123", email="alice@example.com"))
        db.commit()

        monkeypatch.setattr(main_module, "validate_oauth_state", lambda request, state: None)
        monkeypatch.setattr(
            main_module,
            "exchange_google_code_for_profile",
            lambda request, code: {
                "sub": "google-sub-123",
                "email": "alice@example.com",
                "name": "Alice OAuth",
                "picture": "https://example.com/alice.png",
            },
        )
        client.cookies.set("house_agent_oauth_state", "state-ok")
        r = client.get("/auth/google/callback?code=abc&state=state-ok", follow_redirects=False)
        assert r.status_code == 403

    def test_github_start_redirects_and_sets_state_cookie(self, client, monkeypatch):
        import app.main as main_module

        monkeypatch.setattr(
            main_module,
            "build_github_authorize_url",
            lambda request: ("https://github.com/login/oauth/authorize?state=gh-state", "gh-state"),
        )
        r = client.get("/auth/github/start", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"].startswith("https://github.com/login/oauth/authorize")
        assert "house_agent_oauth_state=gh-state" in r.headers.get("set-cookie", "")

    def test_github_callback_creates_user_identity_and_logs_in(self, client, db, monkeypatch):
        import app.main as main_module

        monkeypatch.setattr(main_module, "validate_oauth_state", lambda request, state: None)
        monkeypatch.setattr(
            main_module,
            "exchange_github_code_for_profile",
            lambda request, code: {
                "id": "github-user-99",
                "email": "dev@example.com",
                "name": "Dev User",
                "avatar_url": "https://example.com/dev.png",
                "login": "devuser",
            },
        )
        client.cookies.set("house_agent_oauth_state", "gh-ok")
        r = client.get("/auth/github/callback?code=abc&state=gh-ok", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/"
        identity = db.query(UserIdentity).filter(UserIdentity.provider == "github").first()
        assert identity is not None
        assert identity.email == "dev@example.com"
        assert identity.user.username == "dev@example.com"
        assert "house_agent_user_id=" in r.headers.get("set-cookie", "")

    def test_disabled_github_user_is_blocked_on_callback(self, client, db, monkeypatch):
        import app.main as main_module

        from app.models import User, UserIdentity
        from app.services.auth import USER_STATUS_DISABLED

        user = User(username="dev", display_name="Dev", password_hash="", status=USER_STATUS_DISABLED, is_admin=False)
        db.add(user)
        db.flush()
        db.add(UserIdentity(user_id=user.id, provider="github", provider_user_id="github-user-99", email="dev@example.com"))
        db.commit()

        monkeypatch.setattr(main_module, "validate_oauth_state", lambda request, state: None)
        monkeypatch.setattr(
            main_module,
            "exchange_github_code_for_profile",
            lambda request, code: {
                "id": "github-user-99",
                "email": "dev@example.com",
                "name": "Dev User",
                "avatar_url": "https://example.com/dev.png",
                "login": "devuser",
            },
        )
        client.cookies.set("house_agent_oauth_state", "gh-ok")
        r = client.get("/auth/github/callback?code=abc&state=gh-ok", follow_redirects=False)
        assert r.status_code == 403

    def test_login_rate_limit_blocks_repeated_attempts(self, client, post_with_csrf):
        for _ in range(5):
            r = post_with_csrf("/login", data={"username": "alice", "password": "wrong"}, follow_redirects=False)
            assert r.status_code == 303
        blocked = post_with_csrf("/login", data={"username": "alice", "password": "wrong"}, follow_redirects=False)
        assert blocked.status_code == 429
        assert blocked.headers["retry-after"].isdigit()

    def test_oauth_callback_rate_limit_blocks_repeated_requests(self, client, monkeypatch):
        import app.main as main_module

        monkeypatch.setattr(main_module, "validate_oauth_state", lambda request, state: None)
        monkeypatch.setattr(
            main_module,
            "exchange_google_code_for_profile",
            lambda request, code: {
                "sub": "google-sub-123",
                "email": "alice@example.com",
                "name": "Alice OAuth",
                "picture": "https://example.com/alice.png",
            },
        )
        client.cookies.set("house_agent_oauth_state", "state-ok")
        for _ in range(10):
            r = client.get("/auth/google/callback?code=abc&state=state-ok", follow_redirects=False)
            assert r.status_code == 303
        blocked = client.get("/auth/google/callback?code=abc&state=state-ok", follow_redirects=False)
        assert blocked.status_code == 429

    def test_security_headers_are_applied(self, client):
        r = client.get("/login")
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"]

    def test_secure_cookie_policy_uses_https_or_override(self, client, monkeypatch):
        monkeypatch.setenv("HOUSE_AGENT_COOKIE_SECURE", "true")
        r = client.get("/login")
        set_cookie = r.headers.get("set-cookie", "").lower()
        assert "house_agent_csrf_token=" in set_cookie
        assert "secure" in set_cookie
        assert "samesite=lax" in set_cookie


class TestPasswordHashing:
    def test_login_requires_csrf(self, client):
        r = client.post("/login", data={"username": "alice", "password": "pass1234"})
        assert r.status_code == 403

    def test_register_stores_bcrypt_hash(self, client, db, post_with_csrf):
        from app.models import User

        post_with_csrf("/register", data={"username": "alice", "display_name": "Alice", "password": "pass1234"})
        user = db.query(User).filter(User.username == "alice").first()
        assert user is not None
        assert user.password_hash.startswith("$2")

    def test_legacy_sha256_hash_is_rehashed_on_login(self, client, db, post_with_csrf):
        import hashlib

        from app.models import User

        legacy = User(
            username="legacy",
            display_name="Legacy",
            password_hash=hashlib.sha256("pass1234".encode("utf-8")).hexdigest(),
            is_admin=False,
        )
        db.add(legacy)
        db.commit()

        r = post_with_csrf("/login", data={"username": "legacy", "password": "pass1234"}, follow_redirects=False)
        db.refresh(legacy)
        assert r.status_code == 303
        assert legacy.password_hash.startswith("$2")

    def test_disabled_local_user_cannot_log_in(self, client, db, post_with_csrf):
        from app.models import User
        from app.services.auth import USER_STATUS_DISABLED, hash_password

        user = User(
            username="disabled_user",
            display_name="Disabled",
            password_hash=hash_password("pass1234"),
            status=USER_STATUS_DISABLED,
            is_admin=False,
        )
        db.add(user)
        db.commit()

        r = post_with_csrf("/login", data={"username": "disabled_user", "password": "pass1234"}, follow_redirects=False)
        assert r.status_code == 303
        assert "/login?error=" in r.headers["location"]

    def test_oauth_only_user_cannot_log_in_locally(self, client, db, post_with_csrf):
        from app.models import User
        from app.services.auth import LOGIN_POLICY_OAUTH_ONLY, USER_STATUS_ACTIVE, hash_password

        user = User(
            username="oauth_only_user",
            display_name="OAuth Only",
            password_hash=hash_password("pass1234"),
            status=USER_STATUS_ACTIVE,
            login_policy=LOGIN_POLICY_OAUTH_ONLY,
            is_admin=False,
        )
        db.add(user)
        db.commit()

        r = post_with_csrf("/login", data={"username": "oauth_only_user", "password": "pass1234"}, follow_redirects=False)
        assert r.status_code == 303
        assert "/login?error=" in r.headers["location"]
