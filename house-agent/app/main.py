"""FastAPI app entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.db import get_session, init_db
from app.law_catalog import LAW_CATALOG_BY_NAME
from app.models import AuditLog, Attempt, Chapter, ExamPaper, Law, Question, QuestionType, Subject, User, UserIdentity
from app.schemas import ChoiceSubmit, EssaySubmit, GradingOut
from app.services import exam_papers, grading, mock_exam, quiz
from app.services.admin_laws import audit_laws, refresh_all_laws
from app.services.auth import (
    LOGIN_POLICY_LOCAL_OR_OAUTH,
    LOGIN_POLICY_OAUTH_ONLY,
    USER_STATUS_ACTIVE,
    USER_STATUS_DISABLED,
    authenticate_user,
    clear_login_cookie,
    create_user,
    get_current_user,
    list_users,
    require_admin_user,
    set_login_cookie,
)
from app.services.law_links import (
    law_frequency_stats,
    linked_law_refs,
    linked_questions_for_law,
    question_importance_details,
    serialize_question_law_refs,
)
from app.services.csrf import get_or_create_csrf_token, set_csrf_cookie, validate_csrf
from app.services.oauth import (
    GITHUB_PROVIDER,
    GOOGLE_PROVIDER,
    build_github_authorize_url,
    build_google_authorize_url,
    clear_oauth_state_cookie,
    exchange_github_code_for_profile,
    exchange_google_code_for_profile,
    get_or_create_oauth_user,
    github_oauth_enabled,
    google_oauth_enabled,
    set_oauth_state_cookie,
    validate_oauth_state,
)
from app.services.rate_limit import enforce_rate_limit
from app.services.security import apply_security_headers

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
ADMIN_USERS_PAGE_SIZE = 10
ADMIN_AUDIT_LOGS_PAGE_SIZE = 20
LOGIN_RATE_LIMIT = (5, 60)
OAUTH_START_RATE_LIMIT = (10, 300)
OAUTH_CALLBACK_RATE_LIMIT = (10, 300)


def _render(request: Request, template_name: str, context: dict, current_user) -> HTMLResponse:
    payload = dict(context)
    payload["current_user"] = current_user
    payload["csrf_token"] = get_or_create_csrf_token(request)
    response = templates.TemplateResponse(request, template_name, payload)
    set_csrf_cookie(response, payload["csrf_token"], request)
    return response


def _admin_user_rows(db: Session, users: list[User]) -> list[dict]:
    rows: list[dict] = []
    if not users:
        return rows
    user_ids = [user.id for user in users]
    stats_rows = db.execute(
        select(
            User.id,
            func.count(Attempt.id),
            func.max(Attempt.created_at),
        )
        .outerjoin(Attempt, Attempt.user_id == User.id)
        .where(User.id.in_(user_ids))
        .group_by(User.id)
    ).all()
    stats_by_user_id = {
        int(user_id): {"attempt_count": int(attempt_count or 0), "last_activity_at": last_activity_at}
        for user_id, attempt_count, last_activity_at in stats_rows
    }
    for user in users:
        provider_labels = sorted({identity.provider for identity in user.identities})
        identity_details = [
            {
                "provider": identity.provider,
                "email": identity.email,
                "avatar_url": identity.avatar_url,
                "provider_user_id": identity.provider_user_id,
            }
            for identity in sorted(user.identities, key=lambda item: (item.provider, item.id))
        ]
        has_local = bool(user.password_hash)
        if has_local:
            provider_labels.insert(0, "local")
        if has_local and provider_labels[1:]:
            auth_mode = "mixed"
        elif has_local:
            auth_mode = "local-only"
        elif provider_labels:
            auth_mode = "oauth-only"
        else:
            auth_mode = "unknown"
        rows.append(
            {
                "user": user,
                "providers": provider_labels,
                "identity_details": identity_details,
                "auth_mode": auth_mode,
                "login_policy": str(user.login_policy or LOGIN_POLICY_LOCAL_OR_OAUTH),
                "status": str(user.status or USER_STATUS_ACTIVE),
                **stats_by_user_id.get(user.id, {"attempt_count": 0, "last_activity_at": None}),
            }
        )
    return rows


def _admin_user_query(
    db: Session,
    *,
    q: str = "",
    status: str = "",
    role: str = "",
    provider: str = "",
):
    query = db.query(User).outerjoin(UserIdentity)
    keyword = q.strip()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(
                User.username.ilike(like),
                User.display_name.ilike(like),
                UserIdentity.email.ilike(like),
                UserIdentity.provider_user_id.ilike(like),
            )
        )
    if status in {USER_STATUS_ACTIVE, USER_STATUS_DISABLED}:
        query = query.filter(User.status == status)
    if role == "admin":
        query = query.filter(User.is_admin == True)  # noqa: E712
    elif role == "user":
        query = query.filter(User.is_admin == False)  # noqa: E712
    if provider == "local":
        query = query.filter(User.password_hash != "")
    elif provider in {"google", "github"}:
        query = query.filter(UserIdentity.provider == provider)
    return query.distinct()


def _recent_audit_logs(db: Session, limit: int = 20) -> list[dict]:
    rows = db.query(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit).all()
    return [
        {
            "log": log,
            "actor_name": log.actor_user.display_name if log.actor_user is not None else "System",
            "target_name": log.target_user.display_name if log.target_user is not None else "-",
        }
        for log in rows
    ]


def _audit_log_query(
    db: Session,
    *,
    q: str = "",
    action: str = "",
):
    actor_user = aliased(User)
    target_user = aliased(User)
    query = (
        db.query(AuditLog)
        .outerjoin(actor_user, AuditLog.actor_user_id == actor_user.id)
        .outerjoin(target_user, AuditLog.target_user_id == target_user.id)
    )
    keyword = q.strip()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(
                actor_user.username.ilike(like),
                actor_user.display_name.ilike(like),
                target_user.username.ilike(like),
                target_user.display_name.ilike(like),
                AuditLog.action.ilike(like),
            )
        )
    if action:
        query = query.filter(AuditLog.action == action)
    return query.distinct()


def _paginate_audit_logs(query, *, page: int, page_size: int) -> tuple[list[AuditLog], int, int, int]:
    total = int(query.count())
    total_pages = max(1, (total + page_size - 1) // page_size)
    safe_page = min(max(page, 1), total_pages)
    logs = (
        query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((safe_page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return logs, safe_page, total_pages, total


def _write_audit_log(
    db: Session,
    *,
    actor_user: User | None,
    target_user: User | None,
    action: str,
    details: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor_user.id if actor_user is not None else None,
            target_user_id=target_user.id if target_user is not None else None,
            action=action,
            details=details or {},
        )
    )


def _paginate_user_ids(query, *, page: int, page_size: int) -> tuple[list[int], int, int]:
    total = int(query.count())
    total_pages = max(1, (total + page_size - 1) // page_size)
    safe_page = min(max(page, 1), total_pages)
    ids = [
        int(user_id)
        for (user_id,) in query.with_entities(User.id)
        .order_by(User.created_at.desc(), User.id.desc())
        .offset((safe_page - 1) * page_size)
        .limit(page_size)
        .all()
    ]
    return ids, safe_page, total_pages


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="House Agent", description="不動產經紀人考試教學、複習與模擬系統", lifespan=lifespan)

_static = BASE_DIR / "static"
_static.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static)), name="static")


@app.middleware("http")
async def harden_response(request: Request, call_next):
    response = await call_next(request)
    return apply_security_headers(response)


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_session)):
    current_user = get_current_user(db, request)
    cov = quiz.coverage_by_subject(db, user_id=current_user.id)
    weekly = quiz.accuracy_buckets(db, days=90, user_id=current_user.id)
    monthly = quiz.accuracy_buckets(db, days=365, user_id=current_user.id)
    return _render(
        request,
        "index.html",
        {"coverage": cov, "weekly": weekly, "monthly": monthly},
        current_user,
    )


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_session)):
    current_user = get_current_user(db, request)
    return _render(
        request,
        "login.html",
        {
            "users": list_users(db),
            "error": request.query_params.get("error", ""),
            "github_oauth_enabled": github_oauth_enabled(),
            "google_oauth_enabled": google_oauth_enabled(),
        },
        current_user,
    )


@app.post("/login")
async def login_submit(request: Request, db: Session = Depends(get_session)):
    await validate_csrf(request)
    form = await request.form()
    username = str(form.get("username", "") or "")
    password = str(form.get("password", "") or "")
    enforce_rate_limit(
        request,
        scope="login",
        limit=LOGIN_RATE_LIMIT[0],
        window_seconds=LOGIN_RATE_LIMIT[1],
        subject=username,
    )
    user = authenticate_user(db, username=username, password=password)
    if user is None:
        return RedirectResponse(url="/login?error=帳號或密碼錯誤", status_code=303)
    response = RedirectResponse(url="/", status_code=303)
    set_login_cookie(response, user, request)
    return response


@app.get("/auth/google/start")
def google_oauth_start(request: Request):
    enforce_rate_limit(
        request,
        scope="oauth_google_start",
        limit=OAUTH_START_RATE_LIMIT[0],
        window_seconds=OAUTH_START_RATE_LIMIT[1],
    )
    authorize_url, state = build_google_authorize_url(request)
    response = RedirectResponse(url=authorize_url, status_code=303)
    set_oauth_state_cookie(response, state, request)
    return response


@app.get("/auth/google/callback")
def google_oauth_callback(request: Request, code: str = "", state: str = "", db: Session = Depends(get_session)):
    enforce_rate_limit(
        request,
        scope="oauth_google_callback",
        limit=OAUTH_CALLBACK_RATE_LIMIT[0],
        window_seconds=OAUTH_CALLBACK_RATE_LIMIT[1],
    )
    validate_oauth_state(request, state)
    profile = exchange_google_code_for_profile(request, code)
    user = get_or_create_oauth_user(
        db,
        provider=GOOGLE_PROVIDER,
        provider_user_id=str(profile.get("sub") or ""),
        email=str(profile.get("email") or "").strip() or None,
        display_name=str(profile.get("name") or "").strip() or None,
        avatar_url=str(profile.get("picture") or "").strip() or None,
    )
    response = RedirectResponse(url="/", status_code=303)
    clear_oauth_state_cookie(response, request)
    set_login_cookie(response, user, request)
    return response


@app.get("/auth/github/start")
def github_oauth_start(request: Request):
    enforce_rate_limit(
        request,
        scope="oauth_github_start",
        limit=OAUTH_START_RATE_LIMIT[0],
        window_seconds=OAUTH_START_RATE_LIMIT[1],
    )
    authorize_url, state = build_github_authorize_url(request)
    response = RedirectResponse(url=authorize_url, status_code=303)
    set_oauth_state_cookie(response, state, request)
    return response


@app.get("/auth/github/callback")
def github_oauth_callback(request: Request, code: str = "", state: str = "", db: Session = Depends(get_session)):
    enforce_rate_limit(
        request,
        scope="oauth_github_callback",
        limit=OAUTH_CALLBACK_RATE_LIMIT[0],
        window_seconds=OAUTH_CALLBACK_RATE_LIMIT[1],
    )
    validate_oauth_state(request, state)
    profile = exchange_github_code_for_profile(request, code)
    user = get_or_create_oauth_user(
        db,
        provider=GITHUB_PROVIDER,
        provider_user_id=str(profile.get("id") or ""),
        email=str(profile.get("email") or "").strip() or None,
        display_name=str(profile.get("name") or "").strip() or None,
        avatar_url=str(profile.get("avatar_url") or "").strip() or None,
        fallback_username=str(profile.get("login") or "").strip() or None,
    )
    response = RedirectResponse(url="/", status_code=303)
    clear_oauth_state_cookie(response, request)
    set_login_cookie(response, user, request)
    return response


@app.post("/register")
async def register_submit(request: Request, db: Session = Depends(get_session)):
    await validate_csrf(request)
    form = await request.form()
    username = str(form.get("username", "") or "")
    display_name = str(form.get("display_name", "") or "")
    password = str(form.get("password", "") or "")
    user = create_user(db, username=username, display_name=display_name, password=password)
    response = RedirectResponse(url="/", status_code=303)
    set_login_cookie(response, user, request)
    return response


@app.post("/logout")
async def logout_submit(request: Request):
    await validate_csrf(request)
    response = RedirectResponse(url="/", status_code=303)
    clear_login_cookie(response, request)
    return response


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_session)):
    current_user = require_admin_user(db, request)
    audit = audit_laws(db)
    users = list_users(db)
    return _render(request, "admin_dashboard.html", {"audit": audit, "users": users}, current_user)


@app.post("/admin/laws/refresh")
async def admin_refresh_laws(request: Request, db: Session = Depends(get_session)):
    await validate_csrf(request)
    require_admin_user(db, request)
    refresh_all_laws()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/laws/audit")
async def admin_audit_laws(request: Request, db: Session = Depends(get_session)):
    await validate_csrf(request)
    require_admin_user(db, request)
    audit_laws(db)
    return RedirectResponse(url="/admin", status_code=303)


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users_page(
    request: Request,
    q: str = "",
    status: str = "",
    role: str = "",
    provider: str = "",
    page: int = 1,
    db: Session = Depends(get_session),
):
    current_user = require_admin_user(db, request)
    query = _admin_user_query(db, q=q, status=status, role=role, provider=provider)
    user_ids, safe_page, total_pages = _paginate_user_ids(query, page=page, page_size=ADMIN_USERS_PAGE_SIZE)
    users = db.query(User).filter(User.id.in_(user_ids)).all() if user_ids else []
    by_id = {user.id: user for user in users}
    ordered_users = [by_id[user_id] for user_id in user_ids if user_id in by_id]
    return _render(
        request,
        "admin_users.html",
        {
            "user_rows": _admin_user_rows(db, ordered_users),
            "audit_rows": _recent_audit_logs(db),
            "filters": {"q": q, "status": status, "role": role, "provider": provider},
            "page": safe_page,
            "total_pages": total_pages,
            "total_users": int(query.count()),
        },
        current_user,
    )


@app.get("/admin/audit-logs", response_class=HTMLResponse)
def admin_audit_logs_page(
    request: Request,
    q: str = "",
    action: str = "",
    page: int = 1,
    db: Session = Depends(get_session),
):
    current_user = require_admin_user(db, request)
    query = _audit_log_query(db, q=q, action=action)
    logs, safe_page, total_pages, total_logs = _paginate_audit_logs(
        query, page=page, page_size=ADMIN_AUDIT_LOGS_PAGE_SIZE
    )
    audit_rows = [
        {
            "log": log,
            "actor_name": log.actor_user.display_name if log.actor_user is not None else "System",
            "target_name": log.target_user.display_name if log.target_user is not None else "-",
        }
        for log in logs
    ]
    return _render(
        request,
        "admin_audit_logs.html",
        {
            "audit_rows": audit_rows,
            "filters": {"q": q, "action": action},
            "page": safe_page,
            "total_pages": total_pages,
            "total_logs": total_logs,
        },
        current_user,
    )


@app.post("/admin/users/{user_id}/toggle-admin")
async def admin_toggle_user_admin(user_id: int, request: Request, db: Session = Depends(get_session)):
    await validate_csrf(request)
    current_user = require_admin_user(db, request)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "user not found")
    if user.username == "guest":
        raise HTTPException(400, "guest cannot be promoted")
    before = bool(user.is_admin)
    user.is_admin = not bool(user.is_admin)
    _write_audit_log(
        db,
        actor_user=current_user,
        target_user=user,
        action="toggle_admin",
        details={"before": before, "after": bool(user.is_admin)},
    )
    db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)


@app.post("/admin/users/{user_id}/toggle-status")
async def admin_toggle_user_status(user_id: int, request: Request, db: Session = Depends(get_session)):
    await validate_csrf(request)
    current_user = require_admin_user(db, request)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "user not found")
    if user.username == "guest":
        raise HTTPException(400, "guest cannot be disabled")
    next_status = USER_STATUS_DISABLED if str(user.status or USER_STATUS_ACTIVE) == USER_STATUS_ACTIVE else USER_STATUS_ACTIVE
    if next_status == USER_STATUS_DISABLED and user.is_admin:
        active_admin_count = db.query(User).filter(User.is_admin == True, User.status == USER_STATUS_ACTIVE).count()  # noqa: E712
        if active_admin_count <= 1:
            raise HTTPException(400, "cannot disable last active admin")
    if user.id == current_user.id and next_status == USER_STATUS_DISABLED:
        raise HTTPException(400, "cannot disable current admin")
    before = str(user.status or USER_STATUS_ACTIVE)
    user.status = next_status
    _write_audit_log(
        db,
        actor_user=current_user,
        target_user=user,
        action="toggle_status",
        details={"before": before, "after": next_status},
    )
    db.commit()
    response = RedirectResponse(url="/admin/users", status_code=303)
    if user.id == current_user.id and next_status != USER_STATUS_ACTIVE:
        clear_login_cookie(response, request)
    return response


@app.post("/admin/users/{user_id}/toggle-login-policy")
async def admin_toggle_user_login_policy(user_id: int, request: Request, db: Session = Depends(get_session)):
    await validate_csrf(request)
    current_user = require_admin_user(db, request)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "user not found")
    if user.username == "guest":
        raise HTTPException(400, "guest policy cannot be changed")
    next_policy = (
        LOGIN_POLICY_OAUTH_ONLY
        if str(user.login_policy or LOGIN_POLICY_LOCAL_OR_OAUTH) == LOGIN_POLICY_LOCAL_OR_OAUTH
        else LOGIN_POLICY_LOCAL_OR_OAUTH
    )
    if user.is_admin and next_policy == LOGIN_POLICY_OAUTH_ONLY:
        active_local_admin_count = (
            db.query(User)
            .filter(
                User.is_admin == True,  # noqa: E712
                User.status == USER_STATUS_ACTIVE,
                User.login_policy == LOGIN_POLICY_LOCAL_OR_OAUTH,
            )
            .count()
        )
        if active_local_admin_count <= 1:
            raise HTTPException(400, "cannot remove local login from last active admin")
    if user.id == current_user.id and next_policy == LOGIN_POLICY_OAUTH_ONLY:
        raise HTTPException(400, "cannot remove local login from current admin")
    before = str(user.login_policy or LOGIN_POLICY_LOCAL_OR_OAUTH)
    user.login_policy = next_policy
    _write_audit_log(
        db,
        actor_user=current_user,
        target_user=user,
        action="toggle_login_policy",
        details={"before": before, "after": next_policy},
    )
    db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)


@app.get("/quiz", response_class=HTMLResponse)
def quiz_page(
    request: Request,
    subject_id: int | None = None,
    chapter_id: int | None = None,
    db: Session = Depends(get_session),
):
    current_user = get_current_user(db, request)
    q = quiz.pick_choice_question(db, subject_id=subject_id, chapter_id=chapter_id, user_id=current_user.id)
    importance = question_importance_details(db, [q.id]).get(q.id) if q is not None else None
    subjects = db.query(Subject).order_by(Subject.id).all()
    chapters = db.query(Chapter).filter(Chapter.subject_id == subject_id).all() if subject_id else []
    return _render(
        request,
        "quiz.html",
        {
            "question": q,
            "subjects": subjects,
            "chapters": chapters,
            "subject_id": subject_id,
            "chapter_id": chapter_id,
            "importance": importance,
        },
        current_user,
    )


@app.post("/api/choice/submit")
def submit_choice(payload: ChoiceSubmit, request: Request, db: Session = Depends(get_session)):
    current_user = get_current_user(db, request)
    q = db.get(Question, payload.question_id)
    if q is None or q.type != QuestionType.CHOICE:
        raise HTTPException(404, "question not found")
    correct = (payload.user_answer or "").strip().upper() == (q.answer or "").strip().upper()
    quiz.record_attempt(
        db,
        question_id=q.id,
        user_answer=payload.user_answer,
        correct=correct,
        user_id=current_user.id,
        time_spent_ms=payload.time_spent_ms,
    )
    return {
        "correct": correct,
        "answer": q.answer,
        "explanation": q.explanation,
        "law_refs": serialize_question_law_refs(q),
    }


@app.get("/essay", response_class=HTMLResponse)
def essay_page(request: Request, db: Session = Depends(get_session)):
    import sqlalchemy

    current_user = get_current_user(db, request)
    q = db.query(Question).filter(Question.type == QuestionType.ESSAY).order_by(sqlalchemy.func.random()).first()
    return _render(
        request,
        "essay.html",
        {"question": q, "structured_law_refs": serialize_question_law_refs(q) if q is not None else []},
        current_user,
    )


@app.post("/api/essay/submit", response_model=GradingOut)
def submit_essay(payload: EssaySubmit, request: Request, db: Session = Depends(get_session)):
    current_user = get_current_user(db, request)
    q = db.get(Question, payload.question_id)
    if q is None or q.type != QuestionType.ESSAY:
        raise HTTPException(404, "essay not found")
    try:
        result = grading.grade_essay(question=q.body, answer=payload.user_answer, reference=q.answer or "")
    except Exception as exc:
        raise HTTPException(500, f"grading failed: {exc}")

    quiz.record_attempt(
        db,
        question_id=q.id,
        user_answer=payload.user_answer,
        correct=result.score >= 60,
        user_id=current_user.id,
        score=float(result.score),
        feedback=result.raw,
    )
    return GradingOut(
        score=result.score,
        dimensions=result.dimensions,
        strengths=result.strengths,
        weaknesses=result.weaknesses,
        improved_answer=result.improved_answer,
        key_law_refs=result.key_law_refs,
    )


@app.get("/mock-exam", response_class=HTMLResponse)
def mock_exam_page(request: Request, db: Session = Depends(get_session)):
    current_user = get_current_user(db, request)
    paper = mock_exam.build_mock_exam(db)
    return _render(
        request,
        "mock_exam.html",
        {"paper": paper, "subject_count": len({question.subject_id for question in paper.questions}), "total_questions": len(paper.questions)},
        current_user,
    )


@app.post("/mock-exam", response_class=HTMLResponse)
async def mock_exam_submit(request: Request, db: Session = Depends(get_session)):
    await validate_csrf(request)
    current_user = get_current_user(db, request)
    form = await request.form()
    question_ids = [int(value) for value in form.getlist("question_ids") if str(value).strip().isdigit()]
    if not question_ids:
        raise HTTPException(400, "mock exam is empty")
    answers = {question_id: str(form.get(f"answer_{question_id}", "") or "") for question_id in question_ids}
    result = mock_exam.grade_mock_exam(
        db,
        question_ids=question_ids,
        answers=answers,
        record_attempt=quiz.record_attempt,
        user_id=current_user.id,
    )
    return _render(request, "mock_exam_result.html", result, current_user)


@app.get("/wrong", response_class=HTMLResponse)
def wrong_page(request: Request, db: Session = Depends(get_session)):
    current_user = get_current_user(db, request)
    wrong_qs = quiz.wrong_questions(db, limit=50, user_id=current_user.id)
    for item in wrong_qs:
        question = item.get("question")
        item["structured_law_refs"] = serialize_question_law_refs(question) if question is not None else []
    return _render(request, "wrong.html", {"questions": wrong_qs}, current_user)


@app.get("/api/stats")
def stats(request: Request, db: Session = Depends(get_session)):
    current_user = get_current_user(db, request)
    return {
        "coverage": quiz.coverage_by_subject(db, user_id=current_user.id),
        "daily_30d": quiz.accuracy_buckets(db, days=30, user_id=current_user.id),
        "weekly_90d": quiz.accuracy_buckets(db, days=90, user_id=current_user.id),
        "monthly_365d": quiz.accuracy_buckets(db, days=365, user_id=current_user.id),
    }


@app.get("/api/chapters")
def get_chapters(subject_id: int, db: Session = Depends(get_session)):
    chapters = db.query(Chapter).filter(Chapter.subject_id == subject_id).all()
    return [{"id": c.id, "name": c.name} for c in chapters]


@app.get("/laws", response_class=HTMLResponse)
def laws_index(request: Request, subject_id: int | None = None, db: Session = Depends(get_session)):
    current_user = get_current_user(db, request)
    items = db.query(Law).order_by(Law.name).all()
    counts = {law.id: len(law.articles) for law in items}
    frequency = law_frequency_stats(db, subject_id=subject_id)
    subjects = db.query(Subject).order_by(Subject.id).all()
    catalog_meta = {law.id: LAW_CATALOG_BY_NAME.get(law.name) for law in items}
    return _render(
        request,
        "laws.html",
        {
            "laws": items,
            "counts": counts,
            "frequency": frequency,
            "subjects": subjects,
            "subject_id": subject_id,
            "catalog_meta": catalog_meta,
        },
        current_user,
    )


@app.get("/exam-papers", response_class=HTMLResponse)
def exam_papers_page(request: Request, year: int | None = None, q: str | None = None, db: Session = Depends(get_session)):
    current_user = get_current_user(db, request)
    exam_papers.sync_exam_paper_index(db)
    bundles = exam_papers.query_exam_papers(db, roc_year=year, subject_query=q)
    years = exam_papers.available_roc_years(db)
    return _render(
        request,
        "exam_papers.html",
        {"bundles": bundles, "years": years, "selected_year": year, "query": q or ""},
        current_user,
    )


@app.get("/exam-papers/files/{bundle_id}/{file_name}")
def exam_paper_file(bundle_id: str, file_name: str):
    file_path = exam_papers.resolve_bundle_file(bundle_id, file_name)
    if file_path is None:
        raise HTTPException(404, "file not found")
    return FileResponse(path=file_path, filename=file_path.name)


@app.get("/exam-papers/{bundle_id}/subjects/{subject_order}", response_class=HTMLResponse)
def exam_paper_subject_questions(bundle_id: str, subject_order: int, request: Request, db: Session = Depends(get_session)):
    current_user = get_current_user(db, request)
    paper = db.query(ExamPaper).filter(ExamPaper.bundle_id == bundle_id).first()
    if paper is None:
        raise HTTPException(404, "exam paper not found")
    subject_row = next((item for item in paper.subjects if item.sort_order == subject_order), None)
    if subject_row is None:
        raise HTTPException(404, "subject row not found")

    prefix = f"moex:{bundle_id}:subject:{subject_order}:"
    questions = db.query(Question).filter(Question.source.like(f"{prefix}%")).order_by(Question.type, Question.id).all()
    items = [
        {
            "question": question,
            "law_refs": serialize_question_law_refs(question),
            "law_ref_links": linked_law_refs(db, question),
            "source_url": _question_source_url(question.source),
        }
        for question in questions
    ]
    return _render(request, "exam_paper_subject.html", {"paper": paper, "subject_row": subject_row, "items": items}, current_user)


@app.get("/laws/{law_id}", response_class=HTMLResponse)
def law_detail(law_id: int, request: Request, subject_id: int | None = None, db: Session = Depends(get_session)):
    current_user = get_current_user(db, request)
    law = db.get(Law, law_id)
    if law is None:
        raise HTTPException(404, "law not found")
    articles = sorted(law.articles, key=lambda a: _article_sort_key(a.article_no))
    frequency = law_frequency_stats(db, subject_id=subject_id).get(
        law.id, {"question_count": 0, "importance_score": 0.0, "weight": 1.0, "level": "未統計"}
    )
    linked_questions = [{"question": question, "source_url": _question_source_url(question.source)} for question in linked_questions_for_law(db, law.id)]
    return _render(
        request,
        "law_detail.html",
        {
            "law": law,
            "articles": articles,
            "linked_questions": linked_questions,
            "frequency": frequency,
            "subject_id": subject_id,
            "subject": db.get(Subject, subject_id) if subject_id else None,
            "catalog_entry": LAW_CATALOG_BY_NAME.get(law.name),
        },
        current_user,
    )


def _article_sort_key(article_no: str) -> tuple[int, int]:
    import re

    match = re.search(r"第\s*([0-9]+)(?:-([0-9]+))?\s*條", article_no)
    if not match:
        return (9999, 0)
    return (int(match.group(1)), int(match.group(2) or 0))


def _question_source_url(source: str | None) -> str | None:
    import re

    value = str(source or "")
    match = re.match(r"^moex:([^:]+):subject:(\d+):", value)
    if not match:
        return None
    return f"/exam-papers/{match.group(1)}/subjects/{match.group(2)}"
