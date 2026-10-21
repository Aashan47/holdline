"""The release gate: is the candidate measurably worse than the baseline?

Cases are paired by id, so the comparison asks "did the same cases get worse", which is far more
sensitive than comparing two pass rates. A case counts as passing when all of its repeats passed
(the pass^k view). The gate fails on any of:

- a significant regression: more cases flipped pass->fail than fail->pass, exact McNemar p < alpha;
- a drop in pass rate larger than ``max_drop`` (practical tolerance, even if not significant);
- any must-pass case failing on the candidate;
- candidate pass rate below ``min_pass_rate``;
- candidate holding back on fewer should-not-answer cases than ``min_withheld``;
- latency or cost growing more than the allowed ratio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import stats
from .runner import Run


@dataclass
class GateConfig:
    alpha: float = 0.05
    max_drop: Optional[float] = None
    min_pass_rate: Optional[float] = None
    min_withheld: Optional[float] = None
    max_latency_increase: Optional[float] = None   # e.g. 0.2 = p95 may grow 20%
    max_cost_increase: Optional[float] = None
    enforce_must_pass: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "GateConfig":
        known = cls.__dataclass_fields__
        unknown = set(d) - set(known)
        if unknown:
            raise ValueError(f"unknown gate options {sorted(unknown)}; known: {sorted(known)}")
        return cls(**d)


@dataclass
class GateResult:
    passed: bool
    reasons: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    metrics: list = field(default_factory=list)      # rows: name, baseline, candidate, delta
    regressions: list = field(default_factory=list)  # case ids pass -> fail
    fixes: list = field(default_factory=list)        # case ids fail -> pass
    delta: Optional[dict] = None                     # paired pass-rate change with interval
    mcnemar_p: Optional[float] = None
    paired_cases: int = 0

    @property
    def verdict(self) -> str:
        return "PASS" if self.passed else "FAIL"

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "reasons": self.reasons, "warnings": self.warnings,
                "metrics": self.metrics, "regressions": self.regressions, "fixes": self.fixes,
                "delta": self.delta, "mcnemar_p": self.mcnemar_p,
                "paired_cases": self.paired_cases}


def _all_passed(run: Run) -> dict:
    return {cid: bool(rs) and all(r.passed for r in rs) for cid, rs in run.by_case().items()}


def gate(candidate: Run, baseline: Optional[Run] = None,
         config: Optional[GateConfig] = None) -> GateResult:
    cfg = config or GateConfig()
    cs = candidate.summary
    res = GateResult(passed=True)

    if cfg.enforce_must_pass and cs["must_pass_failed"]:
        res.reasons.append(f"must-pass cases failed: {', '.join(cs['must_pass_failed'])}")
    if cfg.min_pass_rate is not None and cs["pass_rate"] < cfg.min_pass_rate:
        res.reasons.append(f"pass rate {cs['pass_rate']:.3f} < required {cfg.min_pass_rate}")
    if cfg.min_withheld is not None and cs["withheld_when_should"] is not None \
            and cs["withheld_when_should"] < cfg.min_withheld:
        res.reasons.append(f"held back on {cs['withheld_when_should']:.3f} of should-not-answer "
                           f"cases < required {cfg.min_withheld}")

    if baseline is not None:
        bs = baseline.summary
        b_all, c_all = _all_passed(baseline), _all_passed(candidate)
        b_frac, c_frac = baseline.case_pass_fraction(), candidate.case_pass_fraction()
        common = [cid for cid in c_all if cid in b_all]
        only_b = sorted(set(b_all) - set(c_all))
        only_c = sorted(set(c_all) - set(b_all))
        if only_b or only_c:
            res.warnings.append(f"suites differ: {len(only_b)} cases only in baseline, "
                                f"{len(only_c)} only in candidate; compared the {len(common)} shared")
        res.paired_cases = len(common)
        res.regressions = [cid for cid in common if b_all[cid] and not c_all[cid]]
        res.fixes = [cid for cid in common if not b_all[cid] and c_all[cid]]
        res.mcnemar_p = round(stats.mcnemar_exact(len(res.regressions), len(res.fixes)), 6)
        est, lo, hi = stats.bootstrap_mean_diff([(b_frac[c], c_frac[c]) for c in common])
        res.delta = {"estimate": round(est, 4), "ci": [round(lo, 4), round(hi, 4)]}

        if len(res.regressions) > len(res.fixes) and res.mcnemar_p < cfg.alpha:
            res.reasons.append(f"significant regression: {len(res.regressions)} cases broke, "
                               f"{len(res.fixes)} fixed (McNemar p={res.mcnemar_p:.4f} < {cfg.alpha})")
        elif res.regressions:
            res.warnings.append(f"{len(res.regressions)} cases broke and {len(res.fixes)} fixed; "
                                f"not significant (p={res.mcnemar_p:.4f})")
        if cfg.max_drop is not None and est < -cfg.max_drop:
            res.reasons.append(f"pass rate dropped {-est:.3f} > allowed {cfg.max_drop} "
                               f"(95% CI {lo:+.3f} to {hi:+.3f})")

        def ratio_check(name, b, c, limit):
            if limit is not None and b and c > b * (1 + limit):
                res.reasons.append(f"{name} grew {c / b - 1:.0%} > allowed {limit:.0%}")

        ratio_check("p95 latency", bs["latency_ms"]["p95"], cs["latency_ms"]["p95"],
                    cfg.max_latency_increase)
        ratio_check("cost", bs["cost"], cs["cost"], cfg.max_cost_increase)

        if cs["errors"] > bs["errors"]:
            res.warnings.append(f"runs with errors rose from {bs['errors']} to {cs['errors']}")
        new_flaky = sorted(set(cs["flaky_cases"]) - set(bs["flaky_cases"]))
        if new_flaky:
            res.warnings.append(f"newly flaky cases: {', '.join(new_flaky)}")

        k = cs["repeats"]
        rows = [("pass rate", bs["pass_rate"], cs["pass_rate"]),
                (f"pass^{k}", bs.get(f"pass^{k}"), cs.get(f"pass^{k}")),
                ("held back when it should", bs["withheld_when_should"], cs["withheld_when_should"]),
                ("answered when it should", bs["answered_when_should"], cs["answered_when_should"])]
        for name, b, c in (("p95 latency ms", bs["latency_ms"]["p95"], cs["latency_ms"]["p95"]),
                           ("cost", bs["cost"], cs["cost"])):
            if b or c:
                rows.append((name, b, c))
        for name in sorted(set(bs["checks"]) | set(cs["checks"])):
            rows.append((f"check: {name}", bs["checks"].get(name), cs["checks"].get(name)))
        res.metrics = [{"metric": n, "baseline": b, "candidate": c,
                        "delta": None if b is None or c is None else round(c - b, 4)}
                       for n, b, c in rows]
    else:
        k = cs["repeats"]
        res.metrics = [{"metric": "pass rate", "candidate": cs["pass_rate"]},
                       {"metric": f"pass^{k}", "candidate": cs.get(f"pass^{k}")},
                       {"metric": "held back when it should", "candidate": cs["withheld_when_should"]}]

    res.passed = not res.reasons
    return res
