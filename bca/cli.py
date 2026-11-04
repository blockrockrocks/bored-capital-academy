"""Command line: bca snapshot | workbook | run | tutor | web"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import opensea as os_mod
from .metrics import compute_all
from .sources import SourceLog, utc_now
from .workbook import build_workbook


def _env(name: str, required: bool = True) -> str | None:
    v = os.environ.get(name)
    if required and not v:
        sys.exit(f"Missing environment variable {name} (see README).")
    return v


def snapshot(slug: str, days: int, out: Path) -> Path:
    run_dir = out / slug / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log = SourceLog(run_dir)
    meta = {"snapshot_utc": utc_now(), "window_days": days}
    try:
        osc = os_mod.OpenSea(_env("OPENSEA_API_KEY"), log)
        collection = os_mod.parse_collection(osc.collection(slug))
        stats = os_mod.parse_stats(osc.stats(slug))
        raw_l, meta["listings_truncated"] = osc.best_listings(slug)
        raw_o, meta["offers_truncated"] = osc.collection_offers(slug)
        raw_s, meta["sales_truncated"] = osc.sales(slug, int(time.time()) - days * 86400)
        listings, meta["listings_skipped"] = os_mod.parse_listings(raw_l)
        offers, meta["offers_skipped"] = os_mod.parse_offers(raw_o)
        trades, meta["sales_skipped"] = os_mod.parse_sales(raw_s)
    finally:
        log.save()

    norm = {"collection": collection, "stats": stats, "listings": listings, "offers": offers,
            "holders": [], "trades": trades, "meta": meta}
    (run_dir / "normalized.json").write_text(json.dumps(norm, indent=1))
    print(f"Snapshot saved: {run_dir}\n  listings {len(listings)} (skipped {meta['listings_skipped']}), "
          f"bids {len(offers)} (skipped {meta['offers_skipped']}), sales {len(trades)} (skipped {meta['sales_skipped']})")
    return run_dir


def latest_run(path: Path) -> Path:
    if (path / "normalized.json").exists():
        return path
    runs = sorted(p for p in path.iterdir() if (p / "normalized.json").exists()) if path.exists() else []
    if not runs:
        sys.exit(f"No snapshot found under {path}")
    return runs[-1]


def workbook(run_dir: Path, out: Path | None) -> Path:
    norm = json.loads((run_dir / "normalized.json").read_text())
    m = compute_all(norm)
    m["sources"] = json.loads((run_dir / "sources.json").read_text()) if (run_dir / "sources.json").exists() else []
    (run_dir / "metrics.json").write_text(json.dumps(m, indent=1, default=str))
    slug = norm["collection"].get("slug") or run_dir.parent.name
    out = out or run_dir / f"Ape_Analytics_Scorecard_{slug}_{run_dir.name}.xlsx"
    build_workbook(m, str(out))
    print(f"Workbook: {out}\nMetrics:  {run_dir / 'metrics.json'}")
    return out


def tutor_cmd(a) -> None:
    from . import tutor, tutor_redteam
    if a.action == "review":
        print(tutor.review(a.logs, a.days))
    elif a.action == "redteam":
        sys.exit(1 if tutor_redteam.run(a.data) else 0)
    else:
        t = tutor.Tutor(student=a.student, data_dir=a.data, log_dir=a.logs)
        print("Bored Capital Academy tutor — type 'exit' to quit. Educational use only; not investment advice.\n")
        while True:
            try:
                q = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if q.lower() in {"exit", "quit"}:
                break
            if q:
                print(f"\ntutor> {t.send(q)}\n")
        print(f"Conversation log: {t.log_path}")


def web_cmd(a) -> None:
    from .web import mailer, ops
    from .web.config import Settings
    from .web.db import DB
    s = Settings()
    if a.action == "serve":
        import uvicorn
        from .web.app import create_app
        if s.secret_key == "dev-only-change-me":
            print("WARNING: BCA_SECRET_KEY is the development default. Set a long random value in production.")
        uvicorn.run(create_app(s), host=a.host, port=a.port, proxy_headers=True)
    elif a.action == "followups":
        print(f"Survey emails sent: {ops.followups(s, DB(s.db_path), mailer.Mailer(s))}")
    elif a.action == "stats":
        print(ops.stats(DB(s.db_path)))
    elif a.action == "simulate-purchase":
        if not a.email:
            sys.exit("--email is required")
        print(ops.simulate_purchase(s, a.email, a.tier))


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="bca", description="Bored Capital Academy data pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("snapshot", "run"):
        s = sub.add_parser(name)
        s.add_argument("slug", help="OpenSea collection slug, e.g. boredapeyachtclub")
        s.add_argument("--days", type=int, default=30, help="trading window (default 30)")
        s.add_argument("--data", type=Path, default=Path("data"))
        s.add_argument("--out", type=Path, default=None, help="workbook path (run only)")
    w = sub.add_parser("workbook")
    w.add_argument("path", type=Path, help="run directory, or data/<slug> for the latest run")
    w.add_argument("--out", type=Path, default=None)
    t = sub.add_parser("tutor", help="AI tutor: chat | review | redteam")
    t.add_argument("action", choices=["chat", "review", "redteam"])
    t.add_argument("--student", default="anonymous")
    t.add_argument("--days", type=int, default=7, help="review window")
    t.add_argument("--data", type=Path, default=Path("data"))
    t.add_argument("--logs", type=Path, default=Path("logs"))
    w2 = sub.add_parser("web", help="website: serve | followups | stats | simulate-purchase")
    w2.add_argument("action", choices=["serve", "followups", "stats", "simulate-purchase"])
    w2.add_argument("--host", default="127.0.0.1")
    w2.add_argument("--port", type=int, default=8000)
    w2.add_argument("--email")
    w2.add_argument("--tier", default="self", choices=["self", "live"])
    a = p.parse_args(argv)

    if a.cmd == "web":
        return web_cmd(a)
    if a.cmd == "tutor":
        return tutor_cmd(a)

    if a.cmd == "snapshot":
        snapshot(a.slug, a.days, a.data)
    elif a.cmd == "run":
        workbook(snapshot(a.slug, a.days, a.data), a.out)
    elif a.cmd == "workbook":
        workbook(latest_run(a.path), a.out)


if __name__ == "__main__":
    main()
