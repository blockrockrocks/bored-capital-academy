"""Website tests: FastAPI TestClient, synthetic Paddle events, console email backend (no network)."""
import json
import re
import time

import pytest
from fastapi.testclient import TestClient

from bca.web import auth, mailer, ops, paddle
from bca.web.app import create_app
from bca.web.config import Settings

SECRET = "pdl_ntfset_test_secret"


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k, v in {"BCA_BASE_URL": "http://testserver", "BCA_SECRET_KEY": "k" * 32, "BCA_DB": str(tmp_path / "db.sqlite3"),
                 "BCA_DATA_DIR": str(tmp_path / "data"), "BCA_LOG_DIR": str(tmp_path / "logs"),
                 "PADDLE_WEBHOOK_SECRET": SECRET, "PADDLE_CLIENT_TOKEN": "test_tok",
                 "PADDLE_PRICE_SELF": "pri_self", "PADDLE_PRICE_LIVE": "pri_live"}.items():
        monkeypatch.setenv(k, v)
    sent = []

    class FakeTutor:
        def __init__(self, email):
            self.email = email

        def send(self, text):
            sent.append((self.email, text))
            return f"echo: {text}"

    s = Settings()
    app = create_app(s, tutor_factory=FakeTutor)
    return TestClient(app), app, s, tmp_path, sent


def hook(client, event_type, data, event_id=None, secret=SECRET, ts=None):
    body = json.dumps({"event_id": event_id or f"evt_{time.time_ns()}", "event_type": event_type, "data": data}).encode()
    return client.post("/webhooks/paddle", content=body,
                       headers={"Paddle-Signature": paddle.sign(body, secret, ts), "Content-Type": "application/json"})


def purchase(client, email="ana@example.com", price="pri_self", txn="txn_1", event_id=None):
    return hook(client, "transaction.completed",
                {"id": txn, "customer_id": "ctm_1", "currency_code": "EUR", "custom_data": {"email": email},
                 "items": [{"price": {"id": price}, "quantity": 1}], "details": {"totals": {"grand_total": "8900"}}},
                event_id=event_id)


def outbox(tmp_path):
    d = tmp_path / "logs" / "outbox"
    return sorted(d.glob("*.eml")) if d.exists() else []


def login_link_from(eml_path):
    return re.search(r"http://testserver(/auth\?token=[\w-]+)", eml_path.read_text()).group(1)


def test_landing_page_shows_tiers_and_disclaimers(env):
    client, *_ = env
    html = client.get("/").text
    assert "Think Beyond the Floor." in html and "€89" in html and "€179" in html
    assert 'data-price="pri_self"' in html and "not affiliated with" in html
    assert "right of withdrawal" in html  # consent checkbox before checkout
    assert "Checkout is not configured" not in html
    for page in ("terms", "privacy", "imprint"):
        assert client.get(f"/legal/{page}").status_code == 200


def test_signature_verification():
    body = b'{"a":1}'
    paddle.verify_signature(body, paddle.sign(body, SECRET), SECRET)
    for bad in (paddle.sign(body, "wrong"), paddle.sign(body, SECRET, ts=int(time.time()) - 3600), "", "ts=abc;h1=00"):
        with pytest.raises(paddle.SignatureError):
            paddle.verify_signature(body, bad, SECRET)
    with pytest.raises(paddle.SignatureError):
        paddle.verify_signature(b'{"a":2}', paddle.sign(body, SECRET), SECRET)  # tampered body


def test_purchase_enrols_and_emails_once(env):
    client, app, s, tmp_path, _ = env
    assert hook(client, "transaction.completed", {}, secret="wrong").status_code == 401
    assert purchase(client, event_id="evt_1").json() == {"ok": True}
    assert purchase(client, event_id="evt_1").json()["duplicate"] is True  # Paddle retries are idempotent
    st = app.state.db.student("ana@example.com")
    assert st["tier"] == "self" and st["status"] == "active" and st["currency"] == "EUR"
    mails = outbox(tmp_path)
    assert len(mails) == 1 and "Welcome" in mails[0].read_text()


def test_unknown_price_is_ignored_and_live_never_downgrades(env):
    client, app, *_ = env
    assert purchase(client, price="pri_other").json()["ignored"]
    assert app.state.db.student("ana@example.com") is None
    purchase(client, price="pri_live", txn="t1")
    purchase(client, price="pri_self", txn="t2")
    assert app.state.db.student("ana@example.com")["tier"] == "live"


def test_magic_link_login_course_access_and_refund(env):
    client, app, s, tmp_path, _ = env
    assert client.get("/course", follow_redirects=False).status_code == 303
    purchase(client)
    link = login_link_from(outbox(tmp_path)[0])
    r = client.get(link, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/course"
    assert "Why NFT prices are misleading" in client.get("/course").text
    assert "The floor-price illusion" in client.get("/course/module/1").text
    # single use
    client.cookies.clear()
    assert "expired" in client.get(link).text
    # refund revokes access
    client.get(login_link_from(_new_login(client, tmp_path)), follow_redirects=False)
    assert client.get("/course").status_code == 200
    hook(client, "adjustment.created", {"action": "refund", "status": "approved", "transaction_id": "txn_1"})
    assert client.get("/course", follow_redirects=False).status_code == 303


def _new_login(client, tmp_path):
    before = set(outbox(tmp_path))
    client.post("/login", data={"email": "ana@example.com"})
    return (set(outbox(tmp_path)) - before).pop()


def test_login_form_does_not_reveal_enrolment(env):
    client, _, _, tmp_path, _ = env
    a = client.post("/login", data={"email": "nobody@example.com"}).text
    purchase(client)
    b = client.post("/login", data={"email": "ana@example.com"}).text
    assert "If that address has a course enrolment" in a and "If that address has a course enrolment" in b
    assert len(outbox(tmp_path)) == 2  # welcome + login, nothing for the unknown address


def test_forged_and_open_redirect_tokens_rejected(env):
    client, app, s, tmp_path, _ = env
    purchase(client)
    forged = auth.make_token("other-secret", "ana@example.com", "login", 3600)
    assert "expired" in client.get(f"/auth?token={forged}").text
    session_as_login = auth.make_token(s.secret_key, "ana@example.com", "session", 3600)
    assert "expired" in client.get(f"/auth?token={session_as_login}").text
    tok = auth.make_token(s.secret_key, "ana@example.com", "login", 3600)
    r = client.get(f"/auth?token={tok}&next=//evil.example", follow_redirects=False)
    assert r.headers["location"] == "/course"


def test_tutor_api_auth_and_daily_limit(env, monkeypatch):
    client, app, s, tmp_path, sent = env
    assert client.post("/api/tutor", json={"message": "hi"}).status_code == 401
    purchase(client)
    client.get(login_link_from(outbox(tmp_path)[0]))
    s.tutor_daily_limit = 2
    assert client.post("/api/tutor", json={"message": "What is a bid?"}).json()["reply"] == "echo: What is a bid?"
    assert client.post("/api/tutor", json={"message": "again"}).status_code == 200
    assert client.post("/api/tutor", json={"message": "third"}).status_code == 429
    assert sent == [("ana@example.com", "What is a bid?"), ("ana@example.com", "again")]
    assert "Ask the tutor" in client.get("/course/tutor").text


def test_survey_followups_and_stats(env):
    client, app, s, tmp_path, _ = env
    purchase(client)
    db = app.state.db
    assert ops.followups(s, db, mailer.Mailer(s)) == 0  # too early
    s.survey_after_days = 0
    assert ops.followups(s, db, mailer.Mailer(s)) == 1
    assert ops.followups(s, db, mailer.Mailer(s)) == 0  # only once
    survey_mail = next(m.read_text() for m in outbox(tmp_path) if "Two minutes" in m.read_text())
    path = re.search(r"http://testserver(/auth\?token=[\w-]+&next=/survey)", survey_mail).group(1)
    assert client.get(path, follow_redirects=False).headers["location"] == "/survey"
    client.post("/survey", data={"overall": 5, "learned": 4, "recommend": 9, "comment": "great"})
    out = ops.stats(db)
    assert "Paid students (active): 1" in out and "89.00 EUR" in out and "positive (4-5/5): 100%" in out
