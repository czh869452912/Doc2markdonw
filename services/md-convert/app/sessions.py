from __future__ import annotations

import base64
import hashlib
import re
import secrets
from dataclasses import dataclass
from typing import Protocol


COOKIE_NAME = "md_convert_session"
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


class CookieResponse(Protocol):
    def set_cookie(self, **kwargs) -> None: ...


@dataclass(frozen=True)
class SessionIdentity:
    token: str
    owner_hash: str
    fingerprint: str
    is_new: bool


def resolve_session(token: str | None) -> SessionIdentity:
    is_new = not _valid_token(token)
    resolved_token = secrets.token_urlsafe(32) if is_new else token
    assert resolved_token is not None
    owner_hash = hashlib.sha256(resolved_token.encode("ascii")).hexdigest()
    return SessionIdentity(
        token=resolved_token,
        owner_hash=owner_hash,
        fingerprint=owner_hash[:16],
        is_new=is_new,
    )


def set_session_cookie(
    response: CookieResponse,
    identity: SessionIdentity,
    secure: bool,
) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=identity.token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _valid_token(token: str | None) -> bool:
    if not token or not TOKEN_RE.fullmatch(token):
        return False
    try:
        decoded = base64.urlsafe_b64decode(token + "=")
    except (ValueError, base64.binascii.Error):
        return False
    return len(decoded) == 32
