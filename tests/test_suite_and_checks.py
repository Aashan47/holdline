import json

import pytest

import holdline
from conftest import EXAMPLES
from holdline import suite
from holdline.checks import evaluate, match_answer, outcome_of, token_f1, validate
from holdline.suite import Case, SuiteError
from holdline.trace import Step, Trace


def test_load_example_suite():
    s = suite.load(f"{EXAMPLES}/refund_cases.jsonl")
    assert len(s) == 4 and s.name == "refund_cases"
    assert s.filter(tags=["uncovered"]).cases[0].must_pass
    assert len(s.filter(ids=["no-order-number"])) == 1


def test_json_object_form(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"name": "mine", "cases": [{"id": "a", "input": "x"}]}))
    assert suite.load(str(p)).name == "mine"


@pytest.mark.parametrize("bad, msg", [
    ([{"input": "x"}], "needs 'id'"),
    ([{"id": "a", "input": "x"}, {"id": "a", "input": "y"}], "duplicate"),
    ([{"id": "a", "input": "x", "expected": {"outcome": "maybe"}}], "outcome must be"),
    ([{"id": "a", "input": "x", "expected": {"tools_requird": []}}], "unknown expected keys"),
    ([{"id": "a", "input": "x", "expected": {"tools_required": "search"}}], "must be a list"),
])
def test_validation_errors(bad, msg):
    with pytest.raises(SuiteError, match=msg):
        suite.from_list(bad)


def _trace(output=None, tools=(), decisions=(), error=None):
    steps = [Step("tool", t, {"args": [], "kwargs": kw}) for t, kw in tools]
    steps += [Step("decision", d) for d in decisions]
    return Trace("c", steps=steps, output=output, error=error)


def test_outcome_detection():
    assert outcome_of(_trace({"outcome": "escalate", "answer": "x"})) == "escalate"
    assert outcome_of(_trace("hello", decisions=["abstain"])) == "abstain"
    assert outcome_of(_trace("")) == "abstain"
    assert outcome_of(_trace({"answer": "Paris"})) == "answer"


def test_answer_modes():
    assert match_answer("The capital is Paris.", "paris")[0]
    assert not match_answer("The capital is Paris.", "paris", mode="exact")[0]
    assert match_answer("Total: 1,250.00 USD", "1250", mode="numeric")[0]
    assert match_answer("order A-123 shipped", r"A-\d+", mode="regex")[0]
    assert match_answer("Lyon", ["Paris", "Lyon"], mode="exact")[0]
    ok, score, _ = match_answer("the cat sat on the mat", "a cat sat on a mat", mode="f1")
    assert ok and 0.6 < score < 1
    assert token_f1("", "") == 1.0


def test_trajectory_checks():
    case = Case("c", "q", expected={
        "outcome": "answer", "answer": "done", "tools_required": ["search", "read"],
        "tools_forbidden": ["delete"], "tool_order": ["search", "read"], "max_steps": 3,
        "no_loops": True})
    good = _trace({"answer": "done"}, tools=[("search", {"q": 1}), ("read", {})])
    assert all(r.passed for r in evaluate(case, good))

    bad = _trace({"answer": "done"}, tools=[("read", {}), ("search", {"q": 1}), ("search", {"q": 1}),
                                            ("search", {"q": 1}), ("delete", {})])
    failed = {r.check for r in evaluate(case, bad) if not r.passed}
    assert failed == {"tools_forbidden", "tool_order", "max_steps", "no_loops"}


def test_answer_skipped_when_outcome_is_not_answer():
    case = Case("c", "q", expected={"outcome": "escalate", "answer": "x"})
    names = [r.check for r in evaluate(case, _trace({"outcome": "escalate"}))]
    assert "answer" not in names


def test_tool_args_schema():
    schema = {"type": "object", "required": ["order_id"], "additionalProperties": False,
              "properties": {"order_id": {"type": "string", "pattern": "^A\\d{3}$"},
                             "amount": {"type": "number", "minimum": 0}}}
    assert validate({"order_id": "A100", "amount": 3.5}, schema) == []
    errs = validate({"order_id": "B1", "amount": -1, "x": 1}, schema)
    assert len(errs) == 3
    assert validate(True, {"type": "integer"})  # bool is not an integer
    assert validate([1, "a"], {"type": "array", "items": {"type": "integer"}})

    case = Case("c", "q", expected={"tool_args": {"refund": schema}})
    tr = _trace("ok", tools=[("refund", {"order_id": "nope"})])
    r = [x for x in evaluate(case, tr) if x.check == "tool_args"][0]
    assert not r.passed and "pattern" not in r.detail and "does not match" in r.detail


def test_custom_checks_and_errors_are_results():
    @holdline.check("short")
    def short(case, trace):
        return len(str(trace.output)) < 10, "too long"

    @holdline.check("crashes")
    def crashes(case, trace):
        raise ValueError("bad check")

    case = Case("c", "q", expected={"checks": ["short", "crashes", "missing_check"]})
    res = {r.check: r for r in evaluate(case, _trace("tiny"))}
    assert res["short"].passed and not res["crashes"].passed and not res["missing_check"].passed
    assert "bad check" in res["crashes"].detail


def test_rubric_uses_judge_and_survives_judge_errors():
    case = Case("c", "q", expected={"rubric": "be polite"})
    assert not [r for r in evaluate(case, _trace("x")) if r.check == "judge"][0].passed
    ok = evaluate(case, _trace("x"), judge=lambda c, t: {"pass": True, "reason": "fine"})
    assert all(r.passed for r in ok)

    def broken(c, t):
        raise TimeoutError("judge down")
    r = [r for r in evaluate(case, _trace("x"), judge=broken) if r.check == "judge"][0]
    assert not r.passed and "judge down" in r.detail


def test_error_fails_ran_check():
    r = evaluate(Case("c", "q"), _trace(error="ValueError: x"))
    assert r[0].check == "ran" and not r[0].passed
