"""Bored Capital Academy website: landing page, Paddle checkout, magic-link login, course area,
AI tutor chat, feedback survey. Run with:  python -m bca web serve
"""
from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path

import markdown
from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth, mailer, paddle
from .config import ROOT, Settings
from .db import DB

HERE = Path(__file__).resolve().parent
COURSE_DIR = ROOT / "course"
MODULES = [
    {"n": 1, "file": "01_module1_prices.md", "title": "Why NFT prices are misleading",
     "summary": "Floor vs. bid vs. sale, real liquidity, trading quality and ownership structure."},
    {"n": 2, "file": "02_module2_value.md", "title": "What makes a collectible valuable?",
     "summary": "Valuation ranges, BAYC economics, the Mudwater case and a comparison exercise."},
    {"n": 3, "file": "03_scorecard.md", "title": "The Ape Analytics Scorecard & your assessment",
     "summary": "How to score a collection, and the one-page assessment you'll submit."},
]
SESSION_COOKIE = "bca_session"
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,80}")
log = logging.getLogger("bca.web")


def create_app(settings: Settings | None = None, tutor_factory=None) -> FastAPI:
    s = settings or Settings()
    db = DB(s.db_path)
    mail = mailer.Mailer(s)
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    app = FastAPI(title="Bored Capital Academy", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    tutors: dict[str, object] = {}
    tutors_lock = threading.Lock()

    if tutor_factory is None:
        def tutor_factory(email):
            from ..tutor import Tutor
            return Tutor(student=email, data_dir=s.data_dir, log_dir=s.log_dir)

    def render(request, name, **ctx):
        return templates.TemplateResponse(request, name, {"s": s, "user": current_user(request), **ctx})

    def current_user(request):
        tok = request.cookies.get(SESSION_COOKIE)
        got = auth.read_token(s.secret_key, tok, "session") if tok else None
        if not got:
            return None
        row = db.student(got[0])
        return row if row and row["status"] == "active" else None

    def send_login(email, kind="login"):
        tok = auth.make_token(s.secret_key, email, "login", ttl_s=86400)
        link = f"{s.base_url}/auth?token={tok}"
        if kind == "welcome":
            subject, body = mailer.welcome(s.base_url, s.tier(db.student(email)["tier"]).name, link)
        else:
            subject, body = mailer.login_link(link)
        mail.send(email, subject, body)

    # ------------------------------------------------------------ public
    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return render(request, "index.html", modules=MODULES, checkout_ready=bool(
            s.paddle_client_token and all(t.paddle_price_id for t in s.tiers)))

    @app.get("/legal/{page}", response_class=HTMLResponse)
    def legal(request: Request, page: str):
        if page not in {"terms", "privacy", "imprint"}:
            return HTMLResponse("Not found", status_code=404)
        return render(request, f"legal_{page}.html")

    @app.get("/thanks", response_class=HTMLResponse)
    def thanks(request: Request):
        return render(request, "message.html", title="You're in",
                      body="Payment received. We've emailed you a login link. It can take a minute to arrive; "
                           "check spam if you don't see it.")

    # ------------------------------------------------------------ Paddle
    @app.post("/webhooks/paddle")
    async def paddle_webhook(request: Request):
        raw = await request.body()
        try:
            paddle.verify_signature(raw, request.headers.get("Paddle-Signature", ""), s.paddle_webhook_secret)
        except paddle.SignatureError as e:
            log.warning("rejected Paddle webhook: %s", e)
            return JSONResponse({"error": "invalid signature"}, status_code=401)
        evt = json.loads(raw)
        if not db.claim_event(evt.get("event_id", ""), evt.get("event_type", "")):
            return {"ok": True, "duplicate": True}
        data = evt.get("data") or {}
        etype = evt.get("event_type")
        if etype == "transaction.completed":
            price_ids = [((i.get("price") or {}).get("id")) for i in data.get("items") or []]
            tiers = [t for t in (s.tier_for_price(p) for p in price_ids) if t]
            if not tiers:
                log.warning("transaction %s has no course price: %s", data.get("id"), price_ids)
                return {"ok": True, "ignored": "no matching price"}
            tier = "live" if any(t.key == "live" for t in tiers) else tiers[0].key
            email = ((data.get("custom_data") or {}).get("email") or "").strip().lower()
            if not email:
                email = (paddle.customer_email(s.paddle_api_base, s.paddle_api_key, data.get("customer_id")) or "").lower()
            if not email:
                log.error("transaction %s: no email available", data.get("id"))
                return JSONResponse({"error": "no email"}, status_code=500)  # Paddle retries
            totals = (data.get("details") or {}).get("totals") or {}
            db.upsert_student(email, tier, data.get("id"), data.get("customer_id"),
                              totals.get("grand_total"), data.get("currency_code"))
            send_login(email, kind="welcome")
        elif etype in {"adjustment.created", "adjustment.updated"}:
            if data.get("action") in {"refund", "chargeback"} and data.get("status") == "approved":
                db.revoke_by_transaction(data.get("transaction_id", ""))
        return {"ok": True}

    # ------------------------------------------------------------ login
    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        return render(request, "login.html")

    @app.post("/login", response_class=HTMLResponse)
    def login_submit(request: Request, email: str = Form(...)):
        email = email.strip().lower()
        row = db.student(email)
        if row and row["status"] == "active":
            send_login(email)
        # same answer either way, so the form can't be used to discover who is enrolled
        return render(request, "message.html", title="Check your email",
                      body="If that address has a course enrolment, a login link is on its way.")

    @app.get("/auth")
    def auth_callback(request: Request, token: str = "", next: str = "/course"):
        got = auth.read_token(s.secret_key, token, "login")
        if not got or not db.use_nonce(got[1]):
            return render(request, "message.html", title="Link expired",
                          body="This login link has expired or was already used. Request a new one below.",
                          show_login=True)
        row = db.student(got[0])
        if not row or row["status"] != "active":
            return render(request, "message.html", title="No active enrolment", body="Contact us if this is wrong.")
        dest = next if next.startswith("/") and not next.startswith("//") and "\\" not in next else "/course"
        resp = RedirectResponse(dest, status_code=303)
        resp.set_cookie(SESSION_COOKIE, auth.make_token(s.secret_key, got[0], "session", 30 * 86400, nonce=False),
                        max_age=30 * 86400, httponly=True, samesite="lax", secure=s.base_url.startswith("https"))
        return resp

    @app.post("/logout")
    def logout():
        resp = RedirectResponse("/", status_code=303)
        resp.delete_cookie(SESSION_COOKIE)
        return resp

    # ------------------------------------------------------------ course
    def need_user(request):
        return current_user(request) or RedirectResponse("/login", status_code=303)

    @app.get("/course", response_class=HTMLResponse)
    def course(request: Request):
        user = need_user(request)
        if isinstance(user, RedirectResponse):
            return user
        workbooks = sorted(s.data_dir.glob("*/*/Ape_Analytics_Scorecard_*.xlsx"))
        latest = {}
        for w in workbooks:  # newest per collection
            latest[w.parent.parent.name] = w
        return render(request, "course.html", modules=MODULES,
                      workbooks=[{"slug": k, "snapshot": v.parent.name} for k, v in sorted(latest.items())])

    @app.get("/course/module/{n}", response_class=HTMLResponse)
    def module(request: Request, n: int):
        user = need_user(request)
        if isinstance(user, RedirectResponse):
            return user
        m = next((m for m in MODULES if m["n"] == n), None)
        if not m:
            return HTMLResponse("Not found", status_code=404)
        html = markdown.markdown((COURSE_DIR / m["file"]).read_text(), extensions=["tables"])
        video = s.video_urls[n - 1] if n - 1 < len(s.video_urls) else None
        return render(request, "module.html", m=m, html=html, video=video,
                      prev=n - 1 if n > 1 else None, next=n + 1 if n < len(MODULES) else None)

    @app.get("/course/workbook/{slug}")
    def workbook(request: Request, slug: str):
        user = need_user(request)
        if isinstance(user, RedirectResponse):
            return user
        files = sorted((s.data_dir / slug).glob("*/Ape_Analytics_Scorecard_*.xlsx")) if SLUG_RE.fullmatch(slug) else []
        if not files:
            return HTMLResponse("Not found", status_code=404)
        return FileResponse(files[-1], filename=files[-1].name)

    @app.get("/course/tutor", response_class=HTMLResponse)
    def tutor_page(request: Request):
        user = need_user(request)
        if isinstance(user, RedirectResponse):
            return user
        return render(request, "tutor.html")

    @app.post("/api/tutor")
    async def tutor_api(request: Request):
        user = current_user(request)
        if not user:
            return JSONResponse({"error": "Please log in again."}, status_code=401)
        body = await request.json()
        text = str(body.get("message", "")).strip()[:4000]
        if not text:
            return JSONResponse({"error": "Empty message."}, status_code=400)
        if not db.tutor_hit(user["email"], s.tutor_daily_limit):
            return JSONResponse({"error": f"You've reached today's limit of {s.tutor_daily_limit} tutor messages. "
                                          "It resets at midnight UTC."}, status_code=429)
        with tutors_lock:
            t = tutors.get(user["email"]) or tutors.setdefault(user["email"], tutor_factory(user["email"]))
        from starlette.concurrency import run_in_threadpool
        try:
            reply = await run_in_threadpool(t.send, text)
        except Exception:
            log.exception("tutor failure")
            return JSONResponse({"error": "The tutor is unavailable right now. Please try again shortly."}, status_code=503)
        return {"reply": reply}

    @app.post("/api/tutor/reset")
    def tutor_reset(request: Request):
        user = current_user(request)
        if user:
            with tutors_lock:
                tutors.pop(user["email"], None)
        return {"ok": True}

    # ------------------------------------------------------------ survey
    @app.get("/survey", response_class=HTMLResponse)
    def survey_form(request: Request):
        user = need_user(request)
        if isinstance(user, RedirectResponse):
            return user
        return render(request, "survey.html")

    @app.post("/survey", response_class=HTMLResponse)
    def survey_submit(request: Request, overall: int = Form(...), learned: int = Form(...),
                      recommend: int = Form(...), comment: str = Form("")):
        user = need_user(request)
        if isinstance(user, RedirectResponse):
            return user
        clamp = lambda v, lo, hi: max(lo, min(hi, v))
        db.add_survey(user["email"], clamp(overall, 1, 5), clamp(learned, 1, 5), clamp(recommend, 0, 10), comment[:2000])
        return render(request, "message.html", title="Thank you", body="Your feedback has been recorded.")

    app.state.db, app.state.settings, app.state.send_login, app.state.mail = db, s, send_login, mail
    return app
