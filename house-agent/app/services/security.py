"""Shared security settings for cookies and response headers."""
from __future__ import annotations

import os

from fastapi import Request, Response


def should_use_secure_cookies(request: Request | None = None) -> bool:
    configured = os.getenv("HOUSE_AGENT_COOKIE_SECURE", "").strip().lower()
    if configured in {"1", "true", "yes", "on"}:
        return True
    if configured in {"0", "false", "no", "off"}:
        return False
    if request is None:
        return False
    forwarded_proto = str(request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip().lower()
    if forwarded_proto:
        return forwarded_proto == "https"
    return request.url.scheme == "https"


def cookie_options(
    *,
    request: Request | None = None,
    httponly: bool,
    max_age: int | None = None,
) -> dict:
    options = {
        "httponly": httponly,
        "samesite": "lax",
        "secure": should_use_secure_cookies(request),
        "path": "/",
    }
    if max_age is not None:
        options["max_age"] = max_age
    return options


def apply_security_headers(response: Response) -> Response:
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; "
        "font-src 'self' data:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'"
    )
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response
