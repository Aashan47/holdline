"""Command line: ``holdline run | gate | calibrate | report | show``.

Exit codes: 0 ok, 1 gate failed (or judge not fit with ``--strict``), 2 usage or input error.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import sys
from typing import Callable, Optional

from . import judge as judge_mod
from . import report, suite
from .gate import GateConfig, gate
from .runner import Run, run


def _load_callable(spec: str) -> Callable:
    """'package.module:function' (or 'path/to/file.py:function')."""
    if ":" not in spec:
        raise SystemExit(f"error: expected 'module:function', got {spec!r}")
    mod, attr = spec.rsplit(":", 1)
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())
    if mod.endswith(".py"):
        s = importlib.util.spec_from_file_location(os.path.splitext(os.path.basename(mod))[0], mod)
        m = importlib.util.module_from_spec(s)
        s.loader.exec_module(m)
    else:
        m = importlib.import_module(mod)
    obj = m
    for part in attr.split("."):
        obj = getattr(obj, part)
    return obj


def _write(path: Optional[str], text: str) -> None:
    if path:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)


def _step_summary(md: str) -> None:
    """Append to the GitHub Actions job summary when running in Actions."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(md + "\n")


def cmd_run(a) -> int:
    s = suite.load(a.suite)
    if a.tags:
        s = s.filter(tags=a.tags.split(","))
    target = _load_callable(a.target)
    j = _load_callable(a.judge) if a.judge else None

    done = [0]
    total = len(s) * a.repeats

    def progress(_):
        done[0] += 1
        if not a.quiet and sys.stderr.isatty():
            print(f"\r  {done[0]}/{total}", end="", file=sys.stderr, flush=True)

    r = run(target, s, repeats=a.repeats, workers=a.workers, judge=j, timeout=a.timeout,
            label=a.label, progress=progress)
    if not a.quiet and sys.stderr.isatty():
        print(file=sys.stderr)
    out = a.out or os.path.join("holdline-runs", f"{r.meta['label']}.json")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    r.save(out)
    print(report.text_summary(r))
    print(f"  saved {out}")
    if a.html:
        _write(a.html, report.run_html(r))
        print(f"  report {a.html}")
    return 0


def _gate_config(a) -> GateConfig:
    cfg = {}
    if a.config:
        with open(a.config, encoding="utf-8") as fh:
            cfg = json.load(fh)
    for key in ("alpha", "max_drop", "min_pass_rate", "min_withheld", "max_latency_increase",
                "max_cost_increase"):
        v = getattr(a, key)
        if v is not None:
            cfg[key] = v
    return GateConfig.from_dict(cfg)


def cmd_gate(a) -> int:
    cand = Run.load(a.candidate)
    base = Run.load(a.baseline) if a.baseline else None
    res = gate(cand, base, _gate_config(a))
    md = report.gate_markdown(res, cand, base)
    if a.json:
        print(json.dumps(res.to_dict(), indent=1))
    else:
        print(md)
    _write(a.markdown, md)
    _write(a.html, report.run_html(cand, res, base) if a.html else "")
    _step_summary(md)
    return 0 if res.passed else 1


def cmd_calibrate(a) -> int:
    items = judge_mod.load_labels(a.labels)
    rep = judge_mod.calibrate(items, min_kappa=a.min_kappa, max_false_pass=a.max_false_pass,
                              min_n=a.min_n)
    print(json.dumps(rep, indent=1) if a.json else report.calibration_text(rep))
    _write(a.out, json.dumps(rep, indent=1))
    return 1 if a.strict and not rep["fit_to_gate"] else 0


def cmd_report(a) -> int:
    r = Run.load(a.run)
    base = Run.load(a.baseline) if a.baseline else None
    res = gate(r, base) if base else None
    _write(a.html, report.run_html(r, res, base))
    print(f"wrote {a.html}")
    return 0


def cmd_show(a) -> int:
    print(report.text_summary(Run.load(a.run)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="holdline", description="Eval and regression gate for agents.")
    from . import __version__
    p.add_argument("--version", action="version", version=f"holdline {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run a target over a suite")
    r.add_argument("--suite", required=True, help="cases file (.json, .jsonl, .yaml)")
    r.add_argument("--target", required=True, help="module:function taking the case input")
    r.add_argument("--repeats", "-k", type=int, default=1)
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--judge", help="module:function judge(case, trace) for rubric cases")
    r.add_argument("--timeout", type=float, help="seconds; slower runs are marked failed")
    r.add_argument("--tags", help="comma-separated: only cases with any of these tags")
    r.add_argument("--label", help="name for this run (default: the target's name)")
    r.add_argument("--out", help="where to save the run JSON")
    r.add_argument("--html", help="also write an HTML report here")
    r.add_argument("--quiet", "-q", action="store_true")
    r.set_defaults(fn=cmd_run)

    g = sub.add_parser("gate", help="fail if the candidate is measurably worse")
    g.add_argument("--candidate", required=True)
    g.add_argument("--baseline")
    g.add_argument("--config", help="JSON file of gate options")
    g.add_argument("--alpha", type=float)
    g.add_argument("--max-drop", dest="max_drop", type=float)
    g.add_argument("--min-pass-rate", dest="min_pass_rate", type=float)
    g.add_argument("--min-withheld", dest="min_withheld", type=float)
    g.add_argument("--max-latency-increase", dest="max_latency_increase", type=float)
    g.add_argument("--max-cost-increase", dest="max_cost_increase", type=float)
    g.add_argument("--markdown", help="write the Markdown summary here")
    g.add_argument("--html", help="write an HTML report here")
    g.add_argument("--json", action="store_true")
    g.set_defaults(fn=cmd_gate)

    c = sub.add_parser("calibrate", help="measure an LLM judge against human labels")
    c.add_argument("--labels", required=True, help="JSONL of {id, human, judge, group?, judge_score?}")
    c.add_argument("--min-kappa", dest="min_kappa", type=float, default=0.6)
    c.add_argument("--max-false-pass", dest="max_false_pass", type=float, default=0.10)
    c.add_argument("--min-n", dest="min_n", type=int, default=30)
    c.add_argument("--strict", action="store_true", help="exit 1 if the judge is not fit")
    c.add_argument("--out", help="write the report JSON here")
    c.add_argument("--json", action="store_true")
    c.set_defaults(fn=cmd_calibrate)

    rp = sub.add_parser("report", help="write an HTML report for a saved run")
    rp.add_argument("run")
    rp.add_argument("--baseline")
    rp.add_argument("--html", default="holdline-report.html")
    rp.set_defaults(fn=cmd_report)

    sh = sub.add_parser("show", help="print a saved run's summary")
    sh.add_argument("run")
    sh.set_defaults(fn=cmd_show)
    return p


def main(argv: Optional[list] = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return a.fn(a)
    except (suite.SuiteError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
