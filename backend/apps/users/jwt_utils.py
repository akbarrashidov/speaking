"""Qisqa muddatli JWT — REST va WebSocket auth uchun (§4.1)."""

from __future__ import annotations

import time

import jwt
from django.conf import settings


class TokenError(Exception):
    pass


def issue_token(user, ttl_seconds: int | None = None) -> tuple[str, int]:
    """(token, expires_in) qaytaradi."""
    ttl = ttl_seconds or settings.JWT_TTL_SECONDS
    now = int(time.time())
    payload = {
        "sub": str(user.pk),
        "iat": now,
        "exp": now + ttl,
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return token, ttl


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("token_invalid") from exc


def get_user_from_token(token: str):
    """Token bo'yicha aktiv foydalanuvchini qaytaradi (sinxron kontekst)."""
    from apps.users.models import User

    payload = decode_token(token)
    try:
        return User.objects.get(pk=int(payload["sub"]), is_active=True)
    except (User.DoesNotExist, KeyError, ValueError) as exc:
        raise TokenError("user_not_found") from exc
