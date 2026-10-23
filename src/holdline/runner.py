"""Run a target over a suite, k times per case, and summarise what happened.

A target is any callable ``fn(input) -> output`` (sync or async). Each run gets its own trace bound
to the current context, so ``holdline.step`` and ``@holdline.tool`` inside the agent record into it.
An exception from the target is recorded as the run's error and fails it; it never stops the suite.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import inspect
import json
import platform
import subprocess
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import __version__, stats
from .checks import CheckResult, evaluate, outcome_of
from .suite import Case, Suite
from .trace import Trace, bind, unbind


@dataclass
class CaseResult:
    case_id: str
    repeat: int
    passed: bool
    checks: list
    trace: Trace

    @property
    def failed_checks(self) -> list:
        return [c for c in self.checks if not c.passed]

    def to_dict(self) -> dict:
        return {"case_id": self.case_id, "repeat": self.repeat, "passed": self.passed,
                "checks": [c.to_dict() for c in self.checks], "trace": self.trace.to_dict()}

    @classmethod
    def from_dict(cls, d: dict) -> "CaseResult":
        return cls(d["case_id"], d.get("repeat", 0), d["passed"],
                   [CheckResult(**c) for c in d.get("checks", [])], Trace.from_dict(d["trace"]))


@dataclass
class Run:
    meta: dict
    cases: list              # suite snapshot: Case objects, in suite order
    results: list            # CaseResult per (case, repeat)
    _summary: Optional[dict] = field(default=None, repr=False)

    # -- views ----------------------------------------------------------------------------
    def case(self, case_id: str) -> Case:
        return next(c for c in self.cases if c.id == case_id)

    def by_case(self) -> dict:
        out = defaultdict(list)
        for r in self.results:
            out[r.case_id].append(r)
        return {c.id: sorted(out.get(c.id, []), key=lambda r: r.repeat) for c in self.cases}

    def case_pass_fraction(self) -> dict:
        return {cid: (sum(r.passed for r in rs) / len(rs) if rs else 0.0)
                for cid, rs in self.by_case().items()}

    @property
    def summary(self) -> dict:
        if self._summary is None:
            self._summary = summarise(self)
        return self._summary

    # -- persistence ----------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {"holdline": __version__, "meta": self.meta,
                "cases": [c.to_dict() for c in self.cases],
                "summary": self.summary,
                "results": [r.to_dict() for r in self.results]}

    def save(self, path: str) -> str:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=1, default=str)
        return path

    @classmethod
    def load(cls, path: str) -> "Run":
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        from .suite import from_list
        cases = from_list(d["cases"]).cases
        return cls(d["meta"], cases, [CaseResult.from_dict(r) for r in d["results"]])


def _git_sha() -> Optional[str]:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, timeout=2)
        return out.stdout.strip() or None
    except Exception:
        return None


def _call(target: Callable, value: Any) -> Any:
    if inspect.iscoroutinefunction(target):
        return asyncio.run(target(value))
    out = target(value)
    if inspect.isawaitable(out):
        async def _await():
            return await out
        return asyncio.run(_await())
    return out


def run_case(target: Callable, case: Case, repeat: int = 0, judge: Optional[Callable] = None,
             timeout: Optional[float] = None) -> CaseResult:
    """Run one case once. ``timeout`` is soft: the target is not interrupted, but a run that
    takes longer is marked failed (threads cannot be killed safely in Python)."""
    tr = Trace(case_id=case.id, repeat=repeat)
    token = bind(tr)
    t0 = time.perf_counter()
    try:
        tr.output = _call(target, case.input)
    except Exception as exc:
        tr.error = f"{type(exc).__name__}: {exc}"
    finally:
        tr.ms = (time.perf_counter() - t0) * 1000
        unbind(token)
    if timeout is not None and tr.ms > timeout * 1000 and tr.error is None:
        tr.error = f"Timeout: took {tr.ms / 1000:.2f}s > {timeout}s"
    checks = evaluate(case, tr, judge=judge)
    return CaseResult(case.id, repeat, all(c.passed for c in checks), checks, tr)


def run(target: Callable, suite: Suite, *, repeats: int = 1, workers: int = 4,
        judge: Optional[Callable] = None, timeout: Optional[float] = None,
        label: Optional[str] = None, progress: Optional[Callable] = None) -> Run:
    """Run every case ``repeats`` times on a thread pool and return a :class:`Run`."""
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    jobs = [(c, k) for k in range(repeats) for c in suite.cases]
    started = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    t0 = time.perf_counter()
    results = []

    def one(job):
        res = run_case(target, job[0], job[1], judge=judge, timeout=timeout)
        if progress:
            progress(res)
        return res

    if workers <= 1:
        results = [one(j) for j in jobs]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(one, jobs))
    meta = {"label": label or getattr(target, "__name__", "target"), "suite": suite.name,
            "suite_path": suite.path, "target": f"{getattr(target, '__module__', '?')}."
                                                f"{getattr(target, '__qualname__', repr(target))}",
            "repeats": repeats, "started": started,
            "seconds": round(time.perf_counter() - t0, 2), "git_sha": _git_sha(),
            "python": platform.python_version(), "holdline": __version__}
    return Run(meta, list(suite.cases), results)


def _pct(values: list, q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def summarise(run: Run) -> dict:
    by_case = run.by_case()
    k = run.meta.get("repeats", 1)
    fractions = run.case_pass_fraction()
    est, lo, hi = stats.bootstrap_mean(list(fractions.values())) if fractions else (0, 0, 0)
    runs_passed = sum(r.passed for r in run.results)

    pass_hat = [stats.pass_hat_k(len(rs), sum(r.passed for r in rs), k)
                for rs in by_case.values() if len(rs) >= k]
    flaky = [cid for cid, rs in by_case.items() if 0 < sum(r.passed for r in rs) < len(rs)]

    check_rates = defaultdict(lambda: [0, 0])
    for r in run.results:
        for c in r.checks:
            check_rates[c.check][0] += c.passed
            check_rates[c.check][1] += 1

    tag_rates = {}
    for case in run.cases:
        for t in case.tags:
            tag_rates.setdefault(t, []).append(fractions[case.id])

    must_fail = [c.id for c in run.cases if c.must_pass and not all(r.passed for r in by_case[c.id])]

    # Abstention: should the agent have held back, and did it?
    withhold = [c for c in run.cases if c.expected.get("outcome") in ("abstain", "escalate")]
    answerable = [c for c in run.cases if c.expected.get("outcome") == "answer"]

    def rate(cases, ok):
        rs = [r for c in cases for r in by_case[c.id]]
        return round(sum(ok(r) for r in rs) / len(rs), 4) if rs else None

    lat = [r.trace.ms for r in run.results]
    return {
        "cases": len(run.cases), "repeats": k, "runs": len(run.results),
        "pass_rate": round(est, 4), "pass_rate_ci": [round(lo, 4), round(hi, 4)],
        "runs_passed": runs_passed,
        f"pass^{k}": round(sum(pass_hat) / len(pass_hat), 4) if pass_hat else None,
        "flaky_cases": flaky,
        "must_pass_failed": must_fail,
        "errors": sum(1 for r in run.results if r.trace.error),
        "checks": {name: round(p / n, 4) for name, (p, n) in sorted(check_rates.items())},
        "tags": {t: round(sum(v) / len(v), 4) for t, v in sorted(tag_rates.items())},
        "withheld_when_should": rate(withhold, lambda r: outcome_of(r.trace) != "answer"),
        "answered_when_should": rate(answerable, lambda r: outcome_of(r.trace) == "answer"),
        "latency_ms": {"mean": round(sum(lat) / len(lat), 1) if lat else 0.0,
                       "p50": round(_pct(lat, 0.5), 1), "p95": round(_pct(lat, 0.95), 1)},
        "tokens": sum(r.trace.total_tokens for r in run.results),
        "cost": round(sum(r.trace.total_cost for r in run.results), 6),
    }
