"""Builds the Ape Analytics Scorecard workbook (.xlsx) from computed metrics."""
from __future__ import annotations

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

NAVY, TEAL, MIST, INPUT = "13213A", "0F7F7A", "F2F6F7", "FFF4C2"
H1 = Font(bold=True, size=16, color=NAVY)
H2 = Font(bold=True, size=12, color=TEAL)
HEAD = Font(bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor=NAVY)
INPUT_FILL = PatternFill("solid", fgColor=INPUT)
NOTE = Font(italic=True, size=9, color="5A6B7B")
THIN = Border(bottom=Side(style="thin", color="D5DEE3"))
WRAP = Alignment(wrap_text=True, vertical="top")

DISCLAIMER = ("Educational use only. Not investment advice. No number in this workbook is a target price, "
              "risk limit or buy/sell/hold recommendation. Bored Capital Academy is independent of Yuga Labs and BAYC.")

DIMENSIONS = [
    ("Liquidity and exit depth", 0.30,
     "0 = no meaningful bids / listings far apart · 3 = moderate spread, bid book absorbs a few tokens with modest discount · "
     "5 = tight spread, deep funded bids, low slippage for 10+ tokens"),
    ("Trading activity and quality", 0.20,
     "0 = sporadic or mostly flagged trades · 3 = regular trading, some concentration in few wallets · "
     "5 = trades most days, broad buyer/seller base, negligible wash flags"),
    ("Ownership and supply", 0.20,
     "0 = few wallets control most supply or large opaque contract holdings · 3 = some whales, caveats noted · "
     "5 = broadly distributed, low listed float, concentration well understood"),
    ("Benefits, rights and use cases", 0.15,
     "0 = undocumented or unused benefits · 3 = documented rights/utility with partial evidence of use · "
     "5 = clear licence terms, verifiable ongoing use, benefits independent of price"),
    ("Execution and transparency", 0.15,
     "0 = missed milestones, poor disclosure · 3 = mixed delivery record · "
     "5 = consistent delivery, transparent communication and data"),
]


def _header(ws, row, labels, widths=None):
    for i, label in enumerate(labels, 1):
        c = ws.cell(row=row, column=i, value=label)
        c.font, c.fill, c.alignment = HEAD, HEAD_FILL, WRAP
    if widths:
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[chr(64 + i)].width = w


def _rows(ws, start, rows, fmts=None):
    for r, values in enumerate(rows, start):
        for c, v in enumerate(values, 1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.border, cell.alignment = THIN, WRAP
            if fmts and c - 1 < len(fmts) and fmts[c - 1] and isinstance(v, (int, float)):
                cell.number_format = fmts[c - 1]
    return start + len(rows)


def _title(ws, title, sub):
    ws["A1"], ws["A1"].font = title, H1
    ws["A2"], ws["A2"].font = sub, NOTE
    ws["A3"], ws["A3"].font = DISCLAIMER, NOTE


def _kv(label, value, fmt, definition):
    return (label, value, fmt, definition)


def build_workbook(m: dict, path: str) -> str:
    col, mk, tr, ow = m["collection"], m["market"], m["trading"], m["ownership"]
    snap = m["snapshot_utc"]
    sub = f"{col.get('name') or col.get('slug')} · snapshot {snap} UTC"
    wb = Workbook()

    # ---- Read me
    ws = wb.active
    ws.title = "Read me"
    _title(ws, "Ape Analytics Scorecard — Bored Capital Academy", sub)
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 28, 100
    readme = [
        ("Collection", f"{col.get('name')} ({col.get('slug')})"),
        ("Contract / chain", f"{col.get('contract')} on {col.get('chain')}"),
        ("Snapshot (UTC)", snap),
        ("Purpose", "A structured research process: evidence, sources and documented uncertainty — not a magic alpha signal."),
        ("How to use", "1) Read Market snapshot, Ownership and Valuation scenarios. 2) Research the two manual dimensions. "
                       "3) Score each dimension 0–5 in the yellow cells on Scorecard. 4) Complete the One-page report."),
        ("Floor", "Cheapest live listing. An ask, not a price anyone has paid."),
        ("Best bid", "Highest live collection-wide offer (ETH/WETH). What you could sell one token for right now, if funded."),
        ("Headline market cap", "Floor × supply. A headline measure, NOT cash owners could collectively realise."),
        ("Exit curve", "Proceeds from selling N tokens straight into the current bid book, best bid first."),
        ("Wash-trade flags", "Self-trades, reciprocal buyer/seller pairs, or tokens traded 3+ times in the window. "
                             "Flags are prompts to investigate, not proof."),
        ("Wallets ≠ people", "One person can control many wallets; contract holders (vaults, escrow, lending) hide real owners."),
        ("Sources", "OpenSea API v2: collection info and stats, live listings, collection offers, sale events. "
                    "Every request is time-stamped on the Sources tab."),
        ("Limitations", "OpenSea only: other marketplaces' listings, bids and sales are excluded. Bids may be unfunded. "
                        "Ownership concentration is not automated (owner count only). "
                        "Rarity is ignored in comparable sales. Data reflects the snapshot time only."),
        ("Permitted use", DISCLAIMER),
    ]
    for r, (k, v) in enumerate(readme, 5):
        ws.cell(row=r, column=1, value=k).font = Font(bold=True)
        ws.cell(row=r, column=2, value=v).alignment = WRAP

    # ---- Market snapshot
    ws = wb.create_sheet("Market snapshot")
    _title(ws, "Market snapshot", sub)
    _header(ws, 4, ["Metric", "Value", "Definition"], [34, 18, 80])
    rep = m.get("opensea_reported") or {}
    kv = [
        _kv("Floor (cheapest listing)", mk.get("floor_eth"), "0.000 \"ETH\"", "Lowest live ETH listing price"),
        _kv("Best collection bid", mk.get("best_bid_eth"), "0.000 \"ETH\"", "Highest live collection-wide offer"),
        _kv("Bid/ask spread", mk.get("bid_ask_spread_pct"), "0.0%", "(Floor − best bid) / floor"),
        _kv("Listed tokens", mk.get("listed_tokens"), "#,##0", "Distinct tokens listed in ETH"),
        _kv("Listed float", mk.get("listed_float_pct"), "0.0%", "Listed tokens / supply"),
        _kv("Listings within 5% of floor", mk.get("listings_within_5pct"), "#,##0", "Depth near the ask"),
        _kv("Listings within 10% of floor", mk.get("listings_within_10pct"), "#,##0", ""),
        _kv("Bid units (all collection bids)", mk.get("bid_units_total"), "#,##0", "Tokens the bid book would absorb in total"),
        _kv("Distinct bidders", mk.get("bid_makers"), "#,##0", "Concentration of bid liquidity"),
        _kv("Bid book value", mk.get("bid_book_value_eth"), "#,##0.0 \"ETH\"", "Sum of every live collection bid"),
        _kv("Headline market cap", mk.get("headline_market_cap_eth"), "#,##0 \"ETH\"", "Floor × supply — headline only"),
        _kv("Bid book as % of headline cap", mk.get("bid_book_coverage_of_mcap_pct"), "0.00%", "How much of the headline could actually exit today"),
        _kv("Supply", mk.get("supply"), "#,##0", "Reported total supply"),
        _kv("OpenSea-reported floor", rep.get("reported_floor"), "0.000", "Cross-check against computed floor"),
        _kv("OpenSea-reported owners", rep.get("reported_owners"), "#,##0", "Wallets holding at least one token"),
    ]
    r = 5
    for label, v, fmt, d in kv:
        _rows(ws, r, [(label, v if v is not None else "n/a", d)])
        if isinstance(v, (int, float)):
            ws.cell(row=r, column=2).number_format = fmt
        r += 1
    r += 1
    ws.cell(row=r, column=1, value="Exit curve — selling into the bid book").font = H2
    r += 1
    _header(ws, r, ["Tokens sold", "Filled", "Avg price (ETH)", "Discount vs floor", "Proceeds (ETH)"])
    for c in "DE":
        ws.column_dimensions[c].width = 18
    r = _rows(ws, r + 1, [(e["units"], e["units_filled"], e["avg_price_eth"] or "n/a",
                          e["discount_vs_floor"] if e["discount_vs_floor"] is not None else "n/a", e["proceeds_eth"])
                         for e in mk.get("exit_curve", [])], ["0", "0", "0.000", "0.0%", "#,##0.00"])
    r += 1
    ws.cell(row=r, column=1, value=f"Trading activity and quality — last {tr.get('window_days')} days").font = H2
    r += 1
    _header(ws, r, ["Metric", "Value", "Definition"])
    trade_rows = [
        ("Sales", tr.get("n_sales"), "#,##0", "OpenSea sale events"),
        ("Volume (ETH-priced sales)", tr.get("volume_eth"), "#,##0.0", ""),

        ("Turnover", tr.get("turnover_pct"), "0.0%", "Distinct tokens traded / supply"),
        ("Unique buyers", tr.get("unique_buyers"), "#,##0", ""),
        ("Unique sellers", tr.get("unique_sellers"), "#,##0", ""),
        ("Active trading days", tr.get("active_days_pct"), "0%", "Share of days with ≥1 sale"),
        ("Flagged sales", tr.get("flagged_sales"), "#,##0", ", ".join(f"{k}: {v}" for k, v in (tr.get("flag_counts") or {}).items())),
        ("Flagged share of volume", tr.get("flagged_volume_share"), "0.0%", "Investigate before relying on volume"),
        ("Largest wallet pair share of volume", tr.get("top_pair_volume_share"), "0.0%", "High = volume driven by two wallets"),
        ("Median unflagged sale", tr.get("clean_price_p50"), "0.000 \"ETH\"", ""),

    ]
    for label, v, fmt, d in trade_rows:
        r += 1
        _rows(ws, r, [(label, v if v is not None else "n/a", d)])
        if fmt and isinstance(v, (int, float)):
            ws.cell(row=r, column=2).number_format = fmt

    # ---- Ownership
    ws = wb.create_sheet("Ownership")
    _title(ws, "Ownership and supply", sub)
    _header(ws, 4, ["Metric", "Value", "Note"], [34, 46, 60])
    own_rows = [
        ("Holder wallets", ow.get("holder_wallets"), "#,##0", "Burn addresses excluded"),
        ("Source", ow.get("source") or "Holder-level data", None, "Concentration rows need holder-level data; research manually"),
        ("Tokens per wallet", ow.get("tokens_per_wallet"), "0.00", ""),
        ("Top wallet share", ow.get("top1_share"), "0.0%", ""),
        ("Top 10 wallets share", ow.get("top10_share"), "0.0%", ""),
        ("Top 50 wallets share", ow.get("top50_share"), "0.0%", ""),
        ("Wallets controlling 50%", ow.get("wallets_controlling_50pct"), "#,##0", "Lower = more concentrated"),
        ("HHI (0–10,000)", ow.get("hhi"), "#,##0", "Herfindahl index of wallet shares"),
        ("Wallets with 10+ tokens", ow.get("wallets_10plus"), "#,##0", ""),
        ("Single-token wallets", ow.get("single_token_wallets_pct"), "0.0%", ""),
        ("Held by contracts", ow.get("contract_held_share"), "0.0%", "Vaults, escrow, lending, multisigs — real owner hidden"),
    ]
    r = 4
    for label, v, fmt, d in own_rows:
        r += 1
        _rows(ws, r, [(label, v if v is not None else "n/a", d)])
        if fmt and isinstance(v, (int, float)):
            ws.cell(row=r, column=2).number_format = fmt
    r += 2
    ws.cell(row=r, column=1, value="Top holders (cluster caveat: wallets are not people)").font = H2
    r += 1
    _header(ws, r, ["Rank", "Wallet", "Tokens", "Share", "Contract?"])
    ws.column_dimensions["D"].width, ws.column_dimensions["E"].width = 10, 10
    _rows(ws, r + 1, [(i, h["owner"], h["tokens"], h["share"], "yes" if h["is_contract"] else "")
                      for i, h in enumerate(ow.get("top_holders", []), 1)], ["0", None, "#,##0", "0.00%", None])

    # ---- Valuation scenarios
    ws = wb.create_sheet("Valuation scenarios")
    _title(ws, "Valuation scenarios — indicative reference points, not a 'correct price'", sub)
    _header(ws, 4, ["Reference point", "ETH", "Method", "Key assumption"], [34, 14, 44, 60])
    vs = m["valuation_scenarios"]
    end = _rows(ws, 5, [(s["scenario"], s["value_eth"] if s["value_eth"] is not None else "n/a",
                         s["method"], s["key_assumption"]) for s in vs], [None, "0.000"])
    vals = [s["value_eth"] for s in vs if s["value_eth"]]
    ws.cell(row=end + 1, column=1, value="Indicative range").font = Font(bold=True)
    ws.cell(row=end + 1, column=2, value=f"{min(vals):.3f} – {max(vals):.3f}" if vals else "n/a")
    ws.cell(row=end + 1, column=3, value="Spread between immediate exit and patient sale = the liquidity discount")
    ws.cell(row=end + 3, column=1, value="Your assumptions").font = H2
    for i, prompt in enumerate(["Which reference point fits a realistic exit for you, and why?",
                                "What would make the range wider or narrower?",
                                "Which data would change your view?"], end + 4):
        ws.cell(row=i, column=1, value=prompt).alignment = WRAP
        cell = ws.cell(row=i, column=2)
        cell.fill = INPUT_FILL
        ws.merge_cells(start_row=i, start_column=2, end_row=i, end_column=4)
        ws.row_dimensions[i].height = 45

    # ---- Scorecard
    ws = wb.create_sheet("Scorecard")
    _title(ws, "Scorecard — rate each dimension 0–5 using the written criteria", sub)
    _header(ws, 4, ["Dimension", "Weight", "Written criteria", "Auto-filled evidence", "Data confidence",
                    "Your score (0–5)", "Weighted (0–100)", "Unresolved data issues"])
    for c, w in zip("ABCDEFGH", [28, 9, 52, 52, 14, 12, 12, 44]):
        ws.column_dimensions[c].width = w
    ev = {
        "Liquidity and exit depth": _fmt_ev([("Spread", mk.get("bid_ask_spread_pct"), "%"),
                                             ("Bid units", mk.get("bid_units_total"), "n"),
                                             ("Listed float", mk.get("listed_float_pct"), "%"),
                                             ("10-token exit discount", _exit(mk, 10), "%")]),
        "Trading activity and quality": _fmt_ev([("Sales", tr.get("n_sales"), "n"), ("Turnover", tr.get("turnover_pct"), "%"),
                                                 ("Active days", tr.get("active_days_pct"), "%"),
                                                 ("Flagged volume", tr.get("flagged_volume_share"), "%")]),
        "Ownership and supply": _fmt_ev([("Wallets", ow.get("holder_wallets"), "n"), ("Top 10", ow.get("top10_share"), "%"),
                                         ("Wallets for 50%", ow.get("wallets_controlling_50pct"), "n"),
                                         ("Contract-held", ow.get("contract_held_share"), "%")]),
        "Benefits, rights and use cases": "Research: licence terms, documented utilities, evidence of actual use. Cite sources.",
        "Execution and transparency": "Research: roadmap delivery, disclosures, communication record. Cite sources.",
    }
    dv = DataValidation(type="decimal", operator="between", formula1="0", formula2="5", allow_blank=True,
                        showErrorMessage=True, error="Enter a score from 0 to 5")
    ws.add_data_validation(dv)
    for r, (dim, w, crit) in enumerate(DIMENSIONS, 5):
        conf = m["confidence"][dim]
        vals = [dim, w, crit, ev[dim], conf["level"], None, f'=IF(F{r}="","",B{r}*F{r}/5*100)', "; ".join(conf["notes"])]
        _rows(ws, r, [vals])
        ws.cell(row=r, column=2).number_format = "0%"
        ws.cell(row=r, column=6).fill = INPUT_FILL
        ws.cell(row=r, column=7).number_format = "0.0"
        dv.add(f"F{r}")
        ws.row_dimensions[r].height = 75
    ws["A11"], ws["A11"].font = "Weighted score (for discussion only)", Font(bold=True)
    ws["G11"] = '=IF(COUNT(F5:F9)<5,"Score all 5",SUM(G5:G9))'
    ws["G11"].font = Font(bold=True, color=TEAL)
    ws["G11"].number_format = "0.0"
    ws["A12"] = "This score is not a target price, risk limit or recommendation. Always read it alongside data confidence."
    ws["A12"].font = NOTE

    # ---- One-page report
    ws = wb.create_sheet("One-page report")
    _title(ws, f"Collection assessment — {col.get('name')}", sub)
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 30, 90
    report = [
        ("Market snapshot", f"Floor {_e(mk.get('floor_eth'))} · best bid {_e(mk.get('best_bid_eth'))} · spread "
                            f"{_p(mk.get('bid_ask_spread_pct'))} · {mk.get('listed_tokens')} listed ({_p(mk.get('listed_float_pct'))} of supply) · "
                            f"snapshot {snap} UTC"),
        ("Liquidity score (0–5)", "=IF('Scorecard'!F5=\"\",\"not scored yet\",'Scorecard'!F5)"),
        ("Weighted score", "='Scorecard'!G11"),
        ("Ownership observations", None), ("Rights and utility summary", None), ("Principal risks", None),
        ("Key assumptions", None), ("Sources", "See Sources tab, plus any primary sources you used:"),
        ("One unanswered question", None),
    ]
    for r, (k, v) in enumerate(report, 4):
        ws.cell(row=r, column=1, value=k).font = Font(bold=True)
        c = ws.cell(row=r, column=2, value=v)
        c.alignment = WRAP
        if v is None or k == "Sources":
            c.fill = INPUT_FILL
            ws.row_dimensions[r].height = 50

    # ---- Sources
    ws = wb.create_sheet("Sources")
    _title(ws, "Source log", sub)
    _header(ws, 4, ["#", "Source", "Request", "Parameters", "Fetched (UTC)", "HTTP", "Raw file"], [5, 10, 70, 40, 22, 8, 30])
    _rows(ws, 5, [(s["n"], s["source"], f'{s["method"]} {s["url"]}',
                   str({**s.get("params", {}), **s.get("body", {})}) or "", s["fetched_at_utc"], s["http_status"], s["file"])
                  for s in m.get("sources", [])])

    for sheet in wb.worksheets:
        sheet.sheet_view.showGridLines = False
        sheet.freeze_panes = "A5" if sheet.title != "Read me" else None
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.fitToWidth, sheet.page_setup.fitToHeight = 1, 0
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
    wb.save(path)
    return path


def _exit(mk, n):
    row = next((e for e in mk.get("exit_curve", []) if e["units"] == n), None)
    return row and row["discount_vs_floor"]


def _e(v):
    return f"{v:.3f} ETH" if isinstance(v, (int, float)) else "n/a"


def _p(v):
    return f"{v:.1%}" if isinstance(v, (int, float)) else "n/a"


def _fmt_ev(items):
    out = []
    for label, v, kind in items:
        out.append(f"{label}: {'n/a' if v is None else (_p(v) if kind == '%' else f'{v:,.0f}')}")
    return " · ".join(out)
