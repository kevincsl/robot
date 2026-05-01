"""CSRF helpers for form-based POST requests."""
from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, Response
from app.services.security import cookie_options

CSRF_COOKIE_KEY = "house_agent_csrf_token"
CSRF_FORM_KEY = "csrf_token"
CSRF_COOKIE_MAX_AGE = 60 * 60 * 8


def get_or_create_csrf_token(request: Request) -> str:
    token = str(request.cookies.get(CSRF_COOKIE_KEY) or "").strip()
    if token:
        return token
    return secrets.token_urlsafe(32)


def set_csrf_cookie(response: Response, token: str, request: Request | None = None) -> None:
    response.set_cookie(
        CSRF_COOKIE_KEY,
        token,
        **cookie_options(request=request, httponly=False, max_age=CSRF_COOKIE_MAX_AGE),
    )


async def validate_csrf(request: Request) -> None:
    cookie_token = str(request.cookies.get(CSRF_COOKIE_KEY) or "").strip()
    form = await request.form()
    form_token = str(form.get(CSRF_FORM_KEY, "") or "").strip()
    if not cookie_token or not form_token or cookie_token != form_token:
        raise HTTPException(403, "invalid csrf token")
