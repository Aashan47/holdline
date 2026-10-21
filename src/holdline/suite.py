"""Case suites: what the agent is asked, and what must be true of what it does.

A suite is a JSON list, a JSON object with a ``cases`` list, JSONL (one case per line), or YAML
when PyYAML is installed. Example case::

    {"id": "refund-uncovered", "input": "Can I get a refund for a cracked screen?",
     "expected": {"outcome": "escalate", "tools_forbidden": ["issue_refund"]},
     "tags": ["refunds", "uncovered"], "must_pass": true}
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

OUTCOMES = ("answer", "abstain", "escalate")

EXPECTED_KEYS = {
    "answer", "answer_match", "outcome", "tools_required", "tools_forbidden", "tool_order",
    "max_steps", "max_tool_calls", "tool_args", "no_loops", "rubric", "checks",
}


class SuiteError(ValueError):
    pass


@dataclass
class Case:
    id: str
    input: Any
    expected: dict = field(default_factory=dict)
    tags: list = field(default_factory=list)
    difficulty: Optional[str] = None
    must_pass: bool = False
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {"id": self.id, "input": self.input, "expected": self.expected}
        if self.tags:
            d["tags"] = self.tags
        if self.difficulty is not None:
            d["difficulty"] = self.difficulty
        if self.must_pass:
            d["must_pass"] = True
        if self.meta:
            d["meta"] = self.meta
        return d


@dataclass
class Suite:
    name: str
    cases: list
    path: Optional[str] = None

    def __len__(self) -> int:
        return len(self.cases)

    def __iter__(self):
        return iter(self.cases)

    def filter(self, tags: Optional[list] = None, ids: Optional[list] = None) -> "Suite":
        cases = self.cases
        if tags:
            cases = [c for c in cases if set(tags) & set(c.tags)]
        if ids:
            cases = [c for c in cases if c.id in set(ids)]
        return Suite(self.name, cases, self.path)


def _case(raw: dict, where: str) -> Case:
    if not isinstance(raw, dict):
        raise SuiteError(f"{where}: a case must be an object, got {type(raw).__name__}")
    if "id" not in raw or "input" not in raw:
        raise SuiteError(f"{where}: a case needs 'id' and 'input'")
    expected = raw.get("expected") or {}
    if not isinstance(expected, dict):
        raise SuiteError(f"{where} ({raw['id']}): 'expected' must be an object")
    unknown = set(expected) - EXPECTED_KEYS
    if unknown:
        raise SuiteError(f"{where} ({raw['id']}): unknown expected keys {sorted(unknown)}; "
                         f"known: {sorted(EXPECTED_KEYS)}")
    outcome = expected.get("outcome")
    if outcome is not None and outcome not in OUTCOMES:
        raise SuiteError(f"{where} ({raw['id']}): outcome must be one of {OUTCOMES}")
    for key in ("tools_required", "tools_forbidden", "tool_order"):
        if key in expected and not isinstance(expected[key], list):
            raise SuiteError(f"{where} ({raw['id']}): '{key}' must be a list of tool names")
    extra = {k: v for k, v in raw.items()
             if k not in {"id", "input", "expected", "tags", "difficulty", "must_pass", "meta"}}
    return Case(id=str(raw["id"]), input=raw["input"], expected=expected,
                tags=list(raw.get("tags") or []), difficulty=raw.get("difficulty"),
                must_pass=bool(raw.get("must_pass", False)),
                meta={**(raw.get("meta") or {}), **extra})


def from_list(items: list, name: str = "suite", path: Optional[str] = None) -> Suite:
    cases = [_case(raw, f"case {i}") for i, raw in enumerate(items)]
    seen = set()
    for c in cases:
        if c.id in seen:
            raise SuiteError(f"duplicate case id {c.id!r}")
        seen.add(c.id)
    return Suite(name=name, cases=cases, path=path)


def load(path: str) -> Suite:
    """Load a suite from .json, .jsonl or .yaml/.yml."""
    name = os.path.splitext(os.path.basename(path))[0]
    ext = os.path.splitext(path)[1].lower()
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if ext == ".jsonl":
        items = []
        for n, line in enumerate(text.splitlines(), 1):
            if line.strip() and not line.lstrip().startswith("//"):
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise SuiteError(f"{path}:{n}: {exc}") from None
    elif ext in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError:
            raise SuiteError("YAML suites need PyYAML: pip install 'holdline[yaml]'") from None
        items = yaml.safe_load(text)
    else:
        items = json.loads(text)
    if isinstance(items, dict):
        name = items.get("name", name)
        items = items.get("cases", [])
    if not isinstance(items, list):
        raise SuiteError(f"{path}: expected a list of cases")
    return from_list(items, name=name, path=path)
