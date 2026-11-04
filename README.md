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
2. Get keys: OpenSea API key (docs.opensea.io), Dune API key (dune.com → Settings → API) and Anthropic API key (platform.claude.com) for the tutor.
3. `cp .env.example .env`, add your keys, then load them: `set -a; source .env; set +a`
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

## AI tutor

```
python -m bca tutor chat --student ana     # terminal chat (web UI comes with the course platform)
python -m bca tutor review --days 7        # weekly founder review of flagged conversations
python -m bca tutor redteam                # advice-boundary test, 15 prompts (spends API credits)
```

- **Knowledge:** `course/*.md` (written from the business case) plus live numbers from `metrics.json` through a tool. The tutor never quotes market figures from memory and always gives the snapshot time.
- **Advice boundary (MiCA):** every learner message is classified first. Buy/sell/hold, price-prediction or portfolio questions get a boundary reminder for that turn and are flagged. Replies with recommendation-like wording are flagged too. Admin questions, distress and repeated advice-seeking are escalated to you.
- **Logs:** each conversation goes to `logs/tutor/<id>.jsonl` and each flag to `logs/review_queue.jsonl`.
- **Before launch:** fill in `course/05_admin_faq.md` (refunds, VAT, access, Q&A schedule). Until then the tutor says you'll follow up.
- **Model:** the default is set in `bca/tutor.py` (medium effort), with server-side refusal fallback (`fallbacks: "default"`). Change it with `BCA_TUTOR_MODEL`, `BCA_TUTOR_EFFORT` and `BCA_GUARD_MODEL`. A cheaper guard model cuts cost per message; re-run `redteam` after any change.

## Known limits (v0.1)

- Only OpenSea order books. Blur and other venues' bids and listings aren't included yet; their **sales** are included via Dune.
- Bids may be unfunded. The exit curve assumes every bid is real.
- Dune SQL is Ethereum ERC-721 only (BAYC, MAYC, BAKC). Other chains get OpenSea data only.
- Rarity is ignored in comparable sales.
- The OpenSea response parsing was written against the documented v2 shapes and tested with synthetic
  responses. **Check the first live run** (the `listings_skipped` / `offers_skipped` counts in `normalized.json` should be small).

Educational use only. Not investment advice. Independent of Yuga Labs and BAYC.
