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

## Website & checkout

```
python -m bca web serve                     # http://localhost:8000
python -m bca web simulate-purchase --email you@example.com --tier live   # signed fake purchase, local testing
python -m bca web followups                 # run daily (cron): feedback-survey email N days after purchase
python -m bca web stats                     # students, revenue, survey satisfaction vs the 80% target
```

**Flow:** landing page → tier → email and three consent boxes (terms, giving up the withdrawal right for immediate access, not-advice) →
Paddle overlay checkout → Paddle webhook `transaction.completed` → student enrolled → welcome email with a one-time login link →
course area (modules, workbooks, AI tutor, survey). Refunds and chargebacks (`adjustment.*` approved) remove access automatically.

**Why Paddle:** it is merchant of record. It charges and remits VAT in every EU country, issues the invoices and handles refunds,
so BlockRock receives payouts instead of selling to consumers directly. (Your accountant should still confirm how payouts are treated for tax.)

**Security:** webhooks are HMAC-verified with replay protection and processed exactly once. Login links are signed, expire after 24 hours and work once.
The login form never reveals who is enrolled. The tutor needs a login and has a per-student daily limit to cap API spend.

### Going live (checklist)
1. Paddle: create an account (sandbox first), complete seller verification, and create a product with two one-time prices. Copy the price IDs, the client-side token and an API key.
   Add a notification destination `https://<your-domain>/webhooks/paddle` for `transaction.completed`, `adjustment.created` and `adjustment.updated`, and copy its secret.
2. Email: any SMTP provider (Postmark, Brevo, SES…). Set `EMAIL_BACKEND=smtp`, then set up SPF/DKIM on your domain.
3. Host: build the Dockerfile on any container host (Fly.io, Render, Railway, a VPS) with a **persistent volume** for `/app/data` and `/app/logs`.
   Set every variable from `.env.example`, and set `BCA_SECRET_KEY` to a long random value.
4. Daily cron: `bca run boredapeyachtclub` (fresh workbook data) and `bca web followups`.
5. Before taking real money: complete the DRAFT legal pages (`bca/web/templates/legal_*.html`) and `course/05_admin_faq.md`, record the videos
   (`MODULE_VIDEO_URLS`), run `bca tutor redteam`, then make a sandbox test purchase end to end.

## Known limits (v0.1)

- Only OpenSea order books. Blur and other venues' bids and listings aren't included yet; their **sales** are included via Dune.
- Bids may be unfunded. The exit curve assumes every bid is real.
- Dune SQL is Ethereum ERC-721 only (BAYC, MAYC, BAKC). Other chains get OpenSea data only.
- Rarity is ignored in comparable sales.
- Tutor conversations are kept in server memory per student (they reset when the server restarts; the logs keep everything). The site runs as a single instance.
- The OpenSea response parsing was written against the documented v2 shapes and tested with synthetic
  responses. **Check the first live run** (the `listings_skipped` / `offers_skipped` counts in `normalized.json` should be small).

Educational use only. Not investment advice. Independent of Yuga Labs and BAYC.
