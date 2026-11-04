"""Pure metric calculations for the Ape Analytics Scorecard.

No network access here; everything takes normalized lists and returns dicts,
so the same numbers feed the workbook, the AI tutor and the content agent.
Nothing in this module produces a price target or recommendation.
"""
from __future__ import annotations

from collections import Counter, defaultdict

BURN = {"0x0000000000000000000000000000000000000000", "0x000000000000000000000000000000000000dead"}
EXIT_SIZES = (1, 5, 10, 25, 50, 100)


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    pos = (len(v) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def _div(a, b):
    return a / b if a is not None and b else None


# ---------------------------------------------------------------- liquidity
def exit_curve(offers: list[dict], floor: float | None, sizes=EXIT_SIZES) -> list[dict]:
    """Sell N tokens straight into the collection bid book, best bid first."""
    book = sorted(offers, key=lambda o: -o["price_eth"])
    total_units = sum(o["units"] for o in book)
    rows = []
    for n in sizes:
        left, proceeds = n, 0.0
        for o in book:
            take = min(left, o["units"])
            proceeds += take * o["price_eth"]
            left -= take
            if left == 0:
                break
        filled = n - left
        avg = proceeds / filled if filled else None
        rows.append({
            "units": n, "units_filled": filled, "proceeds_eth": proceeds, "avg_price_eth": avg,
            "discount_vs_floor": (1 - avg / floor) if avg and floor else None,
            "fully_filled": filled == n, "book_units_total": total_units,
        })
    return rows


def market_snapshot(listings: list[dict], offers: list[dict], supply: int | None) -> dict:
    prices = sorted(l["price_eth"] for l in listings)
    floor = prices[0] if prices else None
    bids = sorted((o["price_eth"] for o in offers), reverse=True)
    best_bid = bids[0] if bids else None
    bid_units = sum(o["units"] for o in offers)
    bid_book_value = sum(o["price_eth"] * o["units"] for o in offers)
    depth = {f"listings_within_{int(p*100)}pct": (sum(1 for x in prices if x <= floor * (1 + p)) if floor else 0)
             for p in (0.02, 0.05, 0.10, 0.25)}
    headline_mcap = floor * supply if floor and supply else None
    return {
        "floor_eth": floor,
        "best_bid_eth": best_bid,
        "bid_ask_spread_pct": (floor - best_bid) / floor if floor and best_bid else None,
        "listed_tokens": len(prices),
        "listed_float_pct": _div(len(prices), supply),
        **depth,
        "bid_units_total": bid_units,
        "bid_book_value_eth": bid_book_value,
        "bid_makers": len({o.get("maker") for o in offers if o.get("maker")}),
        "headline_market_cap_eth": headline_mcap,
        "bid_book_coverage_of_mcap_pct": _div(bid_book_value, headline_mcap),
        "supply": supply,
        "exit_curve": exit_curve(offers, floor),
    }


# ---------------------------------------------------------- trading quality
def trading_quality(trades: list[dict], supply: int | None, window_days: int) -> dict:
    if not trades:
        return {"n_sales": 0, "window_days": window_days}
    norm = []
    for t in trades:
        norm.append({
            "token": str(t.get("token_id")), "buyer": (t.get("buyer") or "").lower(),
            "seller": (t.get("seller") or "").lower(), "day": str(t.get("block_time", ""))[:10],
            "eth": float(t["amount_original"]) if (t.get("currency_symbol") or "").upper() in {"ETH", "WETH"}
                   and t.get("amount_original") is not None else None,
            "usd": float(t["amount_usd"]) if t.get("amount_usd") is not None else None,
            "venue": t.get("project") or "unknown",
        })
    directed = {(t["seller"], t["buyer"]) for t in norm}
    token_counts = Counter(t["token"] for t in norm)
    for t in norm:
        reasons = []
        if t["buyer"] and t["buyer"] == t["seller"]:
            reasons.append("self-trade")
        if (t["buyer"], t["seller"]) in directed and t["buyer"] != t["seller"]:
            reasons.append("reciprocal pair")
        if token_counts[t["token"]] >= 3:
            reasons.append("token traded 3+ times")
        t["flags"] = reasons
    flagged = [t for t in norm if t["flags"]]
    clean_eth = [t["eth"] for t in norm if not t["flags"] and t["eth"]]
    # Volume shares use USD when every trade has it, otherwise ETH-priced sales
    use_usd = all(t["usd"] is not None for t in norm)
    w = (lambda t: t["usd"] or 0) if use_usd else (lambda t: t["eth"] or 0)
    total_usd = sum(w(t) for t in norm)
    pair_usd = defaultdict(float)
    for t in norm:
        pair_usd[tuple(sorted((t["buyer"], t["seller"])))] += w(t)
    venues = Counter()
    for t in norm:
        venues[t["venue"]] += w(t)
    return {
        "window_days": window_days,
        "n_sales": len(norm),
        "volume_eth": sum(t["eth"] or 0 for t in norm),
        "volume_usd": total_usd if use_usd else None,
        "share_basis": "USD" if use_usd else "ETH",
        "unique_tokens_traded": len(token_counts),
        "turnover_pct": _div(len(token_counts), supply),
        "unique_buyers": len({t["buyer"] for t in norm}),
        "unique_sellers": len({t["seller"] for t in norm}),
        "active_trading_days": len({t["day"] for t in norm}),
        "active_days_pct": len({t["day"] for t in norm}) / window_days if window_days else None,
        "flagged_sales": len(flagged),
        "flagged_volume_share": _div(sum(w(t) for t in flagged), total_usd),
        "flag_counts": dict(Counter(r for t in flagged for r in t["flags"])),
        "top_pair_volume_share": _div(max(pair_usd.values(), default=0), total_usd),
        "venue_volume_share": {k: v / total_usd for k, v in venues.most_common()} if total_usd else {},
        "clean_sales_with_eth_price": len(clean_eth),
        "clean_price_p10": quantile(clean_eth, 0.10), "clean_price_p25": quantile(clean_eth, 0.25),
        "clean_price_p50": quantile(clean_eth, 0.50), "clean_price_p75": quantile(clean_eth, 0.75),
        "clean_price_p90": quantile(clean_eth, 0.90),
    }


# --------------------------------------------------------------- ownership
def ownership_from_owner_count(owners: int | None, supply: int | None) -> dict:
    """OpenSea only reports the number of owner wallets; concentration needs holder-level data."""
    if not owners:
        return {"holder_wallets": 0}
    return {"holder_wallets": owners, "tokens_counted": None, "supply": supply,
            "tokens_per_wallet": supply / owners if supply else None, "source": "OpenSea owner count",
            "top1_share": None, "top10_share": None, "top50_share": None, "wallets_controlling_50pct": None,
            "hhi": None, "wallets_10plus": None, "single_token_wallets_pct": None, "contract_held_share": None,
            "top_holders": []}


def ownership(holders: list[dict], supply: int | None) -> dict:
    rows = [(str(h["owner"]).lower(), int(h["tokens"]), bool(int(h.get("is_contract") or 0)))
            for h in holders if str(h.get("owner", "")).lower() not in BURN and int(h.get("tokens") or 0) > 0]
    if not rows:
        return {"holder_wallets": 0}
    rows.sort(key=lambda r: -r[1])
    tokens = sum(r[1] for r in rows)
    cum, wallets_50 = 0, None
    for i, r in enumerate(rows, 1):
        cum += r[1]
        if cum >= tokens / 2:
            wallets_50 = i
            break
    share = lambda n: sum(r[1] for r in rows[:n]) / tokens
    return {
        "holder_wallets": len(rows),
        "tokens_counted": tokens,
        "supply": supply,
        "tokens_per_wallet": tokens / len(rows),
        "top1_share": share(1), "top10_share": share(10), "top50_share": share(50),
        "wallets_controlling_50pct": wallets_50,
        "hhi": sum((r[1] / tokens) ** 2 for r in rows) * 10_000,
        "wallets_10plus": sum(1 for r in rows if r[1] >= 10),
        "single_token_wallets_pct": sum(1 for r in rows if r[1] == 1) / len(rows),
        "contract_held_share": sum(r[1] for r in rows if r[2]) / tokens,
        "top_holders": [{"owner": o, "tokens": t, "is_contract": c, "share": t / tokens} for o, t, c in rows[:25]],
    }


# ------------------------------------------------------ valuation scenarios
def valuation_scenarios(market: dict, trading: dict) -> list[dict]:
    """Indicative reference points only — never a single 'correct price'."""
    floor, bid = market.get("floor_eth"), market.get("best_bid_eth")
    ten = next((r for r in market.get("exit_curve", []) if r["units"] == 10), None)
    out = [
        ("Immediate exit, 1 token", bid, "Best collection-wide bid right now",
         "Bid is funded and still live when you sell"),
        ("Immediate exit, 10 tokens (avg)", ten and ten["avg_price_eth"], "Walk 10 units down the bid book",
         "Bids are funded; no new bids appear" + ("" if not ten or ten["fully_filled"] else "; book could NOT absorb all 10")),
        ("Comparable sales, lower quartile", trading.get("clean_price_p25"), "25th percentile of unflagged ETH sales",
         "Recent sales are representative of a typical token"),
        ("Comparable sales, median", trading.get("clean_price_p50"), "Median unflagged ETH sale",
         "Same as above; rarity mix of sold tokens ignored"),
        ("Asking floor", floor, "Cheapest live listing", "A buyer arrives at the asking price — not guaranteed"),
        ("Comparable sales, upper quartile", trading.get("clean_price_p75"), "75th percentile of unflagged ETH sales",
         "Patient seller; may reflect rarer tokens"),
    ]
    return [{"scenario": s, "value_eth": v, "method": m, "key_assumption": a} for s, v, m, a in out]


# -------------------------------------------------------- data confidence
def confidence(market: dict, trading: dict, own: dict, meta: dict) -> dict:
    def grade(issues, low_if):
        return ("Low" if low_if else "Medium" if issues else "High"), issues

    liq_issues = ["Bids may be unfunded or cancelled; OpenSea collection offers only (other venues excluded)"]
    if meta.get("sales_truncated"):
        tr_extra = ["Sales history pagination truncated"]
    else:
        tr_extra = []
    if meta.get("listings_truncated") or meta.get("offers_truncated"):
        liq_issues.append("Order book pagination truncated")
    liq = grade(liq_issues, not market.get("floor_eth") or not market.get("best_bid_eth"))

    tr_issues = ["OpenSea sales only; trades on other marketplaces are not included"] + tr_extra
    n = trading.get("n_sales", 0)
    if n < 30:
        tr_issues.append(f"Only {n} sales in window")
    if (trading.get("flagged_volume_share") or 0) > 0.2:
        tr_issues.append("Over 20% of volume carries wash-trade flags")
    tr = grade(tr_issues, n < 10)

    own_issues = ["Wallets are not people: one owner can use many wallets"]
    if own.get("source") == "OpenSea owner count":
        own_issues.append("Only the owner-wallet count is automated; research concentration and contract-held "
                          "tokens manually (e.g. the Etherscan token holders page)")
    if (own.get("contract_held_share") or 0) > 0.05:
        own_issues.append(f"{own['contract_held_share']:.0%} of tokens sit in contracts (vaults/escrow/lending)")
    if own.get("supply") and own.get("tokens_counted") and abs(own["tokens_counted"] - own["supply"]) / own["supply"] > 0.02:
        own_issues.append("Token count differs from reported supply by >2%")
    ow = grade(own_issues, not own.get("holder_wallets") or own.get("source") == "OpenSea owner count")

    manual = ("Manual", ["No automated data — student must research and cite primary sources"])
    return {"Liquidity and exit depth": liq, "Trading activity and quality": tr,
            "Ownership and supply": ow, "Benefits, rights and use cases": manual,
            "Execution and transparency": manual}


def compute_all(norm: dict) -> dict:
    supply = norm["collection"].get("total_supply")
    market = market_snapshot(norm["listings"], norm["offers"], supply)
    trading = trading_quality(norm.get("trades") or [], supply, norm["meta"].get("window_days", 30))
    own = (ownership(norm["holders"], supply) if norm.get("holders")
           else ownership_from_owner_count((norm.get("stats") or {}).get("reported_owners"), supply))
    return {
        "collection": norm["collection"], "snapshot_utc": norm["meta"]["snapshot_utc"],
        "opensea_reported": norm.get("stats", {}), "market": market, "trading": trading,
        "ownership": own, "valuation_scenarios": valuation_scenarios(market, trading),
        "confidence": {k: {"level": v[0], "notes": v[1]} for k, v in confidence(market, trading, own, norm["meta"]).items()},
        "meta": norm["meta"],
    }
