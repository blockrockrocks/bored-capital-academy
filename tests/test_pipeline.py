"""Tests use small synthetic inputs with hand-checkable answers. They are not market data."""
import json

import pytest
from openpyxl import load_workbook

from bca import cli, metrics, opensea

WEI = 10 ** 18


def listing(token, eth, cur="ETH"):
    return {"price": {"current": {"currency": cur, "decimals": 18, "value": str(int(eth * WEI))}},
            "protocol_data": {"parameters": {"offer": [{"identifierOrCriteria": str(token)}]}}}


def offer(eth_total, qty, cur="WETH", maker="0xm", trait=False, remaining=None):
    o = {"price": {"currency": cur, "decimals": 18, "value": str(int(eth_total * WEI))},
         "protocol_data": {"parameters": {"consideration": [{"startAmount": str(qty)}]}},
         "criteria": {"trait": {"type": "Fur", "value": "Gold"}} if trait else {"collection": {"slug": "x"}},
         "maker": maker}
    if remaining is not None:
        o["remaining_quantity"] = remaining
    return o


def test_parse_listings_keeps_cheapest_per_token_and_skips_non_eth():
    rows, skipped = opensea.parse_listings([listing(1, 12), listing(1, 10), listing(2, 11), listing(3, 5, "APE")])
    assert sorted((r["token_id"], r["price_eth"]) for r in rows) == [("1", 10), ("2", 11)]
    assert skipped == 1


def test_parse_offers_per_unit_price_and_trait_skip():
    rows, skipped = opensea.parse_offers([offer(20, 2), offer(9, 1, trait=True), offer(30, 3, remaining=1)])
    assert [(r["price_eth"], r["units"]) for r in rows] == [(10, 2), (10, 1)]
    assert skipped == 1


def test_market_snapshot_and_exit_curve():
    listings = [{"token_id": str(i), "price_eth": p} for i, p in enumerate([10, 10.4, 11, 13])]
    offers = [{"price_eth": 9, "units": 2, "maker": "a"}, {"price_eth": 8, "units": 3, "maker": "b"}]
    m = metrics.market_snapshot(listings, offers, supply=100)
    assert m["floor_eth"] == 10 and m["best_bid_eth"] == 9
    assert m["bid_ask_spread_pct"] == pytest.approx(0.1)
    assert m["listings_within_5pct"] == 2 and m["listings_within_10pct"] == 3
    assert m["headline_market_cap_eth"] == 1000 and m["bid_book_value_eth"] == 42
    five = next(r for r in m["exit_curve"] if r["units"] == 5)
    assert five["fully_filled"] and five["avg_price_eth"] == pytest.approx(42 / 5)
    assert five["discount_vs_floor"] == pytest.approx(1 - 8.4 / 10)
    ten = next(r for r in m["exit_curve"] if r["units"] == 10)
    assert not ten["fully_filled"] and ten["units_filled"] == 5


def test_trading_quality_flags():
    t = lambda tok, s, b, eth, day: {"token_id": tok, "seller": s, "buyer": b, "amount_original": eth,
                                    "currency_symbol": "ETH", "amount_usd": eth * 3000, "block_time": f"2026-10-{day:02d} 10:00",
                                    "project": "opensea"}
    trades = [t(1, "a", "b", 10, 1), t(2, "b", "a", 10, 2),           # reciprocal pair
              t(3, "c", "c", 10, 3),                                   # self-trade
              t(4, "d", "e", 11, 4), t(4, "e", "f", 12, 5), t(4, "f", "g", 13, 6),  # token 4 traded 3x
              t(5, "h", "i", 9, 7), t(6, "j", "k", 10, 8)]
    q = metrics.trading_quality(trades, supply=100, window_days=30)
    assert q["n_sales"] == 8 and q["flagged_sales"] == 6
    assert q["flag_counts"] == {"reciprocal pair": 2, "self-trade": 1, "token traded 3+ times": 3}
    assert q["clean_sales_with_eth_price"] == 2 and q["clean_price_p50"] == pytest.approx(9.5)
    assert q["turnover_pct"] == pytest.approx(0.06) and q["active_trading_days"] == 8


def test_ownership():
    holders = [{"owner": "0xWhale", "tokens": 50, "is_contract": 0}, {"owner": "0xVault", "tokens": 20, "is_contract": 1},
               {"owner": "0x000000000000000000000000000000000000dead", "tokens": 5}] + \
              [{"owner": f"0x{i}", "tokens": 1, "is_contract": 0} for i in range(30)]
    o = metrics.ownership(holders, supply=100)
    assert o["holder_wallets"] == 32 and o["tokens_counted"] == 100
    assert o["top1_share"] == 0.5 and o["wallets_controlling_50pct"] == 1
    assert o["contract_held_share"] == 0.2 and o["wallets_10plus"] == 2


def test_end_to_end_with_mocked_http(tmp_path, monkeypatch):
    """Runs snapshot + workbook through the real CLI code with a fake HTTP session."""
    responses = {
        "/collections/apes": {"collection": "apes", "name": "Test Apes", "total_supply": 100,
                              "contracts": [{"address": "0xabc", "chain": "ethereum"}]},
        "/collections/apes/stats": {"total": {"floor_price": 10, "num_owners": 32},
                                    "intervals": [{"interval": "thirty_day", "volume": 80, "sales": 8}]},
        "/listings/collection/apes/best": {"listings": [listing(1, 10), listing(2, 11)]},
        "/offers/collection/apes": {"offers": [offer(9, 1), offer(16, 2)]},
    }

    class Resp:
        def __init__(self, data, status=200):
            self.data, self.status_code, self.headers, self.text = data, status, {}, json.dumps(data)

        def json(self):
            return self.data

        def raise_for_status(self):
            pass

    class FakeSession:
        def request(self, method, url, **kw):
            if "dune.com" in url:
                if url.endswith("/execute"):
                    return Resp({"execution_id": "q" + url.split("/")[-2]})
                if "/results" in url:
                    rows = ([{"owner": "0xw", "tokens": 70, "is_contract": 0}, {"owner": "0xv", "tokens": 30, "is_contract": 1}]
                            if "q11" in url else
                            [{"token_id": "1", "seller": "a", "buyer": "b", "amount_original": 10, "currency_symbol": "ETH",
                              "amount_usd": 30000, "block_time": "2026-10-01", "project": "blur"}])
                    return Resp({"result": {"rows": rows}})
            path = url.split("/api/v2")[1]
            return Resp(responses[path])

        def get(self, url, **kw):
            return Resp({"state": "QUERY_STATE_COMPLETED"})

    monkeypatch.setattr("requests.Session", FakeSession)
    for k, v in {"OPENSEA_API_KEY": "k", "DUNE_API_KEY": "d", "DUNE_QUERY_HOLDERS": "11", "DUNE_QUERY_TRADES": "22"}.items():
        monkeypatch.setenv(k, v)

    run_dir = cli.snapshot("apes", 30, tmp_path)
    out = cli.workbook(run_dir, None)

    sources = json.loads((run_dir / "sources.json").read_text())
    assert all("k" not in str(s.get("params")) for s in sources)  # keys never stored
    assert {s["source"] for s in sources} == {"OpenSea", "Dune"}

    m = json.loads((run_dir / "metrics.json").read_text())
    assert m["market"]["floor_eth"] == 10 and m["market"]["best_bid_eth"] == 9
    assert m["ownership"]["contract_held_share"] == 0.3

    wb = load_workbook(out)
    assert wb.sheetnames == ["Read me", "Market snapshot", "Ownership", "Valuation scenarios",
                             "Scorecard", "One-page report", "Sources"]
    sc = wb["Scorecard"]
    assert sc["G5"].value == '=IF(F5="","",B5*F5/5*100)'
    assert sum(sc.cell(row=r, column=2).value for r in range(5, 10)) == pytest.approx(1.0)
