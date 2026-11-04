"""AI tutor for The NFT Investor's Playbook.

Guardrails, in layers:
1. Pre-check: every student message is classified (structured output). Advice-seeking or
   price-prediction messages get a turn-specific boundary reminder as a mid-conversation
   system message, and are flagged for founder review.
2. System prompt: course scope, the MiCA advice boundary, data-citation rules.
3. Post-check: replies containing recommendation-like phrasing are flagged (never silently edited).
4. Every event is logged to logs/tutor/<conversation>.jsonl; flags go to logs/review_queue.jsonl,
   which `bca tutor review` summarises for the weekly founder review.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parent.parent
COURSE_DIR = ROOT / "course"
MODEL = os.environ.get("BCA_TUTOR_MODEL", "claude-opus-5-5")
GUARD_MODEL = os.environ.get("BCA_GUARD_MODEL", MODEL)
EFFORT = os.environ.get("BCA_TUTOR_EFFORT", "medium")
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = """You are the tutor for Bored Capital Academy's course "The NFT Investor's Playbook" \
(tagline: Think Beyond the Floor), operated by BlockRock OÜ. The academy is independent of Yuga Labs, BAYC \
and any employer; never imply official endorsement.

Your job is to help learners understand the course material and apply its research methods: liquidity, \
trading quality, ownership analysis, valuation ranges, and the Ape Analytics Scorecard. Teach the method, \
not conclusions. Prefer asking a guiding question or pointing to the relevant workbook tab over doing the \
learner's assessment for them, but always answer conceptual questions directly and clearly.

The advice boundary is a legal requirement (EU MiCA: personalised crypto-asset advice is a regulated \
activity), not a style preference:
- Never give personalised buy, sell or hold recommendations, never say whether a learner should acquire, \
keep or dispose of a specific NFT, and never review a learner's portfolio or positions.
- Never predict prices or say a collection is under- or overvalued. Indicative ranges from the workbook \
are reference points with stated assumptions, not targets.
- When asked for any of these, say plainly that the course can't give personal recommendations, then \
show how the learner could research the question themselves with the course framework. Stay warm and \
useful; don't lecture.

Using market data:
- Use the get_collection_metrics tool for any number about a collection. Never state a market figure \
from memory.
- Always state the snapshot time (UTC) of any figure and note it may be stale.
- Mention the data-confidence level and caveats when they matter (unfunded bids, wallets ≠ people, \
wash-trade flags are prompts, not proof).
- If a collection has no snapshot, say so; don't estimate.

Escalate with the escalate_to_founder tool when: the learner asks about refunds, payments, invoices, \
access, scheduling or anything in the admin FAQ still marked TODO; reports a problem with the course; \
seems distressed about financial losses; or keeps pushing for personal advice after you've explained the \
boundary. Tell the learner the founder will follow up. Never invent admin policies.

Write in clear, plain English (learners are often non-native speakers). Keep answers focused; use short \
lists or a small table when comparing numbers. When you use a tool, you may say a brief sentence first. \
Do not include internal or system XML tags in your response."""

BOUNDARY_REMINDER = ("Boundary check for this turn: the learner's latest message asks for {category}. Do not "
                     "give a personal recommendation or price prediction. Acknowledge the question, explain "
                     "briefly that the course can't advise on individual decisions, and teach how to research "
                     "it with the scorecard and the relevant data.")

GUARD_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": [
            "course_concept", "data_question", "scorecard_help", "personalised_advice",
            "price_prediction", "portfolio_review", "admin", "distress", "off_topic", "other"]},
        "note": {"type": "string", "description": "One short sentence explaining the classification."},
    },
    "required": ["category", "note"],
    "additionalProperties": False,
}
GUARD_SYSTEM = ("Classify the learner's latest message for an NFT market-research course tutor. "
                "personalised_advice = asks whether they should buy/sell/hold/keep a specific asset or what to do "
                "with their own money or NFTs. price_prediction = asks where a price will go, a target price, or "
                "whether something is cheap/overvalued. portfolio_review = asks to assess their own holdings. "
                "admin = payments, refunds, access, schedule. distress = signs of financial or emotional distress. "
                "General educational questions about how markets work are course_concept even when they mention "
                "a specific collection.")
FLAG_CATEGORIES = {"personalised_advice", "price_prediction", "portfolio_review", "admin", "distress"}
REMIND_CATEGORIES = {"personalised_advice": "a personal recommendation",
                     "price_prediction": "a price prediction or valuation verdict",
                     "portfolio_review": "a review of their own holdings"}

ADVICE_PATTERNS = [
    r"\byou should (buy|sell|hold|keep|ape|acquire|dump|offload)\b",
    r"\bi (would|'d) (buy|sell|hold|keep)\b",
    r"\b(i )?recommend (buying|selling|holding)\b",
    r"\b(is|looks) (undervalued|overvalued|a bargain|cheap right now)\b",
    r"\bwill (go up|go down|pump|moon|rise|fall)\b",
    r"\bprice target\b",
]

TOOLS = [
    {
        "name": "list_collections",
        "description": "List collections that have a market-data snapshot available, with snapshot time (UTC).",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "get_collection_metrics",
        "description": ("Get computed market metrics for one collection from its latest snapshot. "
                        "Sections: market (floor, bid, spread, depth, exit curve), trading (sales, turnover, "
                        "wash flags, comparable-sale percentiles), ownership (concentration, contract-held share), "
                        "valuation (indicative reference points), confidence (data-confidence per scorecard dimension)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "OpenSea slug, e.g. boredapeyachtclub"},
                "section": {"type": "string", "enum": ["market", "trading", "ownership", "valuation", "confidence", "all"]},
            },
            "required": ["slug", "section"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "escalate_to_founder",
        "description": "Send this conversation to the founder for a personal follow-up.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "enum": ["admin", "course_problem", "distress", "persistent_advice_request", "other"]},
                "summary": {"type": "string", "description": "One or two sentences for the founder."},
            },
            "required": ["reason", "summary"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_course_text(course_dir: Path = COURSE_DIR) -> str:
    parts = [f"<course_file name=\"{p.name}\">\n{p.read_text()}\n</course_file>" for p in sorted(course_dir.glob("*.md"))]
    return "Course materials (the authoritative source for course content):\n\n" + "\n\n".join(parts)


class MetricsStore:
    """Reads metrics.json files produced by `bca run` (data/<slug>/<run>/metrics.json)."""

    SECTIONS = {"market": "market", "trading": "trading", "ownership": "ownership",
                "valuation": "valuation_scenarios", "confidence": "confidence"}

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)

    def _latest(self, slug: str) -> Path | None:
        d = self.data_dir / slug
        runs = sorted(p for p in d.iterdir() if (p / "metrics.json").exists()) if d.is_dir() else []
        return runs[-1] / "metrics.json" if runs else None

    def list(self) -> list[dict]:
        out = []
        if self.data_dir.is_dir():
            for d in sorted(self.data_dir.iterdir()):
                p = self._latest(d.name)
                if p:
                    m = json.loads(p.read_text())
                    out.append({"slug": d.name, "name": m["collection"].get("name"), "snapshot_utc": m["snapshot_utc"]})
        return out

    def get(self, slug: str, section: str) -> dict:
        p = self._latest(slug)
        if not p:
            return {"error": f"No snapshot for '{slug}'. Available: {[c['slug'] for c in self.list()]}"}
        m = json.loads(p.read_text())
        base = {"collection": m["collection"].get("name"), "snapshot_utc": m["snapshot_utc"],
                "note": "Snapshot data; may be stale. Educational use only."}
        if section == "all":
            return {**base, **{k: m.get(v) for k, v in self.SECTIONS.items()}}
        return {**base, section: m.get(self.SECTIONS[section])}


class Tutor:
    def __init__(self, student: str = "anonymous", data_dir: Path = ROOT / "data", log_dir: Path = ROOT / "logs",
                 client: anthropic.Anthropic | None = None, course_dir: Path = COURSE_DIR):
        self.client = client or anthropic.Anthropic()
        self.student = student
        self.metrics = MetricsStore(data_dir)
        self.conversation_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:6]}"
        self.log_dir = Path(log_dir)
        (self.log_dir / "tutor").mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / "tutor" / f"{self.conversation_id}.jsonl"
        # Frozen, cacheable prefix: instructions + course materials. Nothing volatile here.
        self.system = [{"type": "text", "text": SYSTEM_PROMPT},
                       {"type": "text", "text": load_course_text(course_dir), "cache_control": {"type": "ephemeral"}}]
        self.messages: list = []  # append-only: never edit earlier turns

    # ----------------------------------------------------------- logging
    def _log(self, event: str, **data) -> None:
        rec = {"t": _now(), "conversation": self.conversation_id, "student": self.student, "event": event, **data}
        with self.log_path.open("a") as f:
            f.write(json.dumps(rec, default=str) + "\n")

    def _flag(self, kind: str, detail: str, excerpt: str = "") -> None:
        rec = {"t": _now(), "conversation": self.conversation_id, "student": self.student,
               "kind": kind, "detail": detail, "excerpt": excerpt[:400], "log": str(self.log_path)}
        with (self.log_dir / "review_queue.jsonl").open("a") as f:
            f.write(json.dumps(rec) + "\n")
        self._log("flag", kind=kind, detail=detail)

    # ------------------------------------------------------------ guard
    def classify(self, text: str) -> dict:
        try:
            r = self.client.messages.create(
                model=GUARD_MODEL, max_tokens=1024, system=GUARD_SYSTEM,
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": GUARD_SCHEMA}},
                messages=[{"role": "user", "content": f"<learner_message>\n{text}\n</learner_message>"}],
            )
            if r.stop_reason == "refusal":
                return {"category": "other", "note": "guard classifier declined", "guard_refused": True}
            return json.loads(next(b.text for b in r.content if b.type == "text"))
        except (anthropic.APIError, StopIteration, json.JSONDecodeError) as e:
            # Fail safe: unknown -> treat as needing review, still answer under the system prompt.
            self._log("guard_error", error=repr(e))
            return {"category": "other", "note": f"guard unavailable: {type(e).__name__}", "guard_error": True}

    # ------------------------------------------------------------ tools
    def _run_tool(self, name: str, args: dict) -> tuple[str, bool]:
        try:
            if name == "list_collections":
                return json.dumps(self.metrics.list()), False
            if name == "get_collection_metrics":
                if args.get("section") not in {*MetricsStore.SECTIONS, "all"}:
                    return "Invalid section.", True
                return json.dumps(self.metrics.get(str(args.get("slug", "")), args["section"]), default=str), False
            if name == "escalate_to_founder":
                self._flag(f"escalation:{args.get('reason')}", str(args.get("summary", "")))
                return "Escalated. Tell the learner the founder will follow up personally.", False
            return f"Unknown tool {name}", True
        except Exception as e:  # tool failure goes back to the model, not to the learner as a crash
            return f"Tool error: {e}", True

    # ------------------------------------------------------------- turn
    def send(self, text: str, max_tool_rounds: int = 6) -> str:
        guard = self.classify(text)
        self._log("user", text=text, guard=guard)
        if guard["category"] in FLAG_CATEGORIES or guard.get("guard_error") or guard.get("guard_refused"):
            self._flag(f"guard:{guard['category']}", guard.get("note", ""), text)

        self.messages.append({"role": "user", "content": text})
        if guard["category"] in REMIND_CATEGORIES:
            self.messages.append({"role": "system",
                                  "content": BOUNDARY_REMINDER.format(category=REMIND_CATEGORIES[guard["category"]])})

        reply_parts: list[str] = []
        for _ in range(max_tool_rounds):
            resp = self.client.beta.messages.create(
                model=MODEL, max_tokens=16000, system=self.system, tools=TOOLS, messages=self.messages,
                output_config={"effort": EFFORT}, cache_control={"type": "ephemeral"},
                betas=[FALLBACK_BETA], fallbacks="default",
            )
            usage = getattr(resp, "usage", None)
            self._log("model_response", stop_reason=resp.stop_reason, model=getattr(resp, "model", None),
                      usage=usage.model_dump() if hasattr(usage, "model_dump") else None)
            if resp.stop_reason == "refusal":
                self._flag("model_refusal", str(getattr(resp, "stop_details", "")), text)
                # History stays append-only: record a short placeholder turn instead of editing earlier turns.
                self.messages.append({"role": "assistant", "content": "I can't help with that one."})
                return ("I'm not able to help with that request. If you think this is a mistake, "
                        "the founder will review it and follow up.")
            self.messages.append({"role": "assistant", "content": resp.content})  # full blocks, thinking included
            reply_parts += [b.text for b in resp.content if b.type == "text" and b.text]
            if resp.stop_reason == "pause_turn":
                continue
            if resp.stop_reason != "tool_use":
                break
            results = []
            for b in resp.content:
                if b.type == "tool_use":
                    out, is_err = self._run_tool(b.name, b.input if isinstance(b.input, dict) else {})
                    self._log("tool", name=b.name, input=b.input, is_error=is_err, output=out[:2000])
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": out, "is_error": is_err})
            self.messages.append({"role": "user", "content": results})
        else:
            self._flag("tool_loop_limit", f"exceeded {max_tool_rounds} tool rounds", text)

        reply = "\n\n".join(reply_parts).strip() or "Sorry, I couldn't produce an answer. The founder has been notified."
        self._log("assistant", text=reply)
        hits = [p for p in ADVICE_PATTERNS if re.search(p, reply, re.IGNORECASE)]
        if hits:
            self._flag("post_check:advice_phrasing", f"matched {hits}", reply)
        return reply


# --------------------------------------------------------------- review
def review(log_dir: Path = ROOT / "logs", days: int = 7) -> str:
    q = Path(log_dir) / "review_queue.jsonl"
    if not q.exists():
        return "Review queue is empty."
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    items = []
    for line in q.read_text().splitlines():
        rec = json.loads(line)
        if datetime.strptime(rec["t"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp() >= cutoff:
            items.append(rec)
    convs = len(list((Path(log_dir) / "tutor").glob("*.jsonl")))
    lines = [f"Tutor review: last {days} days — {len(items)} flags across {len({i['conversation'] for i in items})} "
             f"conversations ({convs} conversations logged in total)\n"]
    priority = lambda k: (0 if k.startswith(("escalation", "guard:distress", "post_check", "model_refusal")) else 1, k)
    for rec in sorted(items, key=lambda r: (priority(r["kind"]), r["t"])):
        lines.append(f"[{rec['kind']}] {rec['t']} · {rec['student']} · {rec['detail']}\n"
                     f"    “{rec['excerpt'][:200]}”\n    log: {rec['log']}")
    return "\n".join(lines)
