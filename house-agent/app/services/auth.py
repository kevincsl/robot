"""Local user accounts and cookie helpers."""
from __future__ import annotations

import hashlib

import bcrypt
from fastapi import HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.models import User
from app.services.security import cookie_options

DEFAULT_USERNAME = "guest"
DEFAULT_DISPLAY_NAME = "Guest"
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_DISPLAY_NAME = "Administrator"
COOKIE_USER_ID_KEY = "house_agent_user_id"
LOGIN_COOKIE_MAX_AGE = 60 * 60 * 24 * 30
USER_STATUS_ACTIVE = "active"
USER_STATUS_DISABLED = "disabled"
LOGIN_POLICY_LOCAL_OR_OAUTH = "local_or_oauth"
LOGIN_POLICY_OAUTH_ONLY = "oauth_only"


def hash_password(password: str) -> str:
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    value = str(password_hash or "")
    if _looks_like_bcrypt_hash(value):
        try:
            return bcrypt.checkpw(password.encode("utf-8"), value.encode("utf-8"))
        except ValueError:
            return False
    return _legacy_sha256(password) == value


def password_needs_rehash(password_hash: str) -> bool:
    return not _looks_like_bcrypt_hash(str(password_hash or ""))


def get_or_create_default_user(db: Session) -> User:
    user = db.query(User).filter(User.username == DEFAULT_USERNAME).first()
    if user is None:
        user = User(
            username=DEFAULT_USERNAME,
            display_name=DEFAULT_DISPLAY_NAME,
            password_hash=hash_password("guest"),
            status=USER_STATUS_ACTIVE,
            login_policy=LOGIN_POLICY_LOCAL_OR_OAUTH,
            is_admin=False,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    elif password_needs_rehash(user.password_hash):
        user.password_hash = hash_password("guest")
        db.commit()
        db.refresh(user)
    return user


def get_or_create_default_admin(db: Session) -> User:
    user = db.query(User).filter(User.username == DEFAULT_ADMIN_USERNAME).first()
    if user is None:
        user = User(
            username=DEFAULT_ADMIN_USERNAME,
            display_name=DEFAULT_ADMIN_DISPLAY_NAME,
            password_hash=hash_password("admin1234"),
            status=USER_STATUS_ACTIVE,
            login_policy=LOGIN_POLICY_LOCAL_OR_OAUTH,
            is_admin=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        if not user.is_admin:
            user.is_admin = True
        if user.status != USER_STATUS_ACTIVE:
            user.status = USER_STATUS_ACTIVE
        if user.login_policy != LOGIN_POLICY_LOCAL_OR_OAUTH:
            user.login_policy = LOGIN_POLICY_LOCAL_OR_OAUTH
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password("admin1234")
        db.commit()
        db.refresh(user)
    return user


def list_users(db: Session) -> list[User]:
    return db.query(User).order_by(User.username).all()


def create_user(db: Session, *, username: str, display_name: str, password: str) -> User:
    normalized_username = username.strip().lower()
    if not normalized_username:
        raise HTTPException(400, "username is required")
    if len(password) < 4:
        raise HTTPException(400, "password must be at least 4 characters")
    existing = db.query(User).filter(User.username == normalized_username).first()
    if existing is not None:
        raise HTTPException(400, "username already exists")
    user = User(
        username=normalized_username,
        display_name=display_name.strip() or normalized_username,
        password_hash=hash_password(password),
        status=USER_STATUS_ACTIVE,
        login_policy=LOGIN_POLICY_LOCAL_OR_OAUTH,
        is_admin=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, *, username: str, password: str) -> User | None:
    normalized_username = username.strip().lower()
    user = db.query(User).filter(User.username == normalized_username).first()
    if user is None or not verify_password(password, user.password_hash):
        return None
    if not is_user_active(user):
        return None
    if not allows_local_login(user):
        return None
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        db.commit()
        db.refresh(user)
    return user


def set_login_cookie(response: Response, user: User, request: Request | None = None) -> None:
    response.set_cookie(
        COOKIE_USER_ID_KEY,
        str(user.id),
        **cookie_options(request=request, httponly=True, max_age=LOGIN_COOKIE_MAX_AGE),
    )


def clear_login_cookie(response: Response, request: Request | None = None) -> None:
    response.delete_cookie(COOKIE_USER_ID_KEY, path="/", secure=cookie_options(request=request, httponly=True)["secure"])


def get_current_user(db: Session, request: Request) -> User:
    user_id = request.cookies.get(COOKIE_USER_ID_KEY)
    if user_id and str(user_id).isdigit():
        user = db.get(User, int(user_id))
        if user is not None and is_user_active(user):
            return user
    return get_or_create_default_user(db)


def require_admin_user(db: Session, request: Request) -> User:
    user = get_current_user(db, request)
    if not user.is_admin or not is_user_active(user):
        raise HTTPException(403, "admin required")
    return user


def is_user_active(user: User | None) -> bool:
    return user is not None and str(user.status or USER_STATUS_ACTIVE) == USER_STATUS_ACTIVE


def allows_local_login(user: User | None) -> bool:
    return user is not None and str(user.login_policy or LOGIN_POLICY_LOCAL_OR_OAUTH) == LOGIN_POLICY_LOCAL_OR_OAUTH


def _legacy_sha256(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _looks_like_bcrypt_hash(value: str) -> bool:
    return value.startswith("$2a$") or value.startswith("$2b$") or value.startswith("$2y$")
