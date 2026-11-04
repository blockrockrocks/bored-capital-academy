# Bored Capital Academy — data pipeline & Ape Analytics Scorecard

Step 1 of the AI-run academy. One command pulls live market data for any NFT collection
and produces the **Ape Analytics Scorecard** workbook from the business case (p. 8),
plus a `metrics.json` that the AI tutor and content agent will read later.

```
python -m bca run boredapeyachtclub
```

## What it produces

`data/<slug>/<UTC timestamp>/`

| File | Contents |
|---|---|
| `Ape_Analytics_Scorecard_<slug>_<ts>.xlsx` | Tabs: Read me · Market snapshot · Ownership · Valuation scenarios · Scorecard · One-page report · Sources |
| `metrics.json` | Every computed number (machine-readable, for the tutor and content agents) |
| `normalized.json` | Cleaned inputs |
| `raw/*.json` + `sources.json` | Every API response verbatim, with URL, parameters and UTC fetch time — the dated source log the course requires |

**Data sources**
- **OpenSea API v2:** collection info, stats, live listings and collection-wide bids → floor, best bid, spread, listed float, depth, and an **exit curve** (what selling 1/5/10/25/50/100 tokens into the bid book actually returns).
- **Dune:** `nft.transfers` → current holders, concentration, contract-held share; `nft.trades` → all-venue sales, turnover, wash-trade flags (self-trades, reciprocal pairs, tokens traded 3+ times), clean comparable-sale percentiles.

**What the scorecard does:** fills in the evidence and a data-confidence level for each dimension.
**What it doesn't do:** the student enters the 0–5 scores (yellow cells), and the two qualitative
dimensions (benefits/rights, execution) are left for the student to research. That keeps it an
education tool rather than a signal service, in line with the MiCA boundary on p. 15.

## Setup (one time)

1. Python 3.10+, then `pip install -e .`
2. Get keys: OpenSea API key (docs.opensea.io) and Dune API key (dune.com → Settings → API).
3. `cp .env.example .env`, add both keys, then load them: `set -a; source .env; set +a`
4. Create the two Dune queries in your Dune account:
   ```
   python -m bca dune-setup
   ```
   Paste the two printed `DUNE_QUERY_…` lines into `.env`. If your Dune plan doesn't allow
   query creation through the API, create them by hand from `dune/holders.sql` and
   `dune/trades.sql` (add text parameters `contract` and `days`), then copy the query IDs.

## Commands

```
python -m bca run <slug> [--days 30]      # snapshot + workbook
python -m bca run <slug> --no-dune        # OpenSea only (no ownership/trading tabs)
python -m bca snapshot <slug>             # fetch only
python -m bca workbook data/<slug>        # rebuild workbook from the latest snapshot
python -m pytest -q                       # tests (synthetic inputs, no network)
```

## Known limits (v0.1)

- Only OpenSea order books. Blur and other venues' bids and listings aren't included yet; their **sales** are included via Dune.
- Bids may be unfunded. The exit curve assumes every bid is real.
- Dune SQL is Ethereum ERC-721 only (BAYC, MAYC, BAKC). Other chains get OpenSea data only.
- Rarity is ignored in comparable sales.
- The OpenSea response parsing was written against the documented v2 shapes and tested with synthetic
  responses. **Check the first live run** (the `listings_skipped` / `offers_skipped` counts in `normalized.json` should be small).

Educational use only. Not investment advice. Independent of Yuga Labs and BAYC.
