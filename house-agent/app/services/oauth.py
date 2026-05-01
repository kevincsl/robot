"""OAuth helpers for Google OIDC and GitHub OAuth."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.models import User, UserIdentity
from app.services.security import cookie_options
from app.services.auth import USER_STATUS_ACTIVE, is_user_active

GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_EMAILS_URL = "https://api.github.com/user/emails"
OAUTH_STATE_COOKIE_KEY = "house_agent_oauth_state"
OAUTH_STATE_COOKIE_MAX_AGE = 60 * 10
GOOGLE_PROVIDER = "google"
GITHUB_PROVIDER = "github"


@dataclass(frozen=True)
class OAuthProviderSettings:
    provider: str
    client_id: str
    client_secret: str
    discovery_url: str | None = None


def get_google_settings() -> OAuthProviderSettings | None:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None
    discovery_url = os.getenv("GOOGLE_DISCOVERY_URL", GOOGLE_DISCOVERY_URL).strip() or GOOGLE_DISCOVERY_URL
    return OAuthProviderSettings(
        provider=GOOGLE_PROVIDER,
        client_id=client_id,
        client_secret=client_secret,
        discovery_url=discovery_url,
    )


def get_github_settings() -> OAuthProviderSettings | None:
    client_id = os.getenv("GITHUB_CLIENT_ID", "").strip()
    client_secret = os.getenv("GITHUB_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None
    return OAuthProviderSettings(
        provider=GITHUB_PROVIDER,
        client_id=client_id,
        client_secret=client_secret,
    )


def google_oauth_enabled() -> bool:
    return get_google_settings() is not None


def github_oauth_enabled() -> bool:
    return get_github_settings() is not None


def _load_discovery_document(settings: OAuthProviderSettings) -> dict:
    if not settings.discovery_url:
        raise HTTPException(500, "provider discovery url missing")
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.get(settings.discovery_url)
        response.raise_for_status()
        return response.json()


def build_google_authorize_url(request: Request) -> tuple[str, str]:
    settings = get_google_settings()
    if settings is None:
        raise HTTPException(503, "google oauth not configured")
    state = secrets.token_urlsafe(24)
    discovery = _load_discovery_document(settings)
    redirect_uri = str(request.url_for("google_oauth_callback"))
    query = urlencode(
        {
            "client_id": settings.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
    )
    return f"{discovery['authorization_endpoint']}?{query}", state


def build_github_authorize_url(request: Request) -> tuple[str, str]:
    settings = get_github_settings()
    if settings is None:
        raise HTTPException(503, "github oauth not configured")
    state = secrets.token_urlsafe(24)
    redirect_uri = str(request.url_for("github_oauth_callback"))
    query = urlencode(
        {
            "client_id": settings.client_id,
            "redirect_uri": redirect_uri,
            "scope": "read:user user:email",
            "state": state,
        }
    )
    return f"{GITHUB_AUTHORIZE_URL}?{query}", state


def set_oauth_state_cookie(response: Response, state: str, request: Request | None = None) -> None:
    response.set_cookie(
        OAUTH_STATE_COOKIE_KEY,
        state,
        **cookie_options(request=request, httponly=True, max_age=OAUTH_STATE_COOKIE_MAX_AGE),
    )


def clear_oauth_state_cookie(response: Response, request: Request | None = None) -> None:
    response.delete_cookie(
        OAUTH_STATE_COOKIE_KEY,
        path="/",
        secure=cookie_options(request=request, httponly=True)["secure"],
    )


def validate_oauth_state(request: Request, state: str) -> None:
    saved_state = str(request.cookies.get(OAUTH_STATE_COOKIE_KEY) or "")
    if not state or not saved_state or state != saved_state:
        raise HTTPException(400, "invalid oauth state")


def exchange_google_code_for_profile(request: Request, code: str) -> dict:
    settings = get_google_settings()
    if settings is None:
        raise HTTPException(503, "google oauth not configured")
    if not code:
        raise HTTPException(400, "missing google authorization code")
    discovery = _load_discovery_document(settings)
    redirect_uri = str(request.url_for("google_oauth_callback"))
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        token_response = client.post(
            discovery["token_endpoint"],
            data={
                "code": code,
                "client_id": settings.client_id,
                "client_secret": settings.client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        token_response.raise_for_status()
        token_payload = token_response.json()
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            raise HTTPException(502, "google oauth access token missing")
        profile_response = client.get(
            discovery["userinfo_endpoint"],
            headers={"Authorization": f"Bearer {access_token}"},
        )
        profile_response.raise_for_status()
        profile = profile_response.json()
    if not profile.get("sub"):
        raise HTTPException(502, "google oauth subject missing")
    return profile


def exchange_github_code_for_profile(request: Request, code: str) -> dict:
    settings = get_github_settings()
    if settings is None:
        raise HTTPException(503, "github oauth not configured")
    if not code:
        raise HTTPException(400, "missing github authorization code")
    redirect_uri = str(request.url_for("github_oauth_callback"))
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        token_response = client.post(
            GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.client_id,
                "client_secret": settings.client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        token_response.raise_for_status()
        token_payload = token_response.json()
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            raise HTTPException(502, "github oauth access token missing")
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        user_response = client.get(GITHUB_USER_URL, headers=headers)
        user_response.raise_for_status()
        profile = user_response.json()
        emails_response = client.get(GITHUB_EMAILS_URL, headers=headers)
        emails_response.raise_for_status()
        emails = emails_response.json()
    primary_email = _pick_github_email(emails)
    return {
        "id": str(profile.get("id") or ""),
        "email": primary_email,
        "name": str(profile.get("name") or profile.get("login") or "").strip() or None,
        "avatar_url": str(profile.get("avatar_url") or "").strip() or None,
        "login": str(profile.get("login") or "").strip() or None,
    }


def get_or_create_oauth_user(
    db: Session,
    *,
    provider: str,
    provider_user_id: str,
    email: str | None,
    display_name: str | None,
    avatar_url: str | None,
    fallback_username: str | None = None,
) -> User:
    identity = (
        db.query(UserIdentity)
        .filter(
            UserIdentity.provider == provider,
            UserIdentity.provider_user_id == provider_user_id,
        )
        .first()
    )
    if identity is not None:
        if not is_user_active(identity.user):
            raise HTTPException(403, "user disabled")
        if display_name:
            identity.user.display_name = display_name.strip() or identity.user.display_name
        identity.email = _normalize_email(email)
        identity.avatar_url = avatar_url
        db.commit()
        db.refresh(identity.user)
        return identity.user

    normalized_email = _normalize_email(email)
    username_base = normalized_email or (fallback_username or f"{provider}_{provider_user_id}")
    username = _dedupe_username(db, username_base)
    user = User(
        username=username,
        display_name=(display_name or normalized_email or fallback_username or username).strip(),
        password_hash="",
        status=USER_STATUS_ACTIVE,
        is_admin=False,
    )
    db.add(user)
    db.flush()
    db.add(
        UserIdentity(
            user_id=user.id,
            provider=provider,
            provider_user_id=provider_user_id,
            email=normalized_email,
            avatar_url=avatar_url,
        )
    )
    db.commit()
    db.refresh(user)
    return user


def _pick_github_email(emails: list[dict]) -> str | None:
    verified = [item for item in emails if item.get("verified")]
    primary = next((item for item in verified if item.get("primary")), None)
    if primary and primary.get("email"):
        return str(primary["email"]).strip().lower()
    first_verified = next((item for item in verified if item.get("email")), None)
    if first_verified:
        return str(first_verified["email"]).strip().lower()
    first = next((item for item in emails if item.get("email")), None)
    if first:
        return str(first["email"]).strip().lower()
    return None


def _normalize_email(email: str | None) -> str | None:
    value = (email or "").strip().lower()
    return value or None


def _dedupe_username(db: Session, candidate: str) -> str:
    value = candidate.strip().lower().replace(" ", "_") or "user"
    current = value
    suffix = 2
    while db.query(User).filter(User.username == current).first() is not None:
        current = f"{value}_{suffix}"
        suffix += 1
    return current
