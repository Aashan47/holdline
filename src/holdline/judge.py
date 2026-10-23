"""LLM judges, and measuring them before trusting them.

A judge is any callable ``judge(case, trace) -> bool | float | dict``. :func:`llm_judge` builds one
from your own model call, so holdline never imports a provider SDK.

:func:`calibrate` compares judge verdicts with human labels on the same items and answers one
question: is this judge fit to gate a release? A judge that agrees often but passes outputs that
humans failed (lenient), or whose bias flips direction between easy and hard items, is not.
"""

from __future__ import annotations

import json
import random
import re
from collections import defaultdict
from typing import Any, Callable

from . import stats
from .checks import answer_text

DEFAULT_TEMPLATE = """You are grading one response from an AI agent.

Task given to the agent:
{input}

Agent's final response:
{output}

Tools the agent called, in order: {tools}

Rubric:
{rubric}

Grade strictly against the rubric. Reply with one line of reasoning, then a final line that is
exactly VERDICT: PASS or VERDICT: FAIL."""

_VERDICT = re.compile(r"VERDICT\s*:\s*(PASS|FAIL)", re.I)


def llm_judge(call_model: Callable[[str], str], template: str = DEFAULT_TEMPLATE) -> Callable:
    """Wrap ``call_model(prompt) -> text`` as a judge. The case's ``expected.rubric`` fills the
    template. An unparseable reply counts as FAIL, with the reply kept as the reason."""

    def judge(case, trace) -> dict:
        prompt = template.format(input=case.input if isinstance(case.input, str)
                                 else json.dumps(case.input, ensure_ascii=False),
                                 output=answer_text(trace.output),
                                 tools=", ".join(trace.tool_names()) or "none",
                                 rubric=case.expected.get("rubric", ""))
        reply = call_model(prompt) or ""
        m = _VERDICT.findall(reply)
        ok = bool(m) and m[-1].upper() == "PASS"
        reason = reply.strip().splitlines()[0][:300] if reply.strip() else "empty reply"
        return {"pass": ok, "reason": reason if m else f"unparseable: {reason}"}

    return judge


# -- calibration ---------------------------------------------------------------------------
_TRUE = {"pass", "passed", "yes", "y", "true", "1", "good", "correct"}
_FALSE = {"fail", "failed", "no", "n", "false", "0", "bad", "incorrect"}


def as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v >= 0.5
    s = str(v).strip().lower()
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    raise ValueError(f"cannot read {v!r} as pass/fail")


def load_labels(path: str) -> list:
    """JSONL (or a JSON list) of {"id", "human", "judge", "group"?, "judge_score"?}."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read().strip()
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _confusion(human: list, judge: list) -> dict:
    tp = sum(h and j for h, j in zip(human, judge))
    tn = sum((not h) and (not j) for h, j in zip(human, judge))
    fp = sum((not h) and j for h, j in zip(human, judge))   # judge passed what a human failed
    fn = sum(h and (not j) for h, j in zip(human, judge))   # judge failed what a human passed
    return {"tp": tp, "tn": tn, "fp": fp, "fn": fn}


def _block(human: list, judge: list, with_ci: bool = True) -> dict:
    n = len(human)
    cm = _confusion(human, judge)
    kappa, lo, hi = stats.kappa_ci(human, judge) if with_ci else (stats.cohen_kappa(human, judge), None, None)
    neg, pos = cm["tn"] + cm["fp"], cm["tp"] + cm["fn"]
    return {
        "n": n,
        "agreement": round((cm["tp"] + cm["tn"]) / n, 4) if n else None,
        "kappa": None if kappa != kappa else round(kappa, 4),
        "kappa_ci": None if lo is None or lo != lo else [round(lo, 4), round(hi, 4)],
        "kappa_band": stats.describe_kappa(kappa),
        "confusion": cm,
        # bias > 0: the judge passes more than humans do (lenient); < 0: harsh
        "bias": round((sum(judge) - sum(human)) / n, 4) if n else None,
        "false_pass_rate": round(cm["fp"] / neg, 4) if neg else None,
        "false_fail_rate": round(cm["fn"] / pos, 4) if pos else None,
    }


def _tune_threshold(scores: list, human: list, seed: int = 0) -> dict:
    """Pick the score threshold that maximises kappa on one half, report it on the other half."""
    idx = list(range(len(scores)))
    random.Random(seed).shuffle(idx)
    cut = len(idx) // 2
    fit, held = idx[:cut], idx[cut:]
    best_t, best_k = 0.5, -2.0
    for t in sorted(set(scores)):
        k = stats.cohen_kappa([human[i] for i in fit], [scores[i] >= t for i in fit], [True, False])
        if k == k and k > best_k:
            best_t, best_k = t, k
    held_k = stats.cohen_kappa([human[i] for i in held], [scores[i] >= best_t for i in held],
                               [True, False])
    return {"threshold": best_t, "kappa_fit_half": round(best_k, 4),
            "kappa_held_out_half": None if held_k != held_k else round(held_k, 4),
            "n_fit": len(fit), "n_held_out": len(held)}


def calibrate(items: list, *, min_kappa: float = 0.6, max_false_pass: float = 0.10,
              min_n: int = 30, min_group_n: int = 5, min_bias: float = 0.05) -> dict:
    """Compare judge verdicts with human labels and decide if the judge is fit to gate releases.

    Fit means: at least ``min_n`` labelled items, the lower end of the kappa interval at least
    ``min_kappa``, a false-pass rate (judge PASS on a human FAIL) at most ``max_false_pass``, and
    no sign reversal: the judge must not be lenient on one group and harsh on another (each group
    needs ``min_group_n`` items and a bias of at least ``min_bias`` to count)."""
    human = [as_bool(it["human"]) for it in items]
    judge = [as_bool(it["judge"]) for it in items]
    report = {"overall": _block(human, judge)}

    groups = defaultdict(lambda: ([], []))
    for it, h, j in zip(items, human, judge):
        g = it.get("group", it.get("difficulty", it.get("band")))
        if g is not None:
            groups[str(g)][0].append(h)
            groups[str(g)][1].append(j)
    report["groups"] = {g: _block(h, j, with_ci=False) for g, (h, j) in sorted(groups.items())}

    signed = {g: b["bias"] for g, b in report["groups"].items()
              if b["n"] >= min_group_n and b["bias"] is not None and abs(b["bias"]) >= min_bias}
    report["sign_reversal"] = (any(v > 0 for v in signed.values())
                               and any(v < 0 for v in signed.values()))
    report["lenient_groups"] = sorted(g for g, v in signed.items() if v > 0)
    report["harsh_groups"] = sorted(g for g, v in signed.items() if v < 0)

    if all("judge_score" in it for it in items) and len(items) >= 10:
        report["threshold"] = _tune_threshold([float(it["judge_score"]) for it in items], human)

    o = report["overall"]
    reasons = []
    if o["n"] < min_n:
        reasons.append(f"only {o['n']} labelled items (need {min_n})")
    if o["kappa_ci"] is None or o["kappa_ci"][0] < min_kappa:
        lo = "n/a" if o["kappa_ci"] is None else o["kappa_ci"][0]
        reasons.append(f"kappa lower bound {lo} < {min_kappa}")
    if o["false_pass_rate"] is not None and o["false_pass_rate"] > max_false_pass:
        reasons.append(f"false-pass rate {o['false_pass_rate']} > {max_false_pass} "
                       "(judge passes outputs humans fail)")
    if report["sign_reversal"]:
        reasons.append(f"bias changes sign across groups: lenient on {', '.join(report['lenient_groups'])}, "
                       f"harsh on {', '.join(report['harsh_groups'])}")
    report["fit_to_gate"] = not reasons
    report["reasons"] = reasons
    report["thresholds"] = {"min_kappa": min_kappa, "max_false_pass": max_false_pass,
                            "min_n": min_n}
    return report
