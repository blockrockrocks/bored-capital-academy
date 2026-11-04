"""Operational commands: daily follow-up emails, KPI stats, local purchase simulation."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta, timezone

from . import auth, mailer, paddle
from .config import Settings
from .db import DB


def followups(s: Settings, db: DB, mail: mailer.Mailer) -> int:
    """Send the feedback-survey email N days after enrolment, once per student. Run daily (cron)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=s.survey_after_days)
    sent = 0
    for st in db.students():
        enrolled = datetime.strptime(st["enrolled_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if st["status"] == "active" and enrolled <= cutoff and db.mark_sent(st["email"], "survey"):
            tok = auth.make_token(s.secret_key, st["email"], "login", ttl_s=7 * 86400)
            mail.send(st["email"], *mailer.survey(f"{s.base_url}/auth?token={tok}&next=/survey"))
            sent += 1
    return sent


def stats(db: DB) -> str:
    sts = db.students()
    active = [x for x in sts if x["status"] == "active"]
    revenue: dict[str, float] = {}
    for x in active:
        try:
            # Paddle totals are in the currency's lowest unit (cents for EUR)
            revenue[x["currency"] or "?"] = revenue.get(x["currency"] or "?", 0) + int(x["amount"] or 0) / 100
        except ValueError:
            pass
    sv = db.surveys()
    positive = sum(1 for r in sv if r["overall"] >= 4)
    nps = (sum(1 for r in sv if r["recommend"] >= 9) - sum(1 for r in sv if r["recommend"] <= 6)) / len(sv) * 100 if sv else None
    by_tier = {}
    for x in active:
        by_tier[x["tier"]] = by_tier.get(x["tier"], 0) + 1
    lines = [
        f"Paid students (active): {len(active)}  {by_tier}   refunded: {len(sts) - len(active)}",
        "Revenue incl. VAT (gross, Paddle totals): " + (", ".join(f"{v:,.2f} {k}" for k, v in revenue.items()) or "0"),
        f"Survey responses: {len(sv)}" + (f"   positive (4-5/5): {positive / len(sv):.0%} (target ≥80%)   NPS: {nps:+.0f}" if sv else ""),
    ]
    return "\n".join(lines)


def simulate_purchase(s: Settings, email: str, tier: str, url: str | None = None) -> dict:
    """Send a correctly signed fake 'transaction.completed' to a running local server (dev/testing only)."""
    import requests
    t = s.tier(tier)
    body = json.dumps({
        "event_id": f"evt_sim_{uuid.uuid4().hex[:12]}", "event_type": "transaction.completed",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "data": {"id": f"txn_sim_{uuid.uuid4().hex[:10]}", "status": "completed", "customer_id": "ctm_sim",
                 "currency_code": "EUR", "custom_data": {"email": email, "tier": tier},
                 "items": [{"price": {"id": t.paddle_price_id or f"pri_sim_{tier}"}, "quantity": 1}],
                 "details": {"totals": {"grand_total": "8900" if tier == "self" else "17900"}}},
    }).encode()
    r = requests.post(url or f"{s.base_url}/webhooks/paddle", data=body, timeout=20,
                      headers={"Content-Type": "application/json", "Paddle-Signature": paddle.sign(body, s.paddle_webhook_secret, int(time.time()))})
    return {"status": r.status_code, "body": r.text}
