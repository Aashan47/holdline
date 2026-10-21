"""holdline target for helpdesk-agent (github.com/Aashan47/helpdesk-agent).

    export GEMINI_API_KEY=...            # helpdesk-agent calls Gemini
    holdline run --suite helpdesk_cases.jsonl --target target:agent -k 3 --workers 2

The agent's own step events become holdline steps: each retrieval is a ``search`` tool call, each
"what next?" model call is a ``decide`` step, and the self-consistency answer samples are one
``answer_samples`` model step. The calibrated escalation policy (``decide`` with the threshold the
product ships with) turns the raw prediction into answer or escalate. A model outage raises, so it
is recorded as an error, never counted as a correct escalation.
"""

import os
import sys
import threading

import holdline

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.environ.get("HDA_REPO", os.path.join(HERE, "..", "..", "..", "helpdesk-agent")))
sys.path.insert(0, REPO)

from helpdesk_agent import corpus, metrics  # noqa: E402
from helpdesk_agent.agent import Agent, decide  # noqa: E402

_lock = threading.Lock()
_state: dict = {}


def _agent():
    with _lock:
        if "agent" not in _state:
            contexts, _, is_custom = corpus.load_contexts()
            _state["agent"] = Agent(contexts)
            _state["threshold"] = corpus.abstention_threshold(is_custom)
        return _state["agent"], _state["threshold"]


if os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMENI_API_KEY"):
    _agent()  # build the retriever (embeds the corpus once) before any case is timed


def _on_event(step: dict) -> None:
    action = step.get("action")
    if action == "search":
        holdline.step("tool", "search", {"query": step.get("query")},
                      {"ids": step.get("ids"), "new": step.get("new")})
    elif action == "decide":
        holdline.step("llm", "decide", None, {"next": step.get("next"), "query": step.get("query"),
                                               "reason": step.get("reason")},
                      error=step.get("error"))
    elif action == "abstain":
        holdline.step("llm", "decide", None, {"next": "abstain", "reason": step.get("reason")})
    elif action == "sample":
        holdline.step("llm", "answer_samples", {"n": step.get("n")},
                      {"votes": step.get("votes"), "agreement": step.get("agreement"),
                       "errors": step.get("errors")}, error=step.get("error"))


def agent(question: str) -> dict:
    a, threshold = _agent()
    pred = a.predict(question, on_event=_on_event)
    if pred.get("error"):
        raise RuntimeError(f"model unavailable: {pred['error']}")
    d = decide(pred, threshold)
    outcome = "answer" if d["answered"] else "escalate"
    holdline.step("decision", outcome, None, {"confidence": d["confidence"], "threshold": threshold})
    cite = d.get("citation") or {}
    return {"outcome": outcome, "answer": d["answer"], "reply": d["reply"],
            "confidence": d["confidence"], "citation": cite.get("corpus_id"),
            "llm_calls": pred.get("llm_calls")}


@holdline.check("helpdesk_correct")
def helpdesk_correct(case, trace):
    """helpdesk-agent's own correctness rule, so numbers stay comparable with its EVALUATION.md."""
    out = trace.output or {}
    if out.get("outcome") != "answer":
        return False, "escalated a covered ticket"
    ok = metrics.is_correct(out.get("answer", ""), case.meta["answers"])
    return ok, "" if ok else f"answered {out.get('answer', '')!r}, gold {case.meta['answers'][0]!r}"


@holdline.check("cites_gold_article")
def cites_gold_article(case, trace):
    out = trace.output or {}
    if out.get("outcome") != "answer":
        return False, "no reply, no citation"
    ok = out.get("citation") == case.meta["gold_ctx"]
    return ok, "" if ok else f"cited passage {out.get('citation')}, gold article {case.meta['gold_article']}"
