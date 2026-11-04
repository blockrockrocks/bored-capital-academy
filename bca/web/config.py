"""Web settings, all from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _env(name, default=""):
    return os.environ.get(name, default)


@dataclass
class Tier:
    key: str
    name: str
    price_display: str
    paddle_price_id: str
    features: list[str]
    highlight: bool = False


@dataclass
class Settings:
    base_url: str = field(default_factory=lambda: _env("BCA_BASE_URL", "http://localhost:8000").rstrip("/"))
    secret_key: str = field(default_factory=lambda: _env("BCA_SECRET_KEY", "dev-only-change-me"))
    db_path: Path = field(default_factory=lambda: Path(_env("BCA_DB", str(ROOT / "data" / "academy.sqlite3"))))
    data_dir: Path = field(default_factory=lambda: Path(_env("BCA_DATA_DIR", str(ROOT / "data"))))
    log_dir: Path = field(default_factory=lambda: Path(_env("BCA_LOG_DIR", str(ROOT / "logs"))))
    paddle_env: str = field(default_factory=lambda: _env("PADDLE_ENV", "sandbox"))
    paddle_client_token: str = field(default_factory=lambda: _env("PADDLE_CLIENT_TOKEN"))
    paddle_api_key: str = field(default_factory=lambda: _env("PADDLE_API_KEY"))
    paddle_webhook_secret: str = field(default_factory=lambda: _env("PADDLE_WEBHOOK_SECRET"))
    email_backend: str = field(default_factory=lambda: _env("EMAIL_BACKEND", "console"))  # console | smtp
    email_from: str = field(default_factory=lambda: _env("EMAIL_FROM", "Bored Capital Academy <hello@example.com>"))
    smtp_host: str = field(default_factory=lambda: _env("SMTP_HOST"))
    smtp_port: int = field(default_factory=lambda: int(_env("SMTP_PORT", "587")))
    smtp_user: str = field(default_factory=lambda: _env("SMTP_USER"))
    smtp_password: str = field(default_factory=lambda: _env("SMTP_PASSWORD"))
    tutor_daily_limit: int = field(default_factory=lambda: int(_env("TUTOR_DAILY_LIMIT", "40")))
    live_qa_info: str = field(default_factory=lambda: _env("LIVE_QA_INFO", "Schedule and joining link will be emailed before each session."))
    survey_after_days: int = field(default_factory=lambda: int(_env("SURVEY_AFTER_DAYS", "14")))
    # Optional video embed URLs for modules 1 and 2 (e.g. Bunny Stream / Vimeo embed links)
    video_urls: list[str] = field(default_factory=lambda: [u for u in _env("MODULE_VIDEO_URLS").split(",") if u])
    tiers: list[Tier] = field(default_factory=lambda: [
        Tier("self", "Self-paced", _env("PRICE_SELF_DISPLAY", "€89"), _env("PADDLE_PRICE_SELF"),
             ["Two video modules", "Ape Analytics Scorecard workbook", "AI tutor, 24/7",
              "One-page collection assessment", "Case studies: BAYC and Mudwater"]),
        Tier("live", "Self-paced + Live", _env("PRICE_LIVE_DISPLAY", "€179"), _env("PADDLE_PRICE_LIVE"),
             ["Everything in Self-paced", "Live group Q&A with the founder",
              "Feedback on your one-page assessment", "Priority answers to escalated questions"], highlight=True),
    ])

    def tier_for_price(self, price_id: str) -> Tier | None:
        return next((t for t in self.tiers if t.paddle_price_id and t.paddle_price_id == price_id), None)

    def tier(self, key: str) -> Tier | None:
        return next((t for t in self.tiers if t.key == key), None)

    @property
    def paddle_api_base(self) -> str:
        return "https://api.paddle.com" if self.paddle_env == "production" else "https://sandbox-api.paddle.com"
