"""Command line: bca snapshot | workbook | run | dune-setup"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import dune as dune_mod
from . import opensea as os_mod
from .metrics import compute_all
from .sources import SourceLog, utc_now
from .workbook import build_workbook


def _env(name: str, required: bool = True) -> str | None:
    v = os.environ.get(name)
    if required and not v:
        sys.exit(f"Missing environment variable {name} (see README).")
    return v


def snapshot(slug: str, days: int, out: Path, skip_dune: bool = False) -> Path:
    run_dir = out / slug / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log = SourceLog(run_dir)
    meta = {"snapshot_utc": utc_now(), "window_days": days, "dune": False}
    try:
        osc = os_mod.OpenSea(_env("OPENSEA_API_KEY"), log)
        collection = os_mod.parse_collection(osc.collection(slug))
        stats = os_mod.parse_stats(osc.stats(slug))
        raw_l, meta["listings_truncated"] = osc.best_listings(slug)
        raw_o, meta["offers_truncated"] = osc.collection_offers(slug)
        listings, meta["listings_skipped"] = os_mod.parse_listings(raw_l)
        offers, meta["offers_skipped"] = os_mod.parse_offers(raw_o)

        holders, trades = [], []
        dkey = None if skip_dune else _env("DUNE_API_KEY", required=False)
        if dkey and collection["contract"]:
            if (collection.get("chain") or "ethereum") != "ethereum":
                print(f"Note: Dune SQL is Ethereum-only; {slug} is on {collection['chain']} — skipping Dune.")
            else:
                d = dune_mod.Dune(dkey, log)
                holders = d.run(int(_env("DUNE_QUERY_HOLDERS")), {"contract": collection["contract"]}, "dune_holders")
                trades = d.run(int(_env("DUNE_QUERY_TRADES")), {"contract": collection["contract"], "days": str(days)}, "dune_trades")
                meta["dune"] = True
        elif not skip_dune:
            print("DUNE_API_KEY not set — ownership and trading tabs will be empty.")
    finally:
        log.save()

    norm = {"collection": collection, "stats": stats, "listings": listings, "offers": offers,
            "holders": holders, "trades": trades, "meta": meta}
    (run_dir / "normalized.json").write_text(json.dumps(norm, indent=1))
    print(f"Snapshot saved: {run_dir}")
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


def dune_setup() -> None:
    d = dune_mod.Dune(_env("DUNE_API_KEY"), None)
    for name, spec in dune_mod.QUERIES.items():
        sql = (dune_mod.SQL_DIR / spec["file"]).read_text()
        qid = d.create_query(f"Bored Capital Academy — {name}", sql, spec["params"])
        print(f"export DUNE_QUERY_{name.upper()}={qid}")
    print("Add these lines to your .env (or shell profile).")


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


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="bca", description="Bored Capital Academy data pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("snapshot", "run"):
        s = sub.add_parser(name)
        s.add_argument("slug", help="OpenSea collection slug, e.g. boredapeyachtclub")
        s.add_argument("--days", type=int, default=30, help="trading window (default 30)")
        s.add_argument("--data", type=Path, default=Path("data"))
        s.add_argument("--no-dune", action="store_true")
        s.add_argument("--out", type=Path, default=None, help="workbook path (run only)")
    w = sub.add_parser("workbook")
    w.add_argument("path", type=Path, help="run directory, or data/<slug> for the latest run")
    w.add_argument("--out", type=Path, default=None)
    sub.add_parser("dune-setup")
    t = sub.add_parser("tutor", help="AI tutor: chat | review | redteam")
    t.add_argument("action", choices=["chat", "review", "redteam"])
    t.add_argument("--student", default="anonymous")
    t.add_argument("--days", type=int, default=7, help="review window")
    t.add_argument("--data", type=Path, default=Path("data"))
    t.add_argument("--logs", type=Path, default=Path("logs"))
    a = p.parse_args(argv)

    if a.cmd == "tutor":
        return tutor_cmd(a)

    if a.cmd == "dune-setup":
        dune_setup()
    elif a.cmd == "snapshot":
        snapshot(a.slug, a.days, a.data, a.no_dune)
    elif a.cmd == "run":
        workbook(snapshot(a.slug, a.days, a.data, a.no_dune), a.out)
    elif a.cmd == "workbook":
        workbook(latest_run(a.path), a.out)


if __name__ == "__main__":
    main()
