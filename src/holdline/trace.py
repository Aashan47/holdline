"""Recording what an agent did while a case runs.

The runner opens a :class:`Trace` for each case and binds it to a context variable. Inside the
agent, ``holdline.step(...)`` and functions decorated with ``@holdline.tool`` append steps to the
trace bound to the current context, so instrumentation is two lines and costs nothing when no
trace is active (the calls become no-ops outside a run).
"""

from __future__ import annotations

import contextvars
import functools
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterator, Optional

STEP_KINDS = ("tool", "llm", "decision", "error", "other")

_current: "contextvars.ContextVar[Optional[Trace]]" = contextvars.ContextVar(
    "holdline_trace", default=None)


@dataclass
class Step:
    kind: str
    name: str
    input: Any = None
    output: Any = None
    ms: float = 0.0
    tokens: Optional[int] = None
    cost: Optional[float] = None
    error: Optional[str] = None
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, {}, [])}


@dataclass
class Trace:
    case_id: str
    repeat: int = 0
    steps: list = field(default_factory=list)
    output: Any = None
    error: Optional[str] = None
    ms: float = 0.0
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    # -- derived views used by checks ---------------------------------------------------
    def tool_calls(self) -> list:
        return [s for s in self.steps if s.kind == "tool"]

    def tool_names(self) -> list:
        return [s.name for s in self.tool_calls()]

    @property
    def total_tokens(self) -> int:
        return sum(s.tokens or 0 for s in self.steps)

    @property
    def total_cost(self) -> float:
        return round(sum(s.cost or 0.0 for s in self.steps), 6)

    def to_dict(self) -> dict:
        return {"trace_id": self.trace_id, "case_id": self.case_id, "repeat": self.repeat,
                "ms": round(self.ms, 2), "output": _jsonable(self.output), "error": self.error,
                "steps": [s.to_dict() for s in self.steps]}

    @classmethod
    def from_dict(cls, d: dict) -> "Trace":
        steps = [Step(**{k: v for k, v in s.items() if k in Step.__dataclass_fields__})
                 for s in d.get("steps", [])]
        return cls(case_id=d["case_id"], repeat=d.get("repeat", 0), steps=steps,
                   output=d.get("output"), error=d.get("error"), ms=d.get("ms", 0.0),
                   trace_id=d.get("trace_id") or uuid.uuid4().hex)


def _jsonable(x: Any) -> Any:
    try:
        json.dumps(x)
        return x
    except (TypeError, ValueError):
        return repr(x)


def current() -> Optional[Trace]:
    """The trace bound to the running case, or None outside a run."""
    return _current.get()


def bind(trace: Trace) -> contextvars.Token:
    return _current.set(trace)


def unbind(token: contextvars.Token) -> None:
    _current.reset(token)


def step(kind: str, name: str, input: Any = None, output: Any = None, *, ms: float = 0.0,
         tokens: Optional[int] = None, cost: Optional[float] = None,
         error: Optional[str] = None, **meta: Any) -> Optional[Step]:
    """Record one step in the current trace. A no-op (returns None) outside a holdline run."""
    tr = _current.get()
    if tr is None:
        return None
    if kind not in STEP_KINDS:
        kind = "other"
    s = Step(kind=kind, name=str(name), input=_jsonable(input), output=_jsonable(output),
             ms=round(float(ms), 2), tokens=tokens, cost=cost, error=error, meta=meta)
    tr.steps.append(s)
    return s


def tool(fn: Optional[Callable] = None, *, name: Optional[str] = None, kind: str = "tool"):
    """Decorator: record each call of ``fn`` as a step (arguments, result, time, exception).

    Usable bare (``@tool``) or with options (``@tool(name="search")``)."""

    def wrap(f: Callable) -> Callable:
        label = name or f.__name__

        @functools.wraps(f)
        def inner(*args, **kwargs):
            if _current.get() is None:
                return f(*args, **kwargs)
            t0 = time.perf_counter()
            call_input = {"args": [_jsonable(a) for a in args],
                          "kwargs": {k: _jsonable(v) for k, v in kwargs.items()}}
            try:
                out = f(*args, **kwargs)
            except Exception as exc:
                step(kind, label, call_input, None, ms=(time.perf_counter() - t0) * 1000,
                     error=f"{type(exc).__name__}: {exc}")
                raise
            step(kind, label, call_input, out, ms=(time.perf_counter() - t0) * 1000)
            return out

        return inner

    return wrap(fn) if fn is not None else wrap


# -- persistence ------------------------------------------------------------------------
def write_jsonl(traces: list, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for t in traces:
            fh.write(json.dumps(t.to_dict(), ensure_ascii=False) + "\n")


def read_jsonl(path: str) -> Iterator[Trace]:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield Trace.from_dict(json.loads(line))


def to_otel(trace: Trace, service: str = "agent") -> dict:
    """The trace as an OpenTelemetry (OTLP/JSON) resourceSpans document, using the GenAI
    semantic-convention attribute names where they apply. No dependency on the OTel SDK."""
    root_id = trace.trace_id[:16]
    t_ns = int(time.time() * 1e9)
    spans = [{"traceId": trace.trace_id, "spanId": root_id, "name": f"case {trace.case_id}",
              "startTimeUnixNano": t_ns, "endTimeUnixNano": t_ns + int(trace.ms * 1e6),
              "attributes": [{"key": "holdline.case_id", "value": {"stringValue": trace.case_id}},
                             {"key": "holdline.repeat", "value": {"intValue": trace.repeat}}]}]
    cursor = t_ns
    for i, s in enumerate(trace.steps):
        attrs = [{"key": "holdline.step.kind", "value": {"stringValue": s.kind}}]
        if s.kind == "tool":
            attrs.append({"key": "gen_ai.tool.name", "value": {"stringValue": s.name}})
        if s.kind == "llm":
            attrs.append({"key": "gen_ai.request.model", "value": {"stringValue": s.name}})
        if s.tokens is not None:
            attrs.append({"key": "gen_ai.usage.total_tokens", "value": {"intValue": s.tokens}})
        span = {"traceId": trace.trace_id, "spanId": f"{root_id[:12]}{i:04x}",
                "parentSpanId": root_id, "name": f"{s.kind} {s.name}",
                "startTimeUnixNano": cursor, "endTimeUnixNano": cursor + int(s.ms * 1e6),
                "attributes": attrs}
        if s.error:
            span["status"] = {"code": 2, "message": s.error}
        spans.append(span)
        cursor += int(s.ms * 1e6)
    return {"resourceSpans": [{"resource": {"attributes": [
        {"key": "service.name", "value": {"stringValue": service}}]},
        "scopeSpans": [{"scope": {"name": "holdline"}, "spans": spans}]}]}
