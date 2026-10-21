"""Bring results from any eval tool into holdline, so the gate and its statistics work on them.

Input is a table of per-case results: CSV, TSV, JSON (a list of objects, or an object holding one),
JSONL, or a holdline run file. One row per (case, run): rows that share a case id are its repeats.
Columns are found by name (``case_id``/``id``/``question``..., ``passed``/``success``/``score``...)
or given explicitly. A pass value may be a bool, 1/0, pass/fail, yes/no, or a score compared with
``threshold``.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import json
import os
from collections import defaultdict
from typing import Any, Optional

from . import __version__
from .checks import CheckResult
from .runner import CaseResult, Run
from .suite import Case
from .trace import Trace

ID_COLUMNS = ("case_id", "id", "test_id", "example_id", "item_id", "name", "question", "input", "prompt")
PASS_COLUMNS = ("passed", "pass", "success", "correct", "is_correct", "ok", "verdict")
SCORE_COLUMNS = ("score", "grade", "rating")
REPEAT_COLUMNS = ("repeat", "run", "trial", "attempt", "seed", "sample")
TAG_COLUMNS = ("tags", "tag", "group", "category", "split", "difficulty")
MUST_COLUMNS = ("must_pass", "critical", "required")
INPUT_COLUMNS = ("input", "question", "prompt", "query")

_TRUE = {"true", "t", "yes", "y", "pass", "passed", "success", "ok", "correct", "1", "1.0"}
_FALSE = {"false", "f", "no", "n", "fail", "failed", "failure", "error", "incorrect", "wrong", "0", "0.0"}


class ResultsError(ValueError):
    """Raised when a results file cannot be read as per-case results."""


def _rows(path: str) -> list:
    ext = os.path.splitext(path)[1].lower()
    with open(path, encoding="utf-8-sig") as fh:
        text = fh.read()
    if ext in (".csv", ".tsv"):
        dialect = "excel-tab" if ext == ".tsv" else "excel"
        return [dict(r) for r in csv.DictReader(io.StringIO(text), dialect=dialect)]
    if ext == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    data = json.loads(text)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # common shapes: {"results": [...]}, {"results": {"results": [...]}}, {"data": [...]}
        for key in ("results", "rows", "data", "items", "examples"):
            v = data.get(key)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                for inner in ("results", "rows", "data"):
                    if isinstance(v.get(inner), list):
                        return v[inner]
    raise ResultsError(f"{path}: expected a list of result rows")


def _find(columns: list, wanted: tuple, given: Optional[str], what: str, required: bool = True) -> Optional[str]:
    if given:
        if given not in columns:
            raise ResultsError(f"column {given!r} not found; columns are {columns}")
        return given
    lower = {c.lower(): c for c in columns}
    for w in wanted:
        if w in lower:
            return lower[w]
    if required:
        raise ResultsError(f"could not find the {what} column among {columns}; pass it with --{what}-col")
    return None


def as_pass(value: Any, threshold: float = 0.5) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) >= threshold
    s = str(value).strip().lower()
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    try:
        return float(s) >= threshold
    except ValueError:
        raise ResultsError(f"cannot read {value!r} as pass or fail") from None


def _score(raw: Any, ok: bool) -> float:
    """A numeric value in [0, 1] is kept as the score; anything else scores 1 or 0."""
    if isinstance(raw, bool):
        return float(raw)
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return float(ok)
    return v if 0.0 <= v <= 1.0 else float(ok)


def _is_holdline_run(path: str) -> bool:
    if not path.lower().endswith(".json"):
        return False
    try:
        with open(path, encoding="utf-8") as fh:
            head = json.load(fh)
        return isinstance(head, dict) and "holdline" in head and "results" in head and "cases" in head
    except (ValueError, OSError):
        return False


def load_results(path: str, *, id_col: Optional[str] = None, pass_col: Optional[str] = None,
                 repeat_col: Optional[str] = None, threshold: float = 0.5,
                 label: Optional[str] = None) -> Run:
    """Read per-case results from any tool into a :class:`Run` the gate can compare."""
    if _is_holdline_run(path):
        run = Run.load(path)
        if label:
            run.meta["label"] = label
        return run
    rows = [r for r in _rows(path) if isinstance(r, dict)]
    if not rows:
        raise ResultsError(f"{path}: no result rows")
    columns = list(dict.fromkeys(k for r in rows for k in r))
    idc = _find(columns, ID_COLUMNS, id_col, "id")
    pc = _find(columns, PASS_COLUMNS, pass_col, "pass", required=False) or \
        _find(columns, SCORE_COLUMNS, None, "pass")
    rc = _find(columns, REPEAT_COLUMNS, repeat_col, "repeat", required=False)
    tc = _find(columns, TAG_COLUMNS, None, "tags", required=False)
    mc = _find(columns, MUST_COLUMNS, None, "must", required=False)
    ic = _find(columns, INPUT_COLUMNS, None, "input", required=False)

    order, by_id = [], defaultdict(list)
    for n, r in enumerate(rows, 1):
        if r.get(idc) in (None, ""):
            raise ResultsError(f"{path}: row {n} has no {idc!r}")
        cid = str(r[idc])
        if cid not in by_id:
            order.append(cid)
        by_id[cid].append(r)

    cases, results = [], []
    for cid in order:
        rs = by_id[cid]
        if rc:
            rs = sorted(rs, key=lambda r: str(r.get(rc, "")))
        first = rs[0]
        tags = []
        if tc and first.get(tc) not in (None, ""):
            raw = first[tc]
            tags = [str(t).strip() for t in (raw if isinstance(raw, list) else str(raw).split(",")) if str(t).strip()]
        must = bool(mc and first.get(mc) not in (None, "") and as_pass(first[mc]))
        cases.append(Case(id=cid, input=first.get(ic, "") if ic else "", expected={}, tags=tags,
                          must_pass=must, meta={"imported": True}))
        for k, r in enumerate(rs):
            raw = r.get(pc)
            if raw in (None, ""):
                raise ResultsError(f"{path}: case {cid!r} has no value in {pc!r}")
            ok = as_pass(raw, threshold)
            score = _score(raw, ok)
            check = CheckResult(f"imported:{pc}", ok, score, "" if ok else f"{pc} = {raw}")
            results.append(CaseResult(cid, k, ok, [check], Trace(case_id=cid, repeat=k, output=r)))
    repeats = max(len(v) for v in by_id.values())
    meta = {"label": label or os.path.splitext(os.path.basename(path))[0],
            "suite": os.path.splitext(os.path.basename(path))[0], "suite_path": path,
            "target": f"imported from {os.path.basename(path)}", "repeats": repeats,
            "started": _dt.datetime.fromtimestamp(os.path.getmtime(path), _dt.timezone.utc).isoformat(timespec="seconds"),
            "seconds": 0, "git_sha": None, "python": None, "holdline": __version__, "imported": True,
            "columns": {"id": idc, "pass": pc, "repeat": rc, "tags": tc, "must_pass": mc}}
    return Run(meta, cases, results)
