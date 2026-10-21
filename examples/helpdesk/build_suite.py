"""Turn helpdesk-agent's 68 labelled support tickets into a holdline suite.

    HDA_REPO=../helpdesk-agent python build_suite.py      # writes helpdesk_cases.jsonl

Covered tickets must be answered, correctly (helpdesk-agent's own rule: exact match or token
F1 >= 0.5 against any gold answer) and citing the gold article. Uncovered tickets must be
escalated to a human and are must-pass: a wrong reply to a question the help centre does not
cover is the failure the product exists to prevent.
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.environ.get("HDA_REPO", os.path.join(HERE, "..", "..", "..", "helpdesk-agent")))
sys.path.insert(0, REPO)

from helpdesk_agent import corpus  # noqa: E402


def slugify(text: str, taken: set) -> str:
    base = "-".join(re.findall(r"[a-z0-9]+", text.lower())[:7]) or "ticket"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    taken.add(slug)
    return slug


def main() -> None:
    kb = corpus.load_knowledge_base()
    by_slug = {a["slug"]: (i, a) for i, a in enumerate(kb["articles"])}
    tickets = json.load(open(os.path.join(REPO, "knowledge_base", "tickets.json")))
    taken: set = set()
    cases = []
    for t in tickets:
        cid = slugify(t["question"], taken)
        # One search to start, plus at most HDA_MAX_STEPS (3) reformulations.
        trajectory = {"tools_required": ["search"], "max_tool_calls": 4, "no_loops": True}
        if t["is_impossible"]:
            cases.append({"id": cid, "input": t["question"],
                          "expected": {"outcome": "escalate", **trajectory},
                          "tags": ["uncovered"], "must_pass": True})
            continue
        gold_idx, art = by_slug[t["article"]]
        cases.append({"id": cid, "input": t["question"],
                      "expected": {"outcome": "answer", **trajectory,
                                   "checks": ["helpdesk_correct", "cites_gold_article"]},
                      "tags": ["covered", art["category"]],
                      "meta": {"answers": t["answers"], "gold_article": t["article"],
                               "gold_ctx": gold_idx}})
    out = os.path.join(HERE, "helpdesk_cases.jsonl")
    with open(out, "w", encoding="utf-8") as fh:
        for c in cases:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    n_unc = sum(1 for c in cases if c.get("must_pass"))
    print(f"wrote {len(cases)} cases ({len(cases) - n_unc} covered, {n_unc} uncovered) to {out}")


if __name__ == "__main__":
    main()
