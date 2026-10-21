"""Checks: given a case and the trace of one run, what passed and what did not.

Built-in checks are driven by keys in ``case.expected``. Custom checks are plain functions
registered with ``@holdline.check("name")`` (or referenced as ``"module:function"``) and listed in
``expected.checks``. A check returns a bool, a score in [0, 1], ``(bool, detail)`` or a
:class:`CheckResult`.
"""

from __future__ import annotations

import importlib
import json
import re
import string
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .suite import OUTCOMES, Case
from .trace import Trace

PASS_SCORE = 0.5  # a float score passes at or above this unless the check says otherwise


@dataclass
class CheckResult:
    check: str
    passed: bool
    score: float = 1.0
    detail: str = ""

    def to_dict(self) -> dict:
        d = {"check": self.check, "passed": self.passed, "score": round(self.score, 4)}
        if self.detail:
            d["detail"] = self.detail
        return d


_REGISTRY: dict = {}


def check(name: Optional[str] = None):
    """Register a custom check: ``@holdline.check("cites_source")`` on ``fn(case, trace)``."""

    def wrap(fn: Callable) -> Callable:
        _REGISTRY[name or fn.__name__] = fn
        return fn

    return wrap


def _resolve(name: str) -> Callable:
    if name in _REGISTRY:
        return _REGISTRY[name]
    if ":" in name:
        mod, attr = name.split(":", 1)
        return getattr(importlib.import_module(mod), attr)
    raise KeyError(f"unknown check {name!r}; register it with @holdline.check or use 'module:fn'")


def _coerce(name: str, value: Any) -> CheckResult:
    if isinstance(value, CheckResult):
        return value
    if isinstance(value, tuple) and len(value) == 2:
        ok, detail = value
        return CheckResult(name, bool(ok), 1.0 if ok else 0.0, str(detail))
    if isinstance(value, bool):
        return CheckResult(name, value, 1.0 if value else 0.0)
    if isinstance(value, (int, float)):
        return CheckResult(name, float(value) >= PASS_SCORE, float(value))
    if isinstance(value, dict):
        ok = bool(value.get("pass", value.get("passed")))
        score = float(value.get("score", 1.0 if ok else 0.0))
        return CheckResult(name, ok, score, str(value.get("reason", value.get("detail", ""))))
    raise TypeError(f"check {name!r} returned {type(value).__name__}; expected bool, float, "
                    "(bool, detail), dict or CheckResult")


# -- reading the agent's output -----------------------------------------------------------
def answer_text(output: Any) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        for key in ("answer", "text", "output", "response", "content"):
            if isinstance(output.get(key), str):
                return output[key]
    return json.dumps(output, ensure_ascii=False, default=str)


def outcome_of(trace: Trace) -> str:
    """answer | abstain | escalate. Read from ``output["outcome"]``, else the last decision step
    named after an outcome, else 'abstain' for an empty output and 'answer' otherwise."""
    out = trace.output
    if isinstance(out, dict) and out.get("outcome") in OUTCOMES:
        return out["outcome"]
    for s in reversed(trace.steps):
        if s.kind == "decision" and s.name in OUTCOMES:
            return s.name
    return "abstain" if not answer_text(out).strip() else "answer"


# -- answer matching ----------------------------------------------------------------------
_PUNCT = str.maketrans("", "", string.punctuation)


def normalize(s: str) -> str:
    return " ".join(s.lower().translate(_PUNCT).split())


def token_f1(pred: str, gold: str) -> float:
    p, g = normalize(pred).split(), normalize(gold).split()
    if not p or not g:
        return float(p == g)
    common = sum((Counter(p) & Counter(g)).values())
    if common == 0:
        return 0.0
    prec, rec = common / len(p), common / len(g)
    return 2 * prec * rec / (prec + rec)


_NUM = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")


def _numbers(s: str) -> list:
    return [float(x.replace(",", "")) for x in _NUM.findall(s)]


def match_answer(pred: str, gold: Any, mode: str = "contains", threshold: float = 0.6,
                 tolerance: float = 1e-6) -> tuple:
    """Returns (passed, score, detail). ``gold`` may be a list: any one may match."""
    golds = gold if isinstance(gold, list) else [gold]
    best = (False, 0.0, "")
    for g in golds:
        g = str(g)
        if mode == "exact":
            ok = normalize(pred) == normalize(g)
            r = (ok, float(ok), "")
        elif mode == "contains":
            ok = normalize(g) in normalize(pred)
            r = (ok, float(ok), "")
        elif mode == "regex":
            ok = re.search(g, pred, re.I | re.S) is not None
            r = (ok, float(ok), "")
        elif mode == "numeric":
            target = _numbers(g)
            ok = bool(target) and any(abs(x - target[0]) <= tolerance * max(1.0, abs(target[0]))
                                      for x in _numbers(pred))
            r = (ok, float(ok), "")
        elif mode == "f1":
            f = token_f1(pred, g)
            r = (f >= threshold, f, f"f1={f:.2f}")
        else:
            raise ValueError(f"unknown answer_match mode {mode!r}")
        if r[1] > best[1] or (r[0] and not best[0]):
            best = r
    if not best[0] and not best[2]:
        best = (False, best[1], f"expected {mode} {golds[0]!r}" + (" (or others)" if len(golds) > 1 else ""))
    return best


# -- a small JSON Schema subset for tool arguments ----------------------------------------
_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
          "object": dict, "array": list, "null": type(None)}


def validate(value: Any, schema: dict, path: str = "$") -> list:
    """Validate against type, enum, const, required, properties, additionalProperties, items,
    minimum, maximum, minLength, maxLength, pattern. Returns a list of error strings."""
    errs = []
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        py = tuple(x for name in types for x in (_TYPES[name] if isinstance(_TYPES[name], tuple)
                                                 else (_TYPES[name],)))
        bad_bool = isinstance(value, bool) and bool not in py
        if not isinstance(value, py) or bad_bool:
            return [f"{path}: expected {t}, got {type(value).__name__}"]
    if "const" in schema and value != schema["const"]:
        errs.append(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: {value} > maximum {schema['maximum']}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errs.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append(f"{path}: longer than {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append(f"{path}: does not match {schema['pattern']!r}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errs.append(f"{path}: missing required {key!r}")
        for key, sub in props.items():
            if key in value:
                errs.extend(validate(value[key], sub, f"{path}.{key}"))
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    errs.append(f"{path}: unexpected property {key!r}")
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(value):
            errs.extend(validate(item, schema["items"], f"{path}[{i}]"))
    return errs


def tool_arguments(step_input: Any) -> Any:
    """The arguments of a tool step: keyword arguments for ``@tool``-recorded calls (with a lone
    positional dict treated as the arguments), otherwise the recorded input as is."""
    if isinstance(step_input, dict) and set(step_input) == {"args", "kwargs"}:
        args, kwargs = step_input["args"], step_input["kwargs"]
        if not kwargs and len(args) == 1 and isinstance(args[0], dict):
            return args[0]
        return kwargs
    return step_input


# -- the evaluator -----------------------------------------------------------------------
def evaluate(case: Case, trace: Trace, judge: Optional[Callable] = None) -> list:
    """Run every check that ``case.expected`` asks for against one trace."""
    exp = case.expected
    results = [CheckResult("ran", trace.error is None, float(trace.error is None),
                           trace.error or "")]
    tools = trace.tool_names()
    outcome = outcome_of(trace)

    if "outcome" in exp:
        ok = outcome == exp["outcome"]
        results.append(CheckResult("outcome", ok, float(ok),
                                   "" if ok else f"expected {exp['outcome']}, got {outcome}"))

    if "answer" in exp and exp.get("outcome", "answer") == "answer":
        m = exp.get("answer_match", "contains")
        opts = m if isinstance(m, dict) else {"mode": m}
        ok, score, detail = match_answer(answer_text(trace.output), exp["answer"], **opts)
        results.append(CheckResult("answer", ok, score, detail))

    if "tools_required" in exp:
        missing = [t for t in exp["tools_required"] if t not in tools]
        results.append(CheckResult("tools_required", not missing,
                                   1 - len(missing) / max(1, len(exp["tools_required"])),
                                   f"never called {missing}" if missing else ""))

    if "tools_forbidden" in exp:
        used = sorted({t for t in tools if t in exp["tools_forbidden"]})
        results.append(CheckResult("tools_forbidden", not used, float(not used),
                                   f"called forbidden {used}" if used else ""))

    if "tool_order" in exp:
        want, it = exp["tool_order"], iter(tools)
        ok = all(any(t == w for t in it) for w in want)  # subsequence test
        results.append(CheckResult("tool_order", ok, float(ok),
                                   "" if ok else f"wanted order {want}, got {tools}"))

    if "max_steps" in exp:
        n = len(trace.steps)
        ok = n <= exp["max_steps"]
        results.append(CheckResult("max_steps", ok, float(ok),
                                   "" if ok else f"{n} steps > {exp['max_steps']}"))

    if "max_tool_calls" in exp:
        n = len(tools)
        ok = n <= exp["max_tool_calls"]
        results.append(CheckResult("max_tool_calls", ok, float(ok),
                                   "" if ok else f"{n} tool calls > {exp['max_tool_calls']}"))

    if exp.get("no_loops"):
        limit = 2 if exp["no_loops"] is True else int(exp["no_loops"])
        calls = Counter((s.name, json.dumps(s.input, sort_keys=True, default=str))
                        for s in trace.tool_calls())
        loops = sorted({name for (name, _), n in calls.items() if n > limit})
        results.append(CheckResult("no_loops", not loops, float(not loops),
                                   f"identical calls repeated >{limit}x: {loops}" if loops else ""))

    if "tool_args" in exp:
        errs = []
        for s in trace.tool_calls():
            schema = exp["tool_args"].get(s.name)
            if schema is not None:
                errs += [f"{s.name}: {e}" for e in validate(tool_arguments(s.input), schema)]
        results.append(CheckResult("tool_args", not errs, float(not errs), "; ".join(errs[:5])))

    if "rubric" in exp:
        if judge is None:
            results.append(CheckResult("judge", False, 0.0, "case has a rubric but no judge was given"))
        else:
            try:
                results.append(_coerce("judge", judge(case, trace)))
            except Exception as exc:  # a judge failure is a result, not a crash
                results.append(CheckResult("judge", False, 0.0, f"judge error: {exc}"))

    for name in exp.get("checks", []):
        try:
            results.append(_coerce(name, _resolve(name)(case, trace)))
        except Exception as exc:
            results.append(CheckResult(name, False, 0.0, f"{type(exc).__name__}: {exc}"))

    return results
