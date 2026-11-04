"""HTTP fetching with a dated source log.

Every API response is saved verbatim under <run_dir>/raw/ and recorded in
sources.json (URL, parameters, UTC time, HTTP status). API keys travel in
headers only and are never written to disk.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

RETRY_STATUSES = {429, 500, 502, 503, 504}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SourceLog:
    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.raw_dir = self.run_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.entries: list[dict] = []

    def fetch(self, session: requests.Session, method: str, url: str, *, source: str,
              label: str, params: dict | None = None, json_body: dict | None = None,
              headers: dict | None = None, retries: int = 4) -> dict:
        for attempt in range(retries + 1):
            resp = session.request(method, url, params=params, json=json_body,
                                   headers=headers, timeout=60)
            if resp.status_code not in RETRY_STATUSES or attempt == retries:
                break
            wait = float(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
            time.sleep(min(wait, 60))
        fetched_at = utc_now()
        try:
            data = resp.json()
        except ValueError:
            data = {"_non_json_body": resp.text[:2000]}
        fname = f"{len(self.entries):03d}_{label}.json"
        (self.raw_dir / fname).write_text(json.dumps(data, indent=1))
        self.entries.append({
            "n": len(self.entries), "source": source, "label": label, "method": method,
            "url": url, "params": params or {}, "body": json_body or {},
            "fetched_at_utc": fetched_at, "http_status": resp.status_code,
            "file": f"raw/{fname}",
        })
        if resp.status_code >= 400:
            raise RuntimeError(f"{source} {label}: HTTP {resp.status_code}: {str(data)[:300]}")
        return data

    def save(self) -> None:
        (self.run_dir / "sources.json").write_text(json.dumps(self.entries, indent=1))
