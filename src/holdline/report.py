"""Reports: plain text for the terminal, Markdown for pull requests, one static HTML file."""

from __future__ import annotations

from typing import Optional

from .gate import GateResult
from .runner import Run


def _fmt(v, pct: bool = False) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float) and pct:
        return f"{v * 100:.1f}%"
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


_PCT = ("pass rate", "pass^", "held back", "answered", "check:")


def _is_pct(metric: str) -> bool:
    return metric.startswith(_PCT)


def text_summary(run: Run) -> str:
    s = run.summary
    k = s["repeats"]
    lines = [f"{run.meta.get('label')} on {run.meta.get('suite')}: {s['cases']} cases x {k} "
             f"= {s['runs']} runs",
             f"  pass rate   {_fmt(s['pass_rate'], True)}  (95% CI {_fmt(s['pass_rate_ci'][0], True)}"
             f" to {_fmt(s['pass_rate_ci'][1], True)})",
             f"  pass^{k}      {_fmt(s.get(f'pass^{k}'), True)}"]
    if s["withheld_when_should"] is not None:
        lines.append(f"  held back when it should   {_fmt(s['withheld_when_should'], True)}")
    if s["answered_when_should"] is not None:
        lines.append(f"  answered when it should    {_fmt(s['answered_when_should'], True)}")
    if s["flaky_cases"]:
        lines.append(f"  flaky: {', '.join(s['flaky_cases'])}")
    if s["must_pass_failed"]:
        lines.append(f"  MUST-PASS FAILED: {', '.join(s['must_pass_failed'])}")
    if s["errors"]:
        lines.append(f"  runs with errors: {s['errors']}")
    lines.append(f"  latency p50 {s['latency_ms']['p50']} ms, p95 {s['latency_ms']['p95']} ms")
    return "\n".join(lines)


def gate_markdown(result: GateResult, candidate: Run, baseline: Optional[Run] = None) -> str:
    icon = "PASS" if result.passed else "FAIL"
    out = [f"## holdline gate: **{icon}**", ""]
    if baseline is not None and result.delta:
        d = result.delta
        out.append(f"Compared **{result.paired_cases}** paired cases "
                   f"(`{baseline.meta.get('label')}` vs `{candidate.meta.get('label')}`). "
                   f"Pass-rate change **{d['estimate'] * 100:+.1f} pts** (95% CI "
                   f"{d['ci'][0] * 100:+.1f} to {d['ci'][1] * 100:+.1f}); "
                   f"{len(result.regressions)} broke, {len(result.fixes)} fixed, "
                   f"McNemar p = {result.mcnemar_p:.4f}.")
        out.append("")
    for r in result.reasons:
        out.append(f"- :x: {r}")
    for w in result.warnings:
        out.append(f"- :warning: {w}")
    if result.reasons or result.warnings:
        out.append("")
    if result.metrics:
        if baseline is not None:
            out += ["| Metric | Baseline | Candidate | Change |", "|---|---:|---:|---:|"]
            for m in result.metrics:
                p = _is_pct(m["metric"])
                delta = m["delta"]
                dtxt = "n/a" if delta is None else (f"{delta * 100:+.1f} pts" if p else f"{delta:+.4g}")
                out.append(f"| {m['metric']} | {_fmt(m['baseline'], p)} | "
                           f"{_fmt(m['candidate'], p)} | {dtxt} |")
        else:
            out += ["| Metric | Value |", "|---|---:|"]
            for m in result.metrics:
                out.append(f"| {m['metric']} | {_fmt(m['candidate'], _is_pct(m['metric']))} |")
        out.append("")
    if result.regressions:
        out.append("<details><summary>Cases that broke</summary>\n")
        by_case = candidate.by_case()
        for cid in result.regressions:
            failed = sorted({c.check for r in by_case[cid] for c in r.failed_checks})
            out.append(f"- `{cid}`: failed {', '.join(failed)}")
        out.append("\n</details>")
    return "\n".join(out).rstrip() + "\n"


def calibration_text(rep: dict) -> str:
    o = rep["overall"]
    ci = o["kappa_ci"]
    lines = [f"Judge calibration on {o['n']} labelled items: "
             f"{'FIT to gate' if rep['fit_to_gate'] else 'NOT fit to gate'}",
             f"  agreement {_fmt(o['agreement'], True)}, kappa {_fmt(o['kappa'])}"
             + (f" (95% CI {ci[0]} to {ci[1]}, {o['kappa_band']})" if ci else ""),
             f"  false-pass rate {_fmt(o['false_pass_rate'], True)} (judge PASS, human FAIL)",
             f"  false-fail rate {_fmt(o['false_fail_rate'], True)} (judge FAIL, human PASS)",
             f"  bias {o['bias']:+.3f} ({'lenient' if o['bias'] > 0 else 'harsh' if o['bias'] < 0 else 'neutral'})"]
    for g, b in rep["groups"].items():
        lines.append(f"  group {g}: n={b['n']}, agreement {_fmt(b['agreement'], True)}, "
                     f"bias {b['bias']:+.3f}")
    if "threshold" in rep:
        t = rep["threshold"]
        lines.append(f"  best score threshold {t['threshold']} (kappa {t['kappa_fit_half']} on fit "
                     f"half, {t['kappa_held_out_half']} held out)")
    for r in rep["reasons"]:
        lines.append(f"  - {r}")
    return "\n".join(lines)


# -- HTML lives in html_report; re-exported here so callers use one module -----------------
from .html_report import calibration_html, run_html  # noqa: E402,F401
