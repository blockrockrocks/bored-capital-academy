"""OpenSea API v2 client + parsers.

Parsers are defensive: OpenSea's response shapes change occasionally, so
anything unexpected is counted as 'skipped' rather than silently guessed.
"""
from __future__ import annotations

import requests

from .sources import SourceLog

BASE = "https://api.opensea.io/api/v2"
ETH_LIKE = {"ETH", "WETH"}


class OpenSea:
    def __init__(self, api_key: str, log: SourceLog, session: requests.Session | None = None):
        self.log = log
        self.s = session or requests.Session()
        self.headers = {"X-API-KEY": api_key, "accept": "application/json"}

    def _get(self, path: str, label: str, params: dict | None = None) -> dict:
        return self.log.fetch(self.s, "GET", BASE + path, source="OpenSea", label=label,
                              params=params, headers=self.headers)

    def collection(self, slug: str) -> dict:
        return self._get(f"/collections/{slug}", "os_collection")

    def stats(self, slug: str) -> dict:
        return self._get(f"/collections/{slug}/stats", "os_stats")

    def _paged(self, path: str, label: str, key: str, max_pages: int) -> tuple[list, bool]:
        items, cursor = [], None
        for page in range(max_pages):
            params = {"limit": 100}
            if cursor:
                params["next"] = cursor
            data = self._get(path, f"{label}_p{page}", params)
            items.extend(data.get(key, []))
            cursor = data.get("next")
            if not cursor:
                return items, False
        return items, True  # truncated

    def best_listings(self, slug: str, max_pages: int = 15) -> tuple[list, bool]:
        return self._paged(f"/listings/collection/{slug}/best", "os_listings", "listings", max_pages)

    def collection_offers(self, slug: str, max_pages: int = 10) -> tuple[list, bool]:
        return self._paged(f"/offers/collection/{slug}", "os_offers", "offers", max_pages)

    def sales(self, slug: str, after_unix: int, max_pages: int = 60) -> tuple[list, bool]:
        """Sale events since `after_unix`, newest first, 50 per page."""
        items, cursor = [], None
        for page in range(max_pages):
            params = {"event_type": "sale", "after": after_unix, "limit": 50}
            if cursor:
                params["next"] = cursor
            data = self._get(f"/events/collection/{slug}", f"os_sales_p{page}", params)
            items.extend(data.get("asset_events", []))
            cursor = data.get("next")
            if not cursor:
                return items, False
        return items, True


def _amount(price: dict) -> tuple[float, str] | None:
    try:
        return int(price["value"]) / 10 ** int(price.get("decimals", 18)), price.get("currency", "")
    except (KeyError, TypeError, ValueError):
        return None


def parse_listings(raw: list) -> tuple[list[dict], int]:
    """Cheapest ETH listing per token. Returns (listings, skipped_count)."""
    best: dict[str, float] = {}
    skipped = 0
    for item in raw:
        amt = _amount(((item.get("price") or {}).get("current")) or {})
        try:
            token_id = str(item["protocol_data"]["parameters"]["offer"][0]["identifierOrCriteria"])
        except (KeyError, IndexError, TypeError):
            token_id = None
        if not amt or amt[1] not in ETH_LIKE or token_id is None or amt[0] <= 0:
            skipped += 1
            continue
        best[token_id] = min(amt[0], best.get(token_id, float("inf")))
    return [{"token_id": t, "price_eth": p} for t, p in best.items()], skipped


def parse_offers(raw: list) -> tuple[list[dict], int]:
    """Collection-wide ETH/WETH bids, price per unit and units remaining.

    Trait-specific offers are skipped: they do not apply to every token.
    """
    out, skipped = [], 0
    for item in raw:
        crit = item.get("criteria") or {}
        if crit.get("trait") or crit.get("traits"):
            skipped += 1
            continue
        amt = _amount(item.get("price") or {})
        try:
            qty = int(item["protocol_data"]["parameters"]["consideration"][0]["startAmount"])
        except (KeyError, IndexError, TypeError, ValueError):
            qty = 1
        qty = max(qty, 1)
        remaining = item.get("remaining_quantity")
        units = int(remaining) if isinstance(remaining, (int, str)) and str(remaining).isdigit() else qty
        if not amt or amt[1] not in ETH_LIKE or amt[0] <= 0 or units <= 0:
            skipped += 1
            continue
        out.append({"price_eth": amt[0] / qty, "units": units, "maker": item.get("maker") or ""})
    return out, skipped


def parse_sales(raw: list) -> tuple[list[dict], int]:
    """Sale events -> the trade rows metrics.trading_quality expects."""
    from datetime import datetime, timezone
    out, skipped = [], 0
    for e in raw:
        pay = e.get("payment") or {}
        nft = e.get("nft") or {}
        try:
            qty = max(int(e.get("quantity") or 1), 1)
            amount = int(pay["quantity"]) / 10 ** int(pay.get("decimals", 18)) / qty
            ts = datetime.fromtimestamp(int(e.get("event_timestamp") or e.get("closing_date")), timezone.utc)
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        if nft.get("identifier") is None or not e.get("buyer") or not e.get("seller"):
            skipped += 1
            continue
        out.append({"block_time": ts.strftime("%Y-%m-%d %H:%M:%S"), "token_id": str(nft["identifier"]),
                    "buyer": e["buyer"], "seller": e["seller"], "amount_original": amount,
                    "currency_symbol": (pay.get("symbol") or "").upper(), "amount_usd": None,
                    "project": "opensea", "tx_hash": e.get("transaction")})
    return out, skipped


def parse_collection(raw: dict) -> dict:
    contracts = raw.get("contracts") or []
    return {
        "name": raw.get("name") or raw.get("collection"),
        "slug": raw.get("collection"),
        "contract": contracts[0]["address"] if contracts else None,
        "chain": contracts[0].get("chain") if contracts else None,
        "total_supply": raw.get("total_supply"),
        "opensea_url": raw.get("opensea_url"),
    }


def parse_stats(raw: dict) -> dict:
    total = raw.get("total") or {}
    intervals = {i.get("interval"): i for i in raw.get("intervals") or []}
    return {
        "reported_floor": total.get("floor_price"),
        "reported_floor_symbol": total.get("floor_price_symbol"),
        "reported_owners": total.get("num_owners"),
        "reported_market_cap": total.get("market_cap"),
        "reported_volume_all_time": total.get("volume"),
        "reported_volume_30d": (intervals.get("thirty_day") or {}).get("volume"),
        "reported_sales_30d": (intervals.get("thirty_day") or {}).get("sales"),
    }
