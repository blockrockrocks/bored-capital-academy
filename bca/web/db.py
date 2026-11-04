"""SQLite storage: students, processed webhook events, tutor usage, surveys, sent emails."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
  email TEXT PRIMARY KEY, tier TEXT NOT NULL, status TEXT NOT NULL,
  paddle_transaction_id TEXT, paddle_customer_id TEXT, amount TEXT, currency TEXT,
  enrolled_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS webhook_events (event_id TEXT PRIMARY KEY, event_type TEXT, received_at TEXT);
CREATE TABLE IF NOT EXISTS used_tokens (nonce TEXT PRIMARY KEY, used_at TEXT);
CREATE TABLE IF NOT EXISTS tutor_usage (email TEXT, day TEXT, count INTEGER, PRIMARY KEY (email, day));
CREATE TABLE IF NOT EXISTS surveys (
  email TEXT, submitted_at TEXT, overall INTEGER, learned INTEGER, recommend INTEGER, comment TEXT);
CREATE TABLE IF NOT EXISTS emails_sent (email TEXT, kind TEXT, sent_at TEXT, PRIMARY KEY (email, kind));
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class DB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # events (webhook idempotency)
    def claim_event(self, event_id: str, event_type: str) -> bool:
        with self.conn() as c:
            cur = c.execute("INSERT OR IGNORE INTO webhook_events VALUES (?,?,?)", (event_id, event_type, now()))
            return cur.rowcount == 1

    # students
    def upsert_student(self, email, tier, txn_id, customer_id, amount, currency):
        with self.conn() as c:
            existing = c.execute("SELECT tier FROM students WHERE email=?", (email,)).fetchone()
            # never downgrade: buying Self-paced after Live keeps Live
            if existing and existing["tier"] == "live":
                tier = "live"
            c.execute("""INSERT INTO students VALUES (?,?,?,?,?,?,?,?,?)
                         ON CONFLICT(email) DO UPDATE SET tier=excluded.tier, status='active',
                         paddle_transaction_id=excluded.paddle_transaction_id, amount=excluded.amount,
                         currency=excluded.currency, updated_at=excluded.updated_at""",
                      (email, tier, "active", txn_id, customer_id, amount, currency, now(), now()))

    def student(self, email: str):
        with self.conn() as c:
            return c.execute("SELECT * FROM students WHERE email=?", (email,)).fetchone()

    def revoke_by_transaction(self, txn_id: str) -> str | None:
        with self.conn() as c:
            row = c.execute("SELECT email FROM students WHERE paddle_transaction_id=?", (txn_id,)).fetchone()
            if row:
                c.execute("UPDATE students SET status='refunded', updated_at=? WHERE email=?", (now(), row["email"]))
                return row["email"]
        return None

    def students(self):
        with self.conn() as c:
            return c.execute("SELECT * FROM students ORDER BY enrolled_at").fetchall()

    # magic-link tokens are single use
    def use_nonce(self, nonce: str) -> bool:
        with self.conn() as c:
            return c.execute("INSERT OR IGNORE INTO used_tokens VALUES (?,?)", (nonce, now())).rowcount == 1

    # tutor rate limit
    def tutor_hit(self, email: str, limit: int) -> bool:
        day = now()[:10]
        with self.conn() as c:
            row = c.execute("SELECT count FROM tutor_usage WHERE email=? AND day=?", (email, day)).fetchone()
            if row and row["count"] >= limit:
                return False
            c.execute("""INSERT INTO tutor_usage VALUES (?,?,1)
                         ON CONFLICT(email, day) DO UPDATE SET count=count+1""", (email, day))
            return True

    # surveys
    def add_survey(self, email, overall, learned, recommend, comment):
        with self.conn() as c:
            c.execute("INSERT INTO surveys VALUES (?,?,?,?,?,?)", (email, now(), overall, learned, recommend, comment))

    def surveys(self):
        with self.conn() as c:
            return c.execute("SELECT * FROM surveys").fetchall()

    # emails
    def mark_sent(self, email: str, kind: str) -> bool:
        with self.conn() as c:
            return c.execute("INSERT OR IGNORE INTO emails_sent VALUES (?,?,?)", (email, kind, now())).rowcount == 1
