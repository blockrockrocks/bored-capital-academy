"""Passwordless login: signed, expiring, single-use magic links and a signed session cookie."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def _pack(parts: list[str]) -> str:
    return base64.urlsafe_b64encode("|".join(parts).encode()).decode().rstrip("=")


def _unpack(token: str) -> list[str]:
    return base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode().split("|")


def make_token(secret: str, email: str, purpose: str, ttl_s: int, nonce: bool = True) -> str:
    parts = [purpose, email, str(int(time.time()) + ttl_s), secrets.token_hex(8) if nonce else "-"]
    return _pack(parts + [_sign(secret, "|".join(parts))])


def read_token(secret: str, token: str, purpose: str) -> tuple[str, str] | None:
    """Returns (email, nonce) when valid and unexpired."""
    try:
        p, email, exp, nonce, sig = _unpack(token)
    except Exception:
        return None
    if p != purpose or not hmac.compare_digest(sig, _sign(secret, "|".join([p, email, exp, nonce]))):
        return None
    if int(exp) < time.time():
        return None
    return email, nonce
