# Decisions

Every design decision in holdline, with the options considered and why this one won. Newest
decisions are added at the bottom of their section, the same day they are made.

## Scope and packaging

| # | Date | Decision | Options considered | Why | Consequence |
|---|---|---|---|---|---|
| D1 | 2026-10-21 | Build an eval **and regression-gate** toolkit, not another tracing dashboard | Hosted dashboard; prompt-testing CLI; gate-first library | The gap in most teams is not seeing traces, it is deciding whether a change is safe to merge. A gate that runs in CI forces that decision on every pull request | Everything bends toward one output: a PASS/FAIL with reasons and an exit code |
| D2 | 2026-10-21 | **Zero runtime dependencies** (standard library only) | pydantic, numpy/scipy, rich, click | An eval tool is installed into someone else's agent environment. Every dependency is a version conflict waiting to happen. The statistics needed (binomial, bootstrap, kappa) are short enough to write and test exactly | ~300 lines of statistics written and unit-tested by hand; YAML is an optional extra |
| D3 | 2026-10-21 | Python 3.9+, and importable on 3.8 | 3.10+ only (newer typing syntax) | Many production agent stacks still run older Pythons; the first dogfood target ran 3.8 | No runtime-subscripted generics; `from __future__ import annotations` everywhere |
| D4 | 2026-10-21 | A target is **any callable `fn(input) -> output`**, sync or async | Framework adapters (LangChain, OpenAI Agents SDK, etc.) as the core API | Frameworks change monthly; a function signature does not. Adapters can be thin wrappers later | Works with any agent; the user decides how to call it |
| D5 | 2026-10-21 | Name `holdline` | Other names checked | Free on PyPI and GitHub; says what it does (hold the line on quality) | |
| D6 | 2026-10-21 | Repo private until v0.1 release, then public | Public from day one | Ship it working, with real dogfood numbers, before anyone sees it | |

## Recording what the agent did

| # | Date | Decision | Options considered | Why | Consequence |
|---|---|---|---|---|---|
| D7 | 2026-10-21 | Bind the current trace with **`contextvars`**; `holdline.step()` and `@holdline.tool` write to it | A global list; passing a trace object through the agent; monkey-patching SDKs | Thread-safe and async-safe, needs no change to the agent's function signatures, and is a no-op outside a run, so instrumentation can stay in production code | Threads the agent spawns itself do not inherit the context (documented) |
| D8 | 2026-10-21 | Steps have a small fixed vocabulary of kinds: `tool`, `llm`, `decision`, `error`, `other` | Free-form event names | Checks need to find tool calls and decisions without knowing the agent | Unknown kinds become `other` rather than failing |
| D9 | 2026-10-21 | Traces are JSONL, with an **OpenTelemetry (OTLP/JSON) export** using the GenAI attribute names | OTel SDK as a dependency; a custom format only | Plain files diff in git and need no server; OTLP lets teams push the same traces into the observability stack they already run, without holdline depending on the SDK | `to_otel()` builds the JSON document by hand |

## What counts as passing

| # | Date | Decision | Options considered | Why | Consequence |
|---|---|---|---|---|---|
| D10 | 2026-10-21 | **Outcome is first-class**: every run ends in `answer`, `abstain` or `escalate` | Treat a refusal as just another answer string | Knowing when not to act is the reliability property that matters most for agents in production. It needs its own metrics: held back when it should, answered when it should | Reported separately, with an optional floor in the gate |
| D11 | 2026-10-21 | **Check the trajectory, not only the answer**: required, forbidden and ordered tools, step and tool-call budgets, loop detection, tool arguments against JSON Schema | Final-answer checks only | An agent can reach the right answer the wrong way (skip the policy check, call a forbidden tool). Final-answer evals pass it | The toy example's v2 gives the right answer on one case and still fails on `tool_order` |
| D12 | 2026-10-21 | Answer matching defaults to **`contains`** after normalisation | `exact` default | Agents answer in sentences; exact match fails correct answers | `exact`, `regex`, `numeric`, `f1` are one key away |
| D13 | 2026-10-21 | A case **passes only if every check passes**; a check returns bool, score, `(bool, detail)` or a dict | Weighted scores | A gate needs a binary verdict per case, and a failing check must say why | Scores are kept for reporting |
| D14 | 2026-10-21 | **Errors are results**: an exception in the target, a check or the judge fails that run and the suite continues | Stop on first error | One flaky tool must not hide the other 99 cases | A `ran` check is always present |
| D15 | 2026-10-21 | Timeouts are **soft**: a run slower than the limit is marked failed but not interrupted | Killing threads; process pool | Python cannot safely kill threads; processes would break shared clients and add pickling constraints | Documented limitation |

## Reliability and statistics

| # | Date | Decision | Options considered | Why | Consequence |
|---|---|---|---|---|---|
| D16 | 2026-10-21 | **Run each case k times** and report **pass^k** with the unbiased estimator C(c,k)/C(n,k) | One run per case; pass@k only | Agents are non-deterministic. pass@k (any run passes) flatters; pass^k (all runs pass) is what an unattended agent needs | Cost scales with k; k=3 is the usual setting |
| D17 | 2026-10-21 | Pass-rate interval by **bootstrapping over cases** (per-case pass fractions) | Wilson interval over all runs | Repeats of one case are correlated; treating 3 repeats of 68 cases as 204 independent trials gives falsely narrow intervals | Wilson is kept for single-run proportions |
| D18 | 2026-10-21 | The gate compares runs **paired by case id** | Compare two pass rates (two-proportion test) | The question is "did the same cases get worse". Pairing removes case difficulty from the comparison and is far more sensitive | Suites must share ids; differences are warned |
| D19 | 2026-10-21 | Significance by the **exact McNemar test** on discordant cases | Chi-square McNemar; z-test | Exact is correct at the small counts eval suites have; only cases that flipped carry information | 4 broke and 0 fixed is p = 0.125: not significant |
| D20 | 2026-10-21 | For the gate, a case "passes" when **all its repeats pass** | Majority of repeats | Matches pass^k: a case that fails one run in three is not reliable | Flakiness counts against the candidate |
| D21 | 2026-10-21 | **Practical rules alongside the test**: must-pass cases, maximum drop, minimum pass rate, abstention floor, latency and cost budgets | Significance only | Small suites cannot reach significance; some cases (safety, policy) must never fail regardless of statistics | Gate fails on any rule; warnings for non-significant regressions |
| D22 | 2026-10-21 | All resampling is **seeded** | Random seeds | The same run must produce the same report and the same verdict | |

## The LLM judge

| # | Date | Decision | Options considered | Why | Consequence |
|---|---|---|---|---|---|
| D23 | 2026-10-21 | A judge is **a user-supplied callable**; `llm_judge(call_model)` wraps any `prompt -> text` function | Bundle provider SDKs | Keeps D2 (no dependencies) and works with any model or gateway | An unparseable reply counts as FAIL, with the reply kept as the reason |
| D24 | 2026-10-21 | **Measure the judge against human labels before it may gate** (`holdline calibrate`) | Trust the judge; report raw agreement | A judge is a model with its own errors. Raw agreement looks high when most items pass; Cohen's kappa corrects for chance | Fit to gate needs: n >= 30, kappa lower bound >= 0.6, false-pass rate <= 10%, no sign reversal |
| D25 | 2026-10-21 | The headline judge error is the **false-pass rate** (judge PASS, human FAIL) | Symmetric error | In a release gate, a false pass lets a regression ship; a false fail only costs a re-check | Shown as the outlined cell in the confusion matrix |
| D26 | 2026-10-21 | **Check bias per group and flag sign reversal** | Overall bias only | An average can hide a judge that is lenient on one kind of case and harsh on another; no single threshold fixes that | In the synthetic example overall bias is +0.01 while groups are +0.17 and -0.10 |
| D27 | 2026-10-21 | Tune a score threshold on **one half of the labels and report it on the other** | Tune and report on the same labels | Reporting on the tuning set overstates agreement | Both numbers are shown; the held-out one is "the number to trust" |

## Interfaces

| # | Date | Decision | Options considered | Why | Consequence |
|---|---|---|---|---|---|
| D28 | 2026-10-21 | Plain **JSON/JSONL** for suites, runs and labels | SQLite; a server | Diffable in git, reviewable in a pull request, no infrastructure | A run file holds its suite snapshot, so it can be re-gated later |
| D29 | 2026-10-21 | CLI with `run`, `gate`, `calibrate`, `report`, `show`; exit 1 on gate failure, 2 on bad input | A Python API only | CI speaks exit codes | `argparse`, no extra dependency |
| D30 | 2026-10-21 | **Composite GitHub Action**, writes the Markdown verdict to the job summary | Docker action | Runs on the runner's own Python in seconds; no image to build or pull | CI includes a job that runs the action itself on both example agents |
| D31 | 2026-10-21 | **One self-contained HTML file** per report: inline CSS and a little JS, no network requests, light theme | A web app; a CDN chart library | Opens anywhere: a CI artifact, an email attachment, an air-gapped laptop | Charts are hand-built from HTML elements |
| D32 | 2026-10-21 | Report shows repeats that ended the same way **once** | One block per run | 3 identical failures is one fact, not three | Groups by (passed, failed checks, tool path) |
| D33 | 2026-10-21 | Colours: status colours only for state and always with an icon and a word; trace kinds use three categorical colours validated for colour-vision deficiency | Free choice | Readable for everyone and in print | Aqua is below 3:1 contrast, so every kind badge carries its name |

## Dogfood

| # | Date | Decision | Options considered | Why | Consequence |
|---|---|---|---|---|---|
| D34 | 2026-10-21 | First real target: **helpdesk-agent**, over its 68 labelled tickets, with its own correctness rule (exact match or F1 >= 0.5) | Write new checks for it | Keeps the numbers comparable with that project's evaluation and tests holdline on someone else's conventions | The adapter is in `examples/helpdesk/`; helpdesk-agent's code is not modified |
| D35 | 2026-10-21 | Uncovered tickets are **must-pass escalations** | Ordinary cases | A wrong reply to a question the help centre does not cover is the failure that product exists to prevent | One such failure fails the gate |
| D36 | 2026-10-21 | A model outage **raises** in the adapter | Treat it as an escalation | An outage that looks like a correct escalation would inflate the abstention numbers | Outages show as errors, never as passes |
