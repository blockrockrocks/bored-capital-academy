"""Tutor tests: the real Anthropic SDK against a scripted mock HTTP transport (no network, no credits).

The scripted replies are test fixtures, not real model output; they check the tutor's control flow,
guardrails, logging and the exact request shapes it sends.
"""
import json

import anthropic
import httpx2
import pytest

from bca import tutor as tutor_mod
from bca.tutor import Tutor, review


def msg(content, stop="end_turn"):
    return {"id": "msg_x", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": content, "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5}}


def guard(category):
    return msg([{"type": "text", "text": json.dumps({"category": category, "note": "test"})}])


class Script:
    """Returns queued responses in order and records every request body."""

    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def __call__(self, request):
        self.requests.append({"url": str(request.url), "headers": dict(request.headers),
                              "body": json.loads(request.content)})
        return httpx2.Response(200, json=self.responses.pop(0))


def make(tmp_path, script, metrics=None):
    data = tmp_path / "data"
    if metrics:
        run = data / "apes" / "20261104T120000Z"
        run.mkdir(parents=True)
        (run / "metrics.json").write_text(json.dumps(metrics))
    client = anthropic.Anthropic(api_key="test", max_retries=0,
                                 http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(script)))
    return Tutor(student="ana", data_dir=data, log_dir=tmp_path / "logs", client=client)


METRICS = {"collection": {"name": "Test Apes"}, "snapshot_utc": "2026-11-04T12:00:00Z",
           "market": {"floor_eth": 10.0, "best_bid_eth": 9.0}, "trading": {}, "ownership": {},
           "valuation_scenarios": [], "confidence": {}}


def test_concept_question_request_shape(tmp_path):
    s = Script(guard("course_concept"), msg([{"type": "text", "text": "The floor is an ask."}]))
    t = make(tmp_path, s)
    assert t.send("What is the floor?") == "The floor is an ask."

    g, main = s.requests[0]["body"], s.requests[1]
    assert g["output_config"]["format"]["type"] == "json_schema" and g["output_config"]["effort"] == "low"
    body = main["body"]
    assert "server-side-fallback-2026-07-01" in main["headers"]["anthropic-beta"]
    assert body["fallbacks"] == "default" and body["model"] == "claude-opus-5-5"
    assert "thinking" not in body  # always-on adaptive on this model; disabling would 400
    assert body["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "course_file" in body["system"][-1]["text"]
    assert [m["role"] for m in body["messages"]] == ["user"]  # no reminder for ordinary questions
    assert not (tmp_path / "logs" / "review_queue.jsonl").exists()


def test_advice_request_injects_reminder_and_flags(tmp_path):
    s = Script(guard("personalised_advice"),
               msg([{"type": "text", "text": "I can't make personal recommendations, but here's how to research it."}]))
    t = make(tmp_path, s)
    t.send("Should I buy a BAYC?")
    body = s.requests[1]["body"]
    assert [m["role"] for m in body["messages"]] == ["user", "system"]
    assert "personal recommendation" in body["messages"][-1]["content"]
    flags = (tmp_path / "logs" / "review_queue.jsonl").read_text()
    assert "guard:personalised_advice" in flags


def test_tool_loop_reads_metrics_and_keeps_history_append_only(tmp_path):
    s = Script(guard("data_question"),
               msg([{"type": "text", "text": "Let me check."},
                    {"type": "tool_use", "id": "tu_1", "name": "get_collection_metrics",
                     "input": {"slug": "apes", "section": "market"}}], stop="tool_use"),
               msg([{"type": "text", "text": "As of 2026-11-04 12:00 UTC the best bid is 9 ETH."}]))
    t = make(tmp_path, s, METRICS)
    reply = t.send("What's the best bid on apes?")
    assert "9 ETH" in reply
    second = s.requests[2]["body"]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    result = json.loads(second[2]["content"][0]["content"])
    assert result["market"]["best_bid_eth"] == 9.0 and result["snapshot_utc"] == "2026-11-04T12:00:00Z"
    # history from turn 1 is sent byte-identical as the prefix of turn 2
    s.responses += [guard("course_concept"), msg([{"type": "text", "text": "ok"}])]
    t.send("thanks")
    assert s.requests[4]["body"]["messages"][:3] == second[:2] + [second[2]]


def test_missing_collection_and_escalation(tmp_path):
    s = Script(guard("admin"),
               msg([{"type": "tool_use", "id": "a", "name": "get_collection_metrics", "input": {"slug": "nope", "section": "all"}},
                    {"type": "tool_use", "id": "b", "name": "escalate_to_founder",
                     "input": {"reason": "admin", "summary": "Refund request"}}], stop="tool_use"),
               msg([{"type": "text", "text": "The founder will follow up."}]))
    t = make(tmp_path, s)
    t.send("Refund please, and what about nope?")
    results = s.requests[2]["body"]["messages"][-1]["content"]
    assert len(results) == 2  # both tool results in one user message
    assert "No snapshot" in results[0]["content"]
    q = (tmp_path / "logs" / "review_queue.jsonl").read_text()
    assert "escalation:admin" in q and "guard:admin" in q


def test_post_check_flags_advice_phrasing(tmp_path):
    s = Script(guard("course_concept"), msg([{"type": "text", "text": "Honestly you should buy now."}]))
    t = make(tmp_path, s)
    t.send("Tell me about liquidity")
    assert "post_check:advice_phrasing" in (tmp_path / "logs" / "review_queue.jsonl").read_text()
    assert "post_check:advice_phrasing" in review(tmp_path / "logs")


def test_refusal_and_guard_failure_are_handled(tmp_path):
    def failing_then_refusal(request):
        failing_then_refusal.n += 1
        if failing_then_refusal.n == 1:
            return httpx2.Response(500, json={"type": "error", "error": {"type": "api_error", "message": "boom"}})
        return httpx2.Response(200, json={**msg([], stop="refusal"),
                                          "stop_details": {"type": "refusal", "category": None, "explanation": "x"}})
    failing_then_refusal.n = 0
    t = make(tmp_path, failing_then_refusal)
    reply = t.send("hello")
    assert "not able to help" in reply
    q = (tmp_path / "logs" / "review_queue.jsonl").read_text()
    assert "guard:other" in q and "model_refusal" in q


@pytest.mark.parametrize("text,hit", [("You should sell it.", True), ("It looks undervalued.", True),
                                      ("The bid book shows 12 units.", False)])
def test_advice_patterns(text, hit):
    import re
    assert any(re.search(p, text, re.IGNORECASE) for p in tutor_mod.ADVICE_PATTERNS) == hit
