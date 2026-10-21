# holdline: design

**Hold the line on agent quality.** holdline records what an agent did, checks it against cases
you wrote, tells you whether your LLM judge can be trusted, and fails a pull request when a change
makes the agent measurably worse.

## The problem

Agent changes are judged on vibes. A prompt tweak "looks better" on five examples, ships, and quietly
breaks the cases nobody re-ran. The tools that exist either check only the final answer (missing an
agent that got the right answer by deleting the evidence), trust an LLM judge that nobody has
compared with a human, or report a pass-rate change without saying whether it is noise.

## What holdline does

1. **Trace.** `holdline.step(...)` (or the `@holdline.tool` decorator) records every tool call, model
   call and decision an agent makes while a case runs. Traces are plain JSONL, exportable as
   OpenTelemetry spans.
2. **Check.** Each case says what must be true: the answer, the outcome (answer, abstain, escalate),
   tools that must or must not be used, step limits, loops, valid tool arguments, or a custom check.
   Checks look at the trajectory, not only the final output.
3. **Repeat.** Agents are non-deterministic, so every case can run k times. holdline reports pass rate
   with a confidence interval, **pass^k** (all k runs pass: the reliability number that matters in
   production) and flaky cases.
4. **Calibrate the judge.** Give holdline a few dozen human labels and the judge's verdicts on the same
   items. It reports agreement, Cohen's kappa with a confidence interval, whether the judge is lenient
   or harsh, and whether that bias changes sign across difficulty levels. A judge that has not passed
   calibration is flagged as not fit to gate releases.
5. **Gate.** Compare a candidate run with a baseline, case by case: an exact McNemar test on the
   paired pass/fail outcomes, a bootstrap interval on the change in pass rate, must-pass cases, and an
   abstention floor for cases the agent should refuse. The gate exits non-zero so CI fails, and writes
   a Markdown summary for the pull request.
6. **Report.** A single static HTML file (and Markdown) with every run, check, case and trace.

## Principles

- **Zero runtime dependencies.** The core is the Python standard library (3.9+). Optional extras add
  YAML suites and OpenTelemetry export. Installing holdline never fights your agent's dependencies.
- **Statistics before verdicts.** No "+3%" without the interval and the test behind it.
- **The judge is a model too.** It is measured before it is trusted.
- **Plain files.** Suites, runs, traces and labels are JSON/JSONL that diff cleanly in git.
- **Framework-agnostic.** A target is any Python callable `fn(input) -> output`. Adapters for specific
  frameworks are thin and optional.

## Data model

```
Case       id, input, expected{answer?, outcome?, tools_required?, tools_forbidden?,
           tool_order?, max_steps?, tool_args?}, tags[], difficulty?, must_pass?
Step       kind (tool | llm | decision | error), name, input, output, ms, tokens?, cost?, error?
Trace      case_id, repeat, steps[], output, error?, ms
CheckResult  check, passed, score (0..1), detail
CaseResult   case_id, repeat, passed (all checks), checks[], trace
Run        meta{suite, target, git sha, time, repeats, holdline version}, results[], summary
GateResult   verdict PASS|FAIL, reasons[], per-metric deltas with intervals and p-values
```

## Module map

| Module | Responsibility |
|---|---|
| `trace.py` | context-var recorder, `step()`, `@tool`, JSONL and OpenTelemetry export |
| `suite.py` | load and validate cases (JSON, JSONL, optional YAML) |
| `checks.py` | built-in checks + custom-check loading |
| `runner.py` | run a target over a suite with repeats and a thread pool; timeouts; errors are results |
| `stats.py` | Wilson interval, bootstrap, exact McNemar, Cohen's kappa |
| `judge.py` | judge protocol, calibration report, fitness verdict |
| `gate.py` | baseline vs candidate comparison and the configurable gate |
| `report.py` | Markdown and static HTML |
| `cli.py` | `holdline run | gate | calibrate | report` |

## Out of scope for v0.1

A hosted service, a database, a live dashboard server, framework-specific auto-instrumentation.
