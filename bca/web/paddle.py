"""Paddle Billing: webhook signature verification and event handling.

Paddle is merchant of record: it calculates and remits VAT, issues invoices and processes refunds.
We only grant or revoke course access from its webhooks.
"""
from __future__ import annotations

import hashlib
import hmac
import time

import requests


class SignatureError(Exception):
    pass


def verify_signature(raw_body: bytes, header: str, secret: str, tolerance_s: int = 300, now: float | None = None) -> None:
    """Paddle-Signature: ts=<unix>;h1=<hex hmac_sha256(secret, f"{ts}:{body}")>"""
    if not secret:
        raise SignatureError("PADDLE_WEBHOOK_SECRET not configured")
    pairs = [p.strip().split("=", 1) for p in (header or "").split(";") if "=" in p]
    ts = next((v for k, v in pairs if k == "ts"), None)
    sigs = [v for k, v in pairs if k == "h1"]
    if not ts or not sigs:
        raise SignatureError("malformed signature header")
    if not ts.isdigit() or abs((now or time.time()) - int(ts)) > tolerance_s:
        raise SignatureError("timestamp outside tolerance")
    expected = hmac.new(secret.encode(), f"{ts}:".encode() + raw_body, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in sigs):
        raise SignatureError("signature mismatch")


def sign(raw_body: bytes, secret: str, ts: int | None = None) -> str:
    """Build a valid header (used in tests and for local webhook simulation)."""
    ts = ts or int(time.time())
    return f"ts={ts};h1=" + hmac.new(secret.encode(), f"{ts}:".encode() + raw_body, hashlib.sha256).hexdigest()


def customer_email(api_base: str, api_key: str, customer_id: str) -> str | None:
    if not (api_key and customer_id):
        return None
    r = requests.get(f"{api_base}/customers/{customer_id}", headers={"Authorization": f"Bearer {api_key}"}, timeout=20)
    r.raise_for_status()
    return (r.json().get("data") or {}).get("email")
