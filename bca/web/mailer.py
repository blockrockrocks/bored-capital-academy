"""Outgoing email. 'console' backend writes .eml files to logs/outbox (development);
'smtp' works with any provider (Postmark, Brevo, SES, Fastmail...)."""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from pathlib import Path

from .db import now


class Mailer:
    def __init__(self, settings):
        self.s = settings

    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.s.email_from, to, subject
        msg.set_content(body + "\n\n—\nBored Capital Academy · BlockRock OÜ\n"
                        "Educational content only, not investment advice. Independent of Yuga Labs and BAYC.\n",
                        cte="8bit")  # keeps long login links on one line (no quoted-printable wrapping)
        if self.s.email_backend == "smtp":
            with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=30) as smtp:
                smtp.starttls()
                if self.s.smtp_user:
                    smtp.login(self.s.smtp_user, self.s.smtp_password)
                smtp.send_message(msg)
        else:
            out = Path(self.s.log_dir) / "outbox"
            out.mkdir(parents=True, exist_ok=True)
            safe = "".join(ch if ch.isalnum() else "_" for ch in to)
            (out / f"{now().replace(':', '')}_{safe}_{subject[:30].replace(' ', '_')}.eml").write_bytes(bytes(msg))
            print(f"[email → {to}] {subject}")


def welcome(base_url, tier_name, link):
    return ("Welcome to The NFT Investor's Playbook",
            f"Thanks for joining Bored Capital Academy ({tier_name}).\n\n"
            f"Open your course here (link valid for 24 hours, single use):\n{link}\n\n"
            f"Any time later, request a fresh link at {base_url}/login.\n\n"
            "Start with Module 1, then try the Ape Analytics Scorecard on a collection you know. "
            "The AI tutor is available inside the course whenever you're stuck.\n\n"
            "Your receipt and invoice come separately from Paddle, our payment provider.")


def login_link(link):
    return ("Your Bored Capital Academy login link",
            f"Here's your login link (valid for 24 hours, single use):\n{link}\n\n"
            "If you didn't ask for this, you can ignore this email.")


def survey(link):
    return ("Two minutes of feedback?",
            "You've had the course for a couple of weeks. What worked, and what didn't?\n"
            f"The survey takes two minutes: {link}\n\nYour answers shape the next version of the course.")
