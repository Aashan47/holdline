"""Reports: plain text for the terminal, Markdown for pull requests, one static HTML file."""

from __future__ import annotations

import html
import json
from typing import Optional

from .checks import outcome_of
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


# -- HTML ---------------------------------------------------------------------------------
_CSS = """
:root{--bg:#fbfbfa;--fg:#1a1a19;--muted:#6b6b66;--line:#e6e5e0;--ok:#1f7a4d;--bad:#b42318;
--warn:#a15c07;--card:#fff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}
main{max-width:1080px;margin:0 auto;padding:40px 20px 80px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}h2{font-size:18px;margin:36px 0 12px}
.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card b{display:block;font-size:22px;font-weight:600}.card span{color:var(--muted);font-size:13px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);
border-radius:10px;overflow:hidden;font-size:14px}th,td{padding:8px 12px;border-bottom:1px solid var(--line);
text-align:left;vertical-align:top}th{font-weight:600;font-size:13px;color:var(--muted)}
.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}
.pill{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;border:1px solid var(--line)}
details{margin:2px 0}summary{cursor:pointer}pre{white-space:pre-wrap;word-break:break-word;
background:#f4f4f1;padding:10px;border-radius:8px;font-size:12.5px;margin:6px 0}
.verdict{font-size:15px;font-weight:600;padding:4px 12px;border-radius:99px;color:#fff}
.verdict.PASS{background:var(--ok)}.verdict.FAIL{background:var(--bad)}
@media(max-width:640px){main{padding:24px 16px 60px}td,th{padding:6px 8px}}
"""


def _e(x) -> str:
    return html.escape("" if x is None else str(x))


def _card(value: str, label: str) -> str:
    return f'<div class="card"><b>{_e(value)}</b><span>{_e(label)}</span></div>'


def _metric_row(m: dict) -> str:
    p = _is_pct(m["metric"])
    delta = m["delta"]
    if delta is None:
        dtxt, cls = "n/a", ""
    else:
        dtxt = f"{delta * 100:+.1f} pts" if p else f"{delta:+.4g}"
        cls = "bad" if p and delta < 0 else "ok" if p and delta > 0 else ""
    return (f"<tr><td>{_e(m['metric'])}</td><td>{_e(_fmt(m['baseline'], p))}</td>"
            f"<td>{_e(_fmt(m['candidate'], p))}</td><td class='{cls}'>{_e(dtxt)}</td></tr>")


def run_html(run: Run, gate_result: Optional[GateResult] = None,
             baseline: Optional[Run] = None) -> str:
    s = run.summary
    k = s["repeats"]
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
             f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>holdline: {_e(run.meta.get('label'))}</title><style>{_CSS}</style></head><body><main>",
             f"<h1>{_e(run.meta.get('label'))} <span class='muted'>on {_e(run.meta.get('suite'))}</span></h1>",
             f"<p class='muted'>{s['cases']} cases x {k} repeats · {_e(run.meta.get('started'))}"
             f" · git {_e(run.meta.get('git_sha') or 'n/a')} · holdline {_e(run.meta.get('holdline'))}</p>"]

    if gate_result is not None:
        parts.append(f"<h2>Gate <span class='verdict {gate_result.verdict}'>{gate_result.verdict}</span></h2>")
        for r in gate_result.reasons:
            parts.append(f"<p class='bad'>{_e(r)}</p>")
        for w in gate_result.warnings:
            parts.append(f"<p class='warn'>{_e(w)}</p>")
        if baseline is not None and gate_result.metrics:
            parts.append("<table><tr><th>Metric</th><th>Baseline</th><th>Candidate</th><th>Change</th></tr>")
            for m in gate_result.metrics:
                parts.append(_metric_row(m))
            parts.append("</table>")

    ci = s["pass_rate_ci"]
    parts.append("<h2>Summary</h2><div class='grid'>")
    parts.append(_card(_fmt(s["pass_rate"], True), f"pass rate (95% CI {_fmt(ci[0], True)} to {_fmt(ci[1], True)})"))
    parts.append(_card(_fmt(s.get(f"pass^{k}"), True), f"pass^{k}: all {k} repeats pass"))
    if s["withheld_when_should"] is not None:
        parts.append(_card(_fmt(s["withheld_when_should"], True), "held back when it should"))
    if s["answered_when_should"] is not None:
        parts.append(_card(_fmt(s["answered_when_should"], True), "answered when it should"))
    parts.append(_card(str(len(s["flaky_cases"])), "flaky cases"))
    parts.append(_card(f"{s['latency_ms']['p95']:.0f} ms", "p95 latency"))
    parts.append("</div>")

    if s["checks"]:
        parts.append("<h2>Checks</h2><table><tr><th>Check</th><th>Pass rate</th></tr>")
        for name, v in s["checks"].items():
            parts.append(f"<tr><td>{_e(name)}</td><td class='{'ok' if v == 1 else 'bad' if v < 0.9 else 'warn'}'>"
                         f"{_fmt(v, True)}</td></tr>")
        parts.append("</table>")
    if s["tags"]:
        parts.append("<h2>By tag</h2><table><tr><th>Tag</th><th>Pass rate</th></tr>")
        for t, v in s["tags"].items():
            parts.append(f"<tr><td>{_e(t)}</td><td>{_fmt(v, True)}</td></tr>")
        parts.append("</table>")

    parts.append("<h2>Cases</h2><table><tr><th>Case</th><th>Passed</th><th>Outcome</th><th>Failures and traces</th></tr>")
    by_case = run.by_case()
    for case in run.cases:
        rs = by_case[case.id]
        n_ok = sum(r.passed for r in rs)
        cls = "ok" if n_ok == len(rs) else "bad" if n_ok == 0 else "warn"
        badges = "".join(f" <span class='pill'>{_e(t)}</span>" for t in case.tags)
        if case.must_pass:
            badges += " <span class='pill'>must pass</span>"
        outcomes = sorted({outcome_of(r.trace) for r in rs})
        details = []
        for r in rs:
            fails = "; ".join(f"{c.check}: {c.detail}" if c.detail else c.check for c in r.failed_checks)
            steps = "\n".join(f"{i + 1}. [{st.kind}] {st.name}  {json.dumps(st.input, default=str)[:300]}"
                              + (f"  ERROR {st.error}" if st.error else "")
                              for i, st in enumerate(r.trace.steps)) or "(no steps recorded)"
            out = json.dumps(r.trace.output, ensure_ascii=False, default=str)[:1500]
            details.append(f"<details><summary class='{'ok' if r.passed else 'bad'}'>run {r.repeat + 1}"
                           f"{': ' + _e(fails) if fails else ''}</summary>"
                           f"<pre>{_e(steps)}</pre><pre>output: {_e(out)}</pre></details>")
        parts.append(f"<tr><td><b>{_e(case.id)}</b>{badges}</td><td class='{cls}'>{n_ok}/{len(rs)}</td>"
                     f"<td>{_e(', '.join(outcomes))}</td><td>{''.join(details)}</td></tr>")
    parts.append("</table><p class='muted'>Generated by holdline.</p></main></body></html>")
    return "".join(parts)
