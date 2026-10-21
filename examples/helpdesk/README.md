# holdline on helpdesk-agent

Runs holdline over [helpdesk-agent](https://github.com/Aashan47/helpdesk-agent)'s 68 labelled
support tickets, without modifying helpdesk-agent.

```bash
git clone https://github.com/Aashan47/helpdesk-agent ../../../helpdesk-agent   # or set HDA_REPO
python build_suite.py                                    # -> helpdesk_cases.jsonl
export GEMINI_API_KEY=...
holdline run --suite helpdesk_cases.jsonl --target target:agent -k 3 --out results/production-k3.json
HDA_SAMPLES=1 holdline run --suite helpdesk_cases.jsonl --target target:agent -k 3 --out results/one-sample-k3.json
holdline gate --baseline results/production-k3.json --candidate results/one-sample-k3.json --html results/gate-one-sample.html
```

- 46 covered tickets must be answered correctly (helpdesk-agent's own rule: exact match or token
  F1 >= 0.5) and cite the right article.
- 22 uncovered tickets must be escalated to a human. They are must-pass.
- Every run must search at least once, make at most 4 searches, and never repeat one.
- A model outage raises, so it is recorded as an error, never as a correct escalation.

Results from 2026-10-21 are in `results/` and summarised in the main README.
