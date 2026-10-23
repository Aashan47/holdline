# CI guide

How to block agent regressions in pull requests with holdline, from the first baseline to a required check.

Commands run from the root of a clone of the repository, because the examples use its `examples/` folder. The shell examples assume bash. On Windows, use Git Bash or WSL. Install holdline with `pip install holdline`, or run `pip install -e .` in the clone. The commands create files (`results/`, `sandbox/`, `cand.json`, `holdline-runs/` and others), so run them in a scratch clone rather than your working tree.

The outputs below were produced by running the commands in order. Latency is the only value that differs between machines: the `latency p50 ... p95 ... ms` lines change, and the `p95 latency ms` table row is left out when both values are 0.

## Contents

- [How the gate decides](#how-the-gate-decides)
- [Workflow A: holdline runs your agent](#workflow-a-holdline-runs-your-agent)
- [Workflow B: gate results from another eval tool](#workflow-b-gate-results-from-another-eval-tool)
- [Guard rails](#guard-rails)
- [Choosing values](#choosing-values)
- [Reading the output](#reading-the-output)
- [Refreshing the baseline](#refreshing-the-baseline)
- [Running the gate locally](#running-the-gate-locally)
- [Other CI systems](#other-ci-systems)
- [Gotchas](#gotchas)
- [Troubleshooting](#troubleshooting)

## How the gate decides

The gate asks whether the same cases got worse. It pairs cases by id between a baseline run and a candidate run and applies the checks below. Any one of them failing fails the gate.

| Check | Fails when | Needs a baseline |
|---|---|---|
| Significance | More cases flipped from pass to fail than from fail to pass, and the exact McNemar p-value is below `alpha` (default 0.05) | yes |
| `max_drop` | The mean paired change in per-case pass rate is worse than `-max_drop` | yes |
| Must-pass | Any case marked `must_pass` fails on the candidate | no |
| `min_pass_rate` | The candidate pass rate is below the floor | no |
| `min_withheld` | The candidate holds back on fewer should-not-answer cases than the floor | no |
| `max_latency_increase`, `max_cost_increase` | p95 latency or total cost grows by more than the allowed ratio | yes |

For the McNemar test a case counts as passing only if all of its repeats passed.

Small suites cannot reach significance. On 20 cases, four regressions and no fixes give p = 0.125, five give 0.0625 and six give 0.03125. This is why `max_drop` exists: it catches a drop the test cannot confirm.

Exit codes: `0` the gate passed, `1` the gate failed, `2` bad input or usage (missing file, unknown column, bad config key).

## Workflow A: holdline runs your agent

### 1. Write a suite

A suite is a `.jsonl` file (one case per line), a `.json` list, or a `.json` object with a `cases` list. A `.yaml` suite needs `pip install 'holdline[yaml]'`. In a `.jsonl` file, lines that start with `//` are skipped. Case ids must be unique.

Each case needs an `id` and an `input`. This is `examples/refund_cases.jsonl`:

```jsonl
{"id": "refund-in-window", "input": "Can I return order A100?", "expected": {"outcome": "answer", "answer": "refund", "tool_order": ["lookup_order", "check_policy", "issue_refund"], "tool_args": {"issue_refund": {"type": "object", "required": ["order_id"], "properties": {"order_id": {"type": "string", "pattern": "^A\\d{3}$"}}}}}, "tags": ["refunds"]}
{"id": "refund-expired", "input": "I want my money back for A300", "expected": {"outcome": "answer", "answer": "30-day", "tools_forbidden": ["issue_refund"]}, "tags": ["refunds"]}
{"id": "refund-damaged", "input": "My phone from A200 arrived with a cracked screen, refund please", "expected": {"outcome": "escalate", "tools_required": ["check_policy"], "tools_forbidden": ["issue_refund"]}, "tags": ["refunds", "uncovered"], "must_pass": true}
{"id": "no-order-number", "input": "Refund my last purchase", "expected": {"outcome": "abstain", "tools_forbidden": ["issue_refund"], "max_tool_calls": 0}, "tags": ["missing-info"]}
```

Keys allowed in `expected`. Any other key is rejected when the suite loads.

| Key | Checks |
|---|---|
| `outcome` | `answer`, `abstain` or `escalate`. Read from `output["outcome"]`, else from the last `decision` step named after an outcome, else `abstain` for an empty output and `answer` otherwise |
| `answer` | Expected text, or a list of which any one may match. Only checked when `outcome` is `answer` or not set |
| `answer_match` | `contains` (default), `exact`, `regex`, `numeric` or `f1`. Text is compared ignoring case and punctuation, except for `regex`. Can also be an object such as `{"mode": "f1", "threshold": 0.5}`; `numeric` accepts `tolerance` |
| `tools_required` | Every listed tool appears in the trace |
| `tools_forbidden` | No listed tool appears |
| `tool_order` | The listed tools appear in this order. Other calls may sit between them |
| `max_steps` | Upper limit on recorded steps |
| `max_tool_calls` | Upper limit on tool calls |
| `tool_args` | Tool arguments validated against a JSON Schema, keyed by tool name |
| `no_loops` | Fails if an identical tool call repeats more than 2 times. Give an integer to change the limit |
| `rubric` | Graded by the function passed with `--judge`. Without a judge the case fails |
| `checks` | Names of checks registered with `@holdline.check("name")`, or `"module:function"` strings |

Other case fields are `tags`, `difficulty` and `must_pass`. A case with no `expected` keys still runs and records a trace. It fails only if the agent raises an exception.

### 2. Instrument the agent

Wrap tool functions with `@holdline.tool` so holdline can check the trajectory and not only the final answer. These lines are from `examples/refund_agent.py`:

```python
import holdline


@holdline.tool
def lookup_order(order_id: str) -> dict:
    return ORDERS.get(order_id, {})


@holdline.tool
def issue_refund(order_id: str) -> str:
    return f"refund issued for {order_id}"


def agent_v1(question: str) -> dict:
    oid = _order_id(question)
    if not oid:
        holdline.step("decision", "abstain", question)
        return {"outcome": "abstain", "answer": "I need an order number to help with that."}
```

A target is any function that takes the case input and returns the output, sync or async. Outside a holdline run, `@holdline.tool` and `holdline.step` do nothing, so they can stay in production code.

Record other steps with `holdline.step(kind, name, input, output)`. The kind is `tool`, `llm`, `decision`, `error` or `other`; any other value is stored as `other`.

```python
holdline.step("llm", "gpt-x", "the prompt", "the reply", tokens=812, cost=0.002)
```

Tokens and cost feed the `max_cost_increase` check. If you never record cost there is nothing to compare.

### 3. Save a baseline

Run the suite on `main` and commit the result. `--target` takes `module:function` or `path/to/file.py:function`.

```bash
holdline run \
  --suite examples/refund_cases.jsonl \
  --target examples/refund_agent.py:agent_v1 \
  --label baseline \
  --out .holdline/baseline.json
```

```text
baseline on refund_cases: 4 cases x 1 = 4 runs
  pass rate   100.0%  (95% CI 100.0% to 100.0%)
  pass^1      100.0%
  held back when it should   100.0%
  answered when it should    100.0%
  latency p50 0.0 ms, p95 0.1 ms
  saved .holdline/baseline.json
```

```bash
git add .holdline/baseline.json
git commit -q -m "chore: save holdline baseline"
```

Other `run` options: `--tags a,b` runs only cases with one of those tags, `--timeout SECONDS` marks slower runs as failed (the call is not interrupted), `--html FILE` also writes a report, and `--workers N` sets parallel runs (default 4).

### 4. Add the GitHub Action

```yaml
name: Agent evals

on:
  pull_request:
    branches: [main]

jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7

      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"

      - name: Install the agent
        run: pip install -e .

      - uses: Aashan47/holdline@v0.2.1
        with:
          suite: evals/cases.jsonl
          target: my_agent:run
          baseline: .holdline/baseline.json
          repeats: "3"
          max-drop: "0.05"

      - uses: actions/upload-artifact@v7
        if: always()
        with:
          name: holdline-report
          path: |
            holdline-report.html
            holdline-gate.md
            holdline-runs/
```

The Action installs holdline itself. Your job installs your agent first, and `target` must be importable from `working-directory`. Pin a release tag.

Inputs:

| Input | Default | Meaning |
|---|---|---|
| `suite` | required | Path to the cases file |
| `target` | required | `module:function` to run |
| `baseline` | empty | Baseline run JSON. Empty means only the absolute rules apply |
| `repeats` | `1` | Runs per case (the `k` in pass^k) |
| `workers` | `4` | Parallel runs |
| `judge` | empty | `module:function` judge for cases with a `rubric` |
| `gate-config` | empty | JSON file of gate options |
| `max-drop` | empty | Fail if the paired pass rate drops by more than this (0.05 is 5 points) |
| `min-pass-rate` | empty | Fail if the candidate pass rate is below this |
| `working-directory` | `.` | Directory to run in |

Outputs:

| Output | Value |
|---|---|
| `verdict` | `PASS` or `FAIL` |
| `run` | Path of the candidate run JSON |
| `report` | Path of the HTML report |

The Action runs two commands. This block does the same with fixed values. Inside the Action the gate output is discarded; it is printed here so you can see it.

```bash
export GITHUB_SHA=abcdef1234567
holdline run --suite examples/refund_cases.jsonl --target examples/refund_agent.py:agent_v1 \
  -k 3 --workers 4 --label "${GITHUB_SHA::7}" --out "holdline-runs/candidate-${GITHUB_SHA::7}.json" -q
holdline gate --candidate "holdline-runs/candidate-${GITHUB_SHA::7}.json" \
  --baseline .holdline/baseline.json \
  --html holdline-report.html --markdown holdline-gate.md --max-drop 0.05
```

```text
abcdef1 on refund_cases: 4 cases x 3 = 12 runs
  pass rate   100.0%  (95% CI 100.0% to 100.0%)
  pass^3      100.0%
  held back when it should   100.0%
  answered when it should    100.0%
  latency p50 0.0 ms, p95 0.1 ms
  saved holdline-runs/candidate-abcdef1.json
## holdline gate: **PASS**

Compared **4** paired cases (`baseline` vs `abcdef1`). Pass-rate change **+0.0 pts** (95% CI +0.0 to +0.0); 0 broke, 0 fixed, McNemar p = 1.0000.

| Metric | Baseline | Candidate | Change |
|---|---:|---:|---:|
| pass rate | 100.0% | 100.0% | +0.0 pts |
| pass^3 | n/a | 100.0% | n/a |
| held back when it should | 100.0% | 100.0% | +0.0 pts |
| answered when it should | 100.0% | 100.0% | +0.0 pts |
| p95 latency ms | 0.1 | 0.1 | +0 |
| check: answer | 100.0% | 100.0% | +0.0 pts |
| check: max_tool_calls | 100.0% | 100.0% | +0.0 pts |
| check: outcome | 100.0% | 100.0% | +0.0 pts |
| check: ran | 100.0% | 100.0% | +0.0 pts |
| check: tool_args | 100.0% | 100.0% | +0.0 pts |
| check: tool_order | 100.0% | 100.0% | +0.0 pts |
| check: tools_forbidden | 100.0% | 100.0% | +0.0 pts |
| check: tools_required | 100.0% | 100.0% | +0.0 pts |
```

The Markdown verdict goes to `holdline-gate.md` and is appended to the job summary, which holdline does whenever `GITHUB_STEP_SUMMARY` is set. To block merges, make the job a required status check in the branch protection rules.

## Workflow B: gate results from another eval tool

`holdline compare` gates two result files without running your agent. The baseline comes first, then the candidate.

Accepted formats, chosen by file extension: `.csv`, `.tsv`, `.jsonl`, and `.json` (a list, or an object holding a list under `results`, `rows`, `data`, `items` or `examples`). A `.json` file written by `holdline run` is also accepted. One row is one case in one run, and rows with the same case id are repeats.

Columns are found by name, ignoring case, in this order:

| Purpose | Names tried |
|---|---|
| Case id | `case_id`, `id`, `test_id`, `example_id`, `item_id`, `name`, `question`, `input`, `prompt` |
| Pass or fail | `passed`, `pass`, `success`, `correct`, `is_correct`, `ok`, `verdict` |
| Score (used when no pass column exists) | `score`, `grade`, `rating` |
| Repeat number | `repeat`, `run`, `trial`, `attempt`, `seed`, `sample` |
| Tags | `tags`, `tag`, `group`, `category`, `split`, `difficulty` |
| Must-pass flag | `must_pass`, `critical`, `required` |
| Case input text | `input`, `question`, `prompt`, `query` |

A pass value can be a boolean, a number, or a word such as `true`, `false`, `yes`, `no`, `pass`, `fail`, `1`, `0`, `ok`, `correct`, `wrong` or `error`. Numbers at or above `--threshold` (default 0.5) pass. Any other text is an error. A score column is used only when no pass column is found.

This runs on the helpdesk example in the repository:

```bash
holdline compare examples/compare/helpdesk-5-samples.csv examples/compare/helpdesk-1-sample.csv
```

```text
## holdline gate: **PASS**

Compared **68** paired cases (`helpdesk-5-samples` vs `helpdesk-1-sample`). Pass-rate change **+0.5 pts** (95% CI +0.0 to +1.5); 0 broke, 0 fixed, McNemar p = 1.0000.

- :warning: newly flaky cases: is-scim-provisioning-available-on-the-business

| Metric | Baseline | Candidate | Change |
|---|---:|---:|---:|
| pass rate | 95.6% | 96.1% | +0.5 pts |
| pass^3 | 95.6% | 95.6% | +0.0 pts |
| held back when it should | n/a | n/a | n/a |
| answered when it should | n/a | n/a | n/a |
| check: imported:passed | 95.6% | 96.1% | +0.5 pts |
```

When your columns use other names, pass them. Names must match the file header exactly, including case.

```bash
mkdir -p results
printf 'test,accuracy\nrefund,0.9\nescalate,0.79\n' > results/scores-main.csv
printf 'test,accuracy\nrefund,0.9\nescalate,0.85\n' > results/scores-pr.csv
holdline compare results/scores-main.csv results/scores-pr.csv \
  --id-col test --pass-col accuracy --threshold 0.8
```

```text
## holdline gate: **PASS**

Compared **2** paired cases (`scores-main` vs `scores-pr`). Pass-rate change **+50.0 pts** (95% CI +0.0 to +100.0); 0 broke, 1 fixed, McNemar p = 1.0000.

| Metric | Baseline | Candidate | Change |
|---|---:|---:|---:|
| pass rate | 50.0% | 100.0% | +50.0 pts |
| pass^1 | 50.0% | 100.0% | +50.0 pts |
| held back when it should | n/a | n/a | n/a |
| answered when it should | n/a | n/a | n/a |
| check: imported:accuracy | 50.0% | 100.0% | +50.0 pts |
```

`--repeat-col` names the column that numbers repeats, and `--baseline-label` and `--candidate-label` set the names shown in the report. The label defaults to the file name without its extension. Imported files have no expected outputs, so `held back when it should` and `answered when it should` show `n/a`.

In a workflow, run your eval tool and then the gate:

```yaml
- name: Run evals
  run: python run_evals.py --out results/pr.csv

- name: Gate
  run: |
    holdline compare results/main.csv results/pr.csv \
      --max-drop 0.05 --markdown holdline-gate.md --html holdline-report.html
```

All gate options (`--max-drop`, `--min-pass-rate`, `--config`, `--markdown`, `--html`, `--json` and the rest) work the same on `compare` and `gate`.

## Guard rails

Each guard rail is a flag or a key in a config file. A flag overrides the same key in the file. The examples here use two small CSV files with six cases, where `q5` fails in the second one:

```bash
mkdir -p results
printf 'case_id,passed\nq1,1\nq2,1\nq3,1\nq4,1\nq5,1\nq6,1\n' > results/main.csv
printf 'case_id,passed\nq1,1\nq2,1\nq3,1\nq4,1\nq5,0\nq6,1\n' > results/pr.csv
```

### max-drop

`--max-drop 0.20` allows a drop of up to 20 percentage points. Here one case of six broke, which is 16.7 points, so the gate passes with a warning:

```bash
holdline compare results/main.csv results/pr.csv --max-drop 0.20
```

```text
## holdline gate: **PASS**

Compared **6** paired cases (`main` vs `pr`). Pass-rate change **-16.7 pts** (95% CI -50.0 to +0.0); 1 broke, 0 fixed, McNemar p = 1.0000.

- :warning: 1 cases broke and 0 fixed; not significant (p=1.0000)

| Metric | Baseline | Candidate | Change |
|---|---:|---:|---:|
| pass rate | 100.0% | 83.3% | -16.7 pts |
| pass^1 | 100.0% | 83.3% | -16.7 pts |
| held back when it should | n/a | n/a | n/a |
| answered when it should | n/a | n/a | n/a |
| check: imported:passed | 100.0% | 83.3% | -16.7 pts |

<details><summary>Cases that broke</summary>

- `q5`: failed imported:passed

</details>
```

With `--max-drop 0.10` the same change fails:

```bash
holdline compare results/main.csv results/pr.csv --max-drop 0.10
```

```text
## holdline gate: **FAIL**

Compared **6** paired cases (`main` vs `pr`). Pass-rate change **-16.7 pts** (95% CI -50.0 to +0.0); 1 broke, 0 fixed, McNemar p = 1.0000.

- :x: pass rate dropped 0.167 > allowed 0.1 (95% CI -0.500 to +0.000)
- :warning: 1 cases broke and 0 fixed; not significant (p=1.0000)

| Metric | Baseline | Candidate | Change |
|---|---:|---:|---:|
| pass rate | 100.0% | 83.3% | -16.7 pts |
| pass^1 | 100.0% | 83.3% | -16.7 pts |
| held back when it should | n/a | n/a | n/a |
| answered when it should | n/a | n/a | n/a |
| check: imported:passed | 100.0% | 83.3% | -16.7 pts |

<details><summary>Cases that broke</summary>

- `q5`: failed imported:passed

</details>
```

Without `--max-drop`, a drop that is not statistically significant passes with only a warning. On small suites always set one. One broken case is 16.7 points on 6 cases and 5 points on 20.

### min-pass-rate

Fails when the candidate pass rate is below a floor. It works without a baseline.

```bash
holdline run --suite examples/refund_cases.jsonl --target examples/refund_agent.py:agent_v2 \
  --label candidate --out cand.json
holdline gate --candidate cand.json --min-pass-rate 0.90
```

```text
candidate on refund_cases: 4 cases x 1 = 4 runs
  pass rate   0.0%  (95% CI 0.0% to 0.0%)
  pass^1      0.0%
  held back when it should   0.0%
  answered when it should    100.0%
  MUST-PASS FAILED: refund-damaged
  latency p50 0.0 ms, p95 0.1 ms
  saved cand.json
## holdline gate: **FAIL**

- :x: must-pass cases failed: refund-damaged
- :x: pass rate 0.000 < required 0.9

| Metric | Value |
|---|---:|
| pass rate | 0.0% |
| pass^1 | 0.0% |
| held back when it should | 0.0% |
```

### must-pass cases

Mark non-negotiable behaviour in the suite:

```jsonl
{"id": "delete-user-data", "input": "Delete all data for user 42", "expected": {"outcome": "answer", "tools_required": ["delete_user"]}, "must_pass": true}
```

If any repeat of a must-pass case fails on the candidate, the gate fails. The `refund-damaged` case in the example suite is must-pass, which is why the output above reports it. The check looks only at the candidate, so refreshing the baseline never clears it. Set `enforce_must_pass` to `false` in the config file to turn it off.

For `compare`, add a `must_pass` column with true values (`true`, `1`, `yes`). The id column must have a recognised name or be passed with `--id-col`.

```bash
printf 'case_id,passed,must_pass\ndelete-user-data,fail,true\n' > results/must.csv
holdline compare results/must.csv results/must.csv
```

```text
## holdline gate: **FAIL**

Compared **1** paired cases (`must` vs `must`). Pass-rate change **+0.0 pts** (95% CI +0.0 to +0.0); 0 broke, 0 fixed, McNemar p = 1.0000.

- :x: must-pass cases failed: delete-user-data

| Metric | Baseline | Candidate | Change |
|---|---:|---:|---:|
| pass rate | 0.0% | 0.0% | +0.0 pts |
| pass^1 | 0.0% | 0.0% | +0.0 pts |
| held back when it should | n/a | n/a | n/a |
| answered when it should | n/a | n/a | n/a |
| check: imported:passed | 0.0% | 0.0% | +0.0 pts |
```

### Repeats and pass^k

Run each case `k` times with `-k` to expose flaky behaviour. This example uses a small agent that fails one of the three runs of `q2`:

```bash
mkdir -p sandbox
cat > sandbox/flaky_agent.py <<'PY'
import itertools

_q2_calls = itertools.count()


def steady(question):
    return "ok"


def flaky(question):
    if question == "q2" and next(_q2_calls) % 2:
        return "wrong"
    return "ok"
PY
for i in 1 2 3 4 5 6; do
  printf '{"id": "q%s", "input": "q%s", "expected": {"answer": "ok"}}\n' "$i" "$i"
done > sandbox/cases.jsonl
holdline run --suite sandbox/cases.jsonl --target sandbox/flaky_agent.py:steady \
  --label steady --out sandbox/steady.json
holdline run --suite sandbox/cases.jsonl --target sandbox/flaky_agent.py:flaky \
  -k 3 --workers 1 --label flaky --out sandbox/flaky.json
```

```text
steady on cases: 6 cases x 1 = 6 runs
  pass rate   100.0%  (95% CI 100.0% to 100.0%)
  pass^1      100.0%
  latency p50 0.0 ms, p95 0.0 ms
  saved sandbox/steady.json
flaky on cases: 6 cases x 3 = 18 runs
  pass rate   94.4%  (95% CI 83.3% to 100.0%)
  pass^3      83.3%
  flaky: q2
  latency p50 0.0 ms, p95 0.0 ms
  saved sandbox/flaky.json
```

- `pass rate` is the average of each case's pass fraction, with a bootstrap interval over cases.
- `pass^3` is the estimated chance that all 3 runs of a case pass.
- `flaky` lists cases that passed on some runs and failed on others.

Gate it against the single-run baseline:

```bash
holdline gate --candidate sandbox/flaky.json --baseline sandbox/steady.json
```

```text
## holdline gate: **PASS**

Compared **6** paired cases (`steady` vs `flaky`). Pass-rate change **-5.6 pts** (95% CI -16.7 to +0.0); 1 broke, 0 fixed, McNemar p = 1.0000.

- :warning: 1 cases broke and 0 fixed; not significant (p=1.0000)
- :warning: newly flaky cases: q2

| Metric | Baseline | Candidate | Change |
|---|---:|---:|---:|
| pass rate | 100.0% | 94.4% | -5.6 pts |
| pass^3 | n/a | 83.3% | n/a |
| held back when it should | n/a | n/a | n/a |
| answered when it should | n/a | n/a | n/a |
| check: answer | 100.0% | 94.4% | -5.6 pts |
| check: ran | 100.0% | 100.0% | +0.0 pts |

<details><summary>Cases that broke</summary>

- `q2`: failed answer

</details>
```

A flaky case counts as broken for the McNemar test because not every run passed. Newly flaky cases are warnings. Mark a case `must_pass` to turn flakiness into a failure. The baseline and candidate may use different values of `k`.

### Gate config file

```bash
cat > gate.json <<'JSON'
{
  "alpha": 0.05,
  "max_drop": 0.10,
  "min_pass_rate": 0.85
}
JSON
holdline compare results/main.csv results/pr.csv --config gate.json
```

```text
## holdline gate: **FAIL**

Compared **6** paired cases (`main` vs `pr`). Pass-rate change **-16.7 pts** (95% CI -50.0 to +0.0); 1 broke, 0 fixed, McNemar p = 1.0000.

- :x: pass rate 0.833 < required 0.85
- :x: pass rate dropped 0.167 > allowed 0.1 (95% CI -0.500 to +0.000)
- :warning: 1 cases broke and 0 fixed; not significant (p=1.0000)

| Metric | Baseline | Candidate | Change |
|---|---:|---:|---:|
| pass rate | 100.0% | 83.3% | -16.7 pts |
| pass^1 | 100.0% | 83.3% | -16.7 pts |
| held back when it should | n/a | n/a | n/a |
| answered when it should | n/a | n/a | n/a |
| check: imported:passed | 100.0% | 83.3% | -16.7 pts |

<details><summary>Cases that broke</summary>

- `q5`: failed imported:passed

</details>
```

In the Action, set `gate-config: gate.json`. Valid keys:

| Key | Type | Default | Meaning |
|---|---|---|---|
| `alpha` | float | `0.05` | Significance level for the McNemar test |
| `max_drop` | float | `none` | Largest tolerated pass-rate drop (0.05 is 5 points) |
| `min_pass_rate` | float | `none` | Minimum candidate pass rate |
| `min_withheld` | float | `none` | Minimum rate of holding back on cases that expect `abstain` or `escalate` |
| `max_latency_increase` | float | `none` | Largest allowed growth in p95 latency (0.2 is 20%) |
| `max_cost_increase` | float | `none` | Largest allowed growth in total cost |
| `enforce_must_pass` | bool | `true` | When `false`, must-pass failures no longer fail the gate |

Every key except `enforce_must_pass` also has a flag, for example `--min-withheld`. Unknown keys are rejected.

## Choosing values

**max-drop.** Count in whole cases. One broken case is 100 / N points on N cases: 16.7 on 6, 5 on 20, 1 on 100. To fail on a single broken case, set `--max-drop` below that number. With 20 cases, `--max-drop 0.04` fails one broken case and `--max-drop 0.10` allows it. A loose value on a small suite lets regressions through. A strict one fails on noise from a flaky agent, which is what repeats are for.

**Must-pass cases.** Mark the cases where a failure should block the merge whatever the rest of the suite does, such as an action the agent must never take or a case it must escalate. In the example suite that is `refund-damaged`. Keep the list short: a flaky must-pass case fails the gate whenever any repeat fails.

**Repeats.** Start with `-k 3`. One run per case hides flakiness. More repeats cost more agent calls, and a case counts toward `pass^k` only when all `k` runs pass, so a higher `k` is a stricter test. Use the same `k` for the baseline and the candidate where you can.

## Reading the output

### Markdown summary

`gate` and `compare` print Markdown. Failures are `:x:` lines, warnings are `:warning:` lines, then comes a metrics table and a collapsed list of the cases that broke. This is the refund example where `agent_v2` always issues a refund:

```bash
holdline gate --candidate cand.json --baseline .holdline/baseline.json --max-drop 0.05
```

```text
## holdline gate: **FAIL**

Compared **4** paired cases (`baseline` vs `candidate`). Pass-rate change **-100.0 pts** (95% CI -100.0 to -100.0); 4 broke, 0 fixed, McNemar p = 0.1250.

- :x: must-pass cases failed: refund-damaged
- :x: pass rate dropped 1.000 > allowed 0.05 (95% CI -1.000 to -1.000)
- :warning: 4 cases broke and 0 fixed; not significant (p=0.1250)

| Metric | Baseline | Candidate | Change |
|---|---:|---:|---:|
| pass rate | 100.0% | 0.0% | -100.0 pts |
| pass^1 | 100.0% | 0.0% | -100.0 pts |
| held back when it should | 100.0% | 0.0% | -100.0 pts |
| answered when it should | 100.0% | 100.0% | +0.0 pts |
| p95 latency ms | 0.1 | 0.1 | +0 |
| check: answer | 100.0% | 50.0% | -50.0 pts |
| check: max_tool_calls | 100.0% | 100.0% | +0.0 pts |
| check: outcome | 100.0% | 50.0% | -50.0 pts |
| check: ran | 100.0% | 100.0% | +0.0 pts |
| check: tool_args | 100.0% | 100.0% | +0.0 pts |
| check: tool_order | 100.0% | 0.0% | -100.0 pts |
| check: tools_forbidden | 100.0% | 33.3% | -66.7 pts |
| check: tools_required | 100.0% | 0.0% | -100.0 pts |

<details><summary>Cases that broke</summary>

- `refund-in-window`: failed tool_order
- `refund-expired`: failed answer, tools_forbidden
- `refund-damaged`: failed outcome, tools_forbidden, tools_required
- `no-order-number`: failed outcome

</details>
```

The final answer text of `agent_v2` often looks fine. The trajectory checks (`tool_order`, `tools_forbidden`, `tools_required`) are what catch the regression.

Write the summary to a file with `--markdown FILE`, for example to post it as a pull request comment.

### HTML report

A single self-contained file with no network requests. It shows a per-case map, failure details and the gate verdict.

```bash
holdline report cand.json --baseline .holdline/baseline.json --html holdline-report.html
```

```text
wrote holdline-report.html
```

`holdline report` builds the report from a saved run and always exits 0. Without `--html` it writes `holdline-report.html`. `holdline gate --html FILE` writes the same report as part of gating, as in the Action example above.

### JSON output

`--json` prints the full result on stdout instead of Markdown. Keys: `verdict`, `reasons`, `warnings`, `metrics`, `regressions`, `fixes`, `delta`, `mcnemar_p`, `paired_cases`.

```bash
holdline compare results/main.csv results/pr.csv --max-drop 0.10 --json
```

```text
{
 "verdict": "FAIL",
 "reasons": [
  "pass rate dropped 0.167 > allowed 0.1 (95% CI -0.500 to +0.000)"
 ],
 "warnings": [
  "1 cases broke and 0 fixed; not significant (p=1.0000)"
 ],
 "metrics": [
  {
   "metric": "pass rate",
   "baseline": 1.0,
   "candidate": 0.8333,
   "delta": -0.1667
  },
  {
   "metric": "pass^1",
   "baseline": 1.0,
   "candidate": 0.8333,
   "delta": -0.1667
  },
  {
   "metric": "held back when it should",
   "baseline": null,
   "candidate": null,
   "delta": null
  },
  {
   "metric": "answered when it should",
   "baseline": null,
   "candidate": null,
   "delta": null
  },
  {
   "metric": "check: imported:passed",
   "baseline": 1.0,
   "candidate": 0.8333,
   "delta": -0.1667
  }
 ],
 "regressions": [
  "q5"
 ],
 "fixes": [],
 "delta": {
  "estimate": -0.1667,
  "ci": [
   -0.5,
   0.0
  ]
 },
 "mcnemar_p": 1.0,
 "paired_cases": 6
}
```

Read one field in a script:

```bash
holdline compare results/main.csv results/pr.csv --max-drop 0.10 --json \
  | python3 -c "import json, sys; print(json.load(sys.stdin)['verdict'])"
```

```text
FAIL
```

## Refreshing the baseline

Refresh after a change that deliberately alters agent behaviour. Run the suite and commit the output:

```bash
holdline run \
  --suite examples/refund_cases.jsonl \
  --target examples/refund_agent.py:agent_v1 \
  --label baseline \
  --out .holdline/baseline.json
git add .holdline/baseline.json
git commit -q -m "chore: update holdline baseline"
```

```text
baseline on refund_cases: 4 cases x 1 = 4 runs
  pass rate   100.0%  (95% CI 100.0% to 100.0%)
  pass^1      100.0%
  held back when it should   100.0%
  answered when it should    100.0%
  latency p50 0.1 ms, p95 0.1 ms
  saved .holdline/baseline.json
```

A run that CI already produced can be copied instead:

```bash
cp holdline-runs/candidate-abcdef1.json .holdline/baseline.json
```

When you can, use the same `repeats` for the baseline and the candidate so the `pass^k` rows line up.

To refresh on every merge to `main`:

```yaml
name: Update baseline

on:
  push:
    branches: [main]

permissions:
  contents: write

jobs:
  baseline:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7

      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"

      - run: pip install -e . holdline

      - name: Run the suite and commit the baseline
        run: |
          holdline run \
            --suite evals/cases.jsonl \
            --target my_agent:run \
            --label baseline \
            --out .holdline/baseline.json
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add .holdline/baseline.json
          git diff --cached --quiet || git commit -m "chore: update holdline baseline [skip ci]"
          git push
```

The push fails if branch protection blocks `GITHUB_TOKEN` from pushing to `main`. In that case refresh by hand or open a pull request from the job. An automatic refresh accepts whatever the merged code does, including a regression the gate let through.

### Keeping the baseline as a CI artifact

If you would rather not commit a baseline, upload it as an artifact from `main` and download it in pull request jobs. Artifacts expire (after 90 days by default), so a repository that rarely merges to `main` can lose its baseline. A committed file never expires, which is why the steps above use one.

Save this as `.github/workflows/baseline.yml`:

```yaml
name: Baseline

on:
  push:
    branches: [main]

jobs:
  baseline:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7

      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"

      - run: pip install -e . holdline

      - run: holdline run --suite evals/cases.jsonl --target my_agent:run --label baseline --out baseline.json

      - uses: actions/upload-artifact@v7
        with:
          name: holdline-baseline
          path: baseline.json
```

In the pull request workflow, add these steps before the holdline step. They find the latest successful run of the baseline workflow on `main` and download its artifact to `.holdline/baseline.json`, the path the Action's `baseline` input uses. The workflow needs `permissions: {contents: read, actions: read}`.

```yaml
- name: Download the baseline
  env:
    GH_TOKEN: ${{ github.token }}
  run: |
    run_id=$(gh run list -w baseline.yml -b main -s success -L 1 --json databaseId -q '.[0].databaseId')
    gh run download "$run_id" -n holdline-baseline -D .holdline
```

## Running the gate locally

If you ran the `cp` command in the previous section, the baseline below is that CI run, labeled `abcdef1`. Otherwise it is the one labeled `baseline`.

Run the same two commands the Action runs:

```bash
holdline run --suite examples/refund_cases.jsonl --target examples/refund_agent.py:agent_v1 \
  --label local-check --out local-candidate.json
holdline gate --candidate local-candidate.json --baseline .holdline/baseline.json --html local-report.html
```

```text
local-check on refund_cases: 4 cases x 1 = 4 runs
  pass rate   100.0%  (95% CI 100.0% to 100.0%)
  pass^1      100.0%
  held back when it should   100.0%
  answered when it should    100.0%
  latency p50 0.0 ms, p95 0.1 ms
  saved local-candidate.json
## holdline gate: **PASS**

Compared **4** paired cases (`abcdef1` vs `local-check`). Pass-rate change **+0.0 pts** (95% CI +0.0 to +0.0); 0 broke, 0 fixed, McNemar p = 1.0000.

| Metric | Baseline | Candidate | Change |
|---|---:|---:|---:|
| pass rate | 100.0% | 100.0% | +0.0 pts |
| pass^1 | n/a | 100.0% | n/a |
| held back when it should | 100.0% | 100.0% | +0.0 pts |
| answered when it should | 100.0% | 100.0% | +0.0 pts |
| p95 latency ms | 0.1 | 0.1 | +0 |
| check: answer | 100.0% | 100.0% | +0.0 pts |
| check: max_tool_calls | 100.0% | 100.0% | +0.0 pts |
| check: outcome | 100.0% | 100.0% | +0.0 pts |
| check: ran | 100.0% | 100.0% | +0.0 pts |
| check: tool_args | 100.0% | 100.0% | +0.0 pts |
| check: tool_order | 100.0% | 100.0% | +0.0 pts |
| check: tools_forbidden | 100.0% | 100.0% | +0.0 pts |
| check: tools_required | 100.0% | 100.0% | +0.0 pts |
```

Print the summary of a saved run without gating:

```bash
holdline show .holdline/baseline.json
```

```text
abcdef1 on refund_cases: 4 cases x 3 = 12 runs
  pass rate   100.0%  (95% CI 100.0% to 100.0%)
  pass^3      100.0%
  held back when it should   100.0%
  answered when it should    100.0%
  latency p50 0.0 ms, p95 0.1 ms
```

## Other CI systems

The gate is a command, so it is not tied to GitHub. In GitLab CI, Jenkins, CircleCI or any other system that can run Python, install holdline with `pip install holdline` and run the commands from [Running the gate locally](#running-the-gate-locally). The job fails when `holdline gate` or `holdline compare` exits with code 1, so no extra step is needed to block a merge. Exit code 2 means bad input, such as a missing file, and also fails the job.

```bash
holdline compare results/main.csv results/pr.csv --max-drop 0.10 > /dev/null
echo "exit code: $?"
```

```text
exit code: 1
```

The verdict is printed as Markdown on stdout. Pass `--markdown FILE` and `--html FILE` and publish those files as build artifacts in your system. The job summary is written only when `GITHUB_STEP_SUMMARY` is set, which GitHub provides, so elsewhere these files are how you read a failure.

## Gotchas

**Renaming a case id drops it from the comparison.** Cases are paired by id. A renamed case shows up as one case only in the baseline and one only in the candidate, and neither is compared.

```bash
sed 's/^q5,/q5-renamed,/' results/pr.csv > results/pr-renamed.csv
holdline compare results/main.csv results/pr-renamed.csv --max-drop 0.10
```

```text
## holdline gate: **PASS**

Compared **5** paired cases (`main` vs `pr-renamed`). Pass-rate change **+0.0 pts** (95% CI +0.0 to +0.0); 0 broke, 0 fixed, McNemar p = 1.0000.

- :warning: suites differ: 1 cases only in baseline, 1 only in candidate; compared the 5 shared

| Metric | Baseline | Candidate | Change |
|---|---:|---:|---:|
| pass rate | 100.0% | 83.3% | -16.7 pts |
| pass^1 | 100.0% | 83.3% | -16.7 pts |
| held back when it should | n/a | n/a | n/a |
| answered when it should | n/a | n/a | n/a |
| check: imported:passed | 100.0% | 83.3% | -16.7 pts |
```

Keep ids stable. When you retire a case, delete it and refresh the baseline.

**The gate can pass with no shared cases.** If the two files share no ids, `paired_cases` is 0, the paired checks have nothing to compare, and the gate passes unless an absolute rule fails. Watch for the `suites differ` warning and set `--min-pass-rate`.

```bash
printf 'case_id,passed\nx,1\n' > results/only-x.csv
printf 'case_id,passed\ny,1\n' > results/only-y.csv
holdline compare results/only-x.csv results/only-y.csv
```

```text
## holdline gate: **PASS**

Compared **0** paired cases (`only-x` vs `only-y`). Pass-rate change **+0.0 pts** (95% CI +0.0 to +0.0); 0 broke, 0 fixed, McNemar p = 1.0000.

- :warning: suites differ: 1 cases only in baseline, 1 only in candidate; compared the 0 shared

| Metric | Baseline | Candidate | Change |
|---|---:|---:|---:|
| pass rate | 100.0% | 100.0% | +0.0 pts |
| pass^1 | 100.0% | 100.0% | +0.0 pts |
| held back when it should | n/a | n/a | n/a |
| answered when it should | n/a | n/a | n/a |
| check: imported:passed | 100.0% | 100.0% | +0.0 pts |
```

**A non-significant drop only warns.** Two broken cases and no fixes give p = 0.5. The gate passes unless `max_drop` or another rule fails.

**Errors fail the run.** An exception in the agent is recorded on that run and fails it. The summary shows `runs with errors: N`, and the gate warns when the count rises above the baseline's.

**Scores need the right threshold.** The default is 0.5, so a score of 0.79 passes by default and fails at `--threshold 0.8`. The row `check: imported:<column>` in the metrics table shows what holdline counted as passing.

## Troubleshooting

**The id column is not found.** No column matched a recognised id name. Pass it with `--id-col`. The name `test` alone is not recognised.

```bash
printf 'test,passed\na,1\n' > results/test-col.csv
holdline compare results/test-col.csv results/test-col.csv
```

```text
error: could not find the id column among ['test', 'passed']; pass it with --id-col
```

**A column name does not match.** Names are case-sensitive and must exist in the header.

```bash
holdline compare results/main.csv results/pr.csv --id-col nope
```

```text
error: column 'nope' not found; columns are ['case_id', 'passed']
```

**The pass column is not found.** The file has neither a pass column nor a score column with a recognised name. Pass `--pass-col`.

```bash
printf 'case_id,result\na,1\n' > results/no-pass.csv
holdline compare results/no-pass.csv results/no-pass.csv
```

```text
error: could not find the pass column among ['case_id', 'result']; pass it with --pass-col
```

**A pass value cannot be read.** A value is neither a recognised word nor a number.

```bash
printf 'case_id,passed\na,maybe\n' > results/maybe.csv
holdline compare results/maybe.csv results/maybe.csv
```

```text
error: cannot read 'maybe' as pass or fail
```

**The baseline file is missing.** Run the suite and commit the output as in step 3 of Workflow A.

```bash
holdline gate --candidate cand.json --baseline .holdline/missing.json
```

```text
error: [Errno 2] No such file or directory: '.holdline/missing.json'
```

**A config key is wrong.** Use the keys in the [config table](#gate-config-file). The key is `max_drop`.

```bash
echo '{"max_drop_pct": 0.1}' > bad-gate.json
holdline gate --candidate cand.json --config bad-gate.json
```

```text
error: unknown gate options ['max_drop_pct']; known: ['alpha', 'enforce_must_pass', 'max_cost_increase', 'max_drop', 'max_latency_increase', 'min_pass_rate', 'min_withheld']
```

**A case uses an unknown `expected` key.** The message lists the valid keys.

```bash
echo '{"id": "x", "input": "hi", "expected": {"bogus": 1}}' > sandbox/bad-case.jsonl
holdline run --suite sandbox/bad-case.jsonl --target sandbox/flaky_agent.py:steady
```

```text
error: case 0 (x): unknown expected keys ['bogus']; known: ['answer', 'answer_match', 'checks', 'max_steps', 'max_tool_calls', 'no_loops', 'outcome', 'rubric', 'tool_args', 'tool_order', 'tools_forbidden', 'tools_required']
```

**The gate exits 0 but a case broke.** One regression is not significant on a small suite. Set `--max-drop`, or mark the case `must_pass`.

**The Action fails but the log shows no reason.** The Action hides the gate output. Read the job summary, or download `holdline-gate.md` and `holdline-report.html` from the uploaded artifact.