"""Dune API client: execute saved queries with parameters and fetch all rows."""
from __future__ import annotations

import time
from pathlib import Path

import requests

from .sources import SourceLog

BASE = "https://api.dune.com/api/v1"
SQL_DIR = Path(__file__).resolve().parent.parent / "dune"
QUERIES = {
    "holders": {"file": "holders.sql", "params": {"contract": "0xbc4ca0eda7647a8ab7c2061c2e118a18a936f13d"}},
    "trades": {"file": "trades.sql", "params": {"contract": "0xbc4ca0eda7647a8ab7c2061c2e118a18a936f13d", "days": "30"}},
}


class Dune:
    def __init__(self, api_key: str, log: SourceLog | None, session: requests.Session | None = None):
        self.log = log
        self.s = session or requests.Session()
        self.headers = {"X-Dune-API-Key": api_key}

    def _call(self, method, path, label, params=None, body=None):
        if self.log is None:  # setup commands don't need a run directory
            r = self.s.request(method, BASE + path, params=params, json=body, headers=self.headers, timeout=60)
            r.raise_for_status()
            return r.json()
        return self.log.fetch(self.s, method, BASE + path, source="Dune", label=label,
                              params=params, json_body=body, headers=self.headers)

    def create_query(self, name: str, sql: str, params: dict) -> int:
        body = {"name": name, "query_sql": sql, "is_private": False,
                "parameters": [{"key": k, "type": "text", "value": v} for k, v in params.items()]}
        return int(self._call("POST", "/query", "create", body=body)["query_id"])

    def run(self, query_id: int, params: dict, label: str, timeout_s: int = 600) -> list[dict]:
        ex = self._call("POST", f"/query/{query_id}/execute", f"{label}_execute",
                        body={"query_parameters": params})
        eid = ex["execution_id"]
        deadline = time.time() + timeout_s
        while True:
            # status polls are not logged to disk; only the final results are evidence
            r = self.s.get(f"{BASE}/execution/{eid}/status", headers=self.headers, timeout=60)
            r.raise_for_status()
            state = r.json().get("state")
            if state == "QUERY_STATE_COMPLETED":
                break
            if state in {"QUERY_STATE_FAILED", "QUERY_STATE_CANCELLED", "QUERY_STATE_EXPIRED"}:
                raise RuntimeError(f"Dune query {query_id} ended in {state}: {r.json()}")
            if time.time() > deadline:
                raise TimeoutError(f"Dune query {query_id} still {state} after {timeout_s}s")
            time.sleep(3)
        rows, offset, page = [], 0, 0
        while True:
            data = self._call("GET", f"/execution/{eid}/results", f"{label}_rows_p{page}",
                              params={"limit": 5000, "offset": offset})
            rows.extend((data.get("result") or {}).get("rows") or [])
            if data.get("next_offset") is None:
                return rows
            offset, page = data["next_offset"], page + 1
