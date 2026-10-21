import asyncio
import random

import pytest

import holdline
import refund_agent
from conftest import EXAMPLES
from holdline import GateConfig, gate, run, suite
from holdline.runner import Run
from holdline.suite import from_list


@pytest.fixture
def cases():
    return suite.load(f"{EXAMPLES}/refund_cases.jsonl")


def test_good_agent_passes_everything(cases):
    r = run(refund_agent.agent_v1, cases, repeats=3)
    s = r.summary
    assert s["pass_rate"] == 1.0 and s["pass^3"] == 1.0 and not s["flaky_cases"]
    assert s["withheld_when_should"] == 1.0 and s["answered_when_should"] == 1.0
    assert s["runs"] == 12 and s["errors"] == 0


def test_helpful_rewrite_is_caught(cases):
    r = run(refund_agent.agent_v2, cases)
    s = r.summary
    assert s["must_pass_failed"] == ["refund-damaged"]
    assert s["withheld_when_should"] == 0.0
    by = {c: rs[0] for c, rs in r.by_case().items()}
    failed = {c.check for c in by["refund-damaged"].failed_checks}
    assert {"outcome", "tools_forbidden", "tools_required"} <= failed


def test_exceptions_and_async_targets():
    s = from_list([{"id": "a", "input": 1}, {"id": "b", "input": 2}])

    def flaky(x):
        if x == 2:
            raise KeyError("missing")
        return "ok"

    r = run(flaky, s, workers=1)
    assert r.summary["errors"] == 1 and r.summary["pass_rate"] == 0.5

    async def aio(x):
        await asyncio.sleep(0)
        holdline.step("tool", "noop")
        return "ok"

    r = run(aio, s, workers=2)
    assert r.summary["pass_rate"] == 1.0
    assert all(cr.trace.tool_names() == ["noop"] for cr in r.results)


def test_soft_timeout():
    import time
    s = from_list([{"id": "a", "input": 0}])
    r = run(lambda x: time.sleep(0.05), s, timeout=0.01)
    assert r.results[0].trace.error.startswith("Timeout")


def test_flaky_and_pass_hat_k():
    rng = random.Random(1)
    s = from_list([{"id": f"c{i}", "input": i, "expected": {"answer": "ok"}} for i in range(10)])
    r = run(lambda x: "ok" if x < 5 or rng.random() < 0.5 else "no", s, repeats=4, workers=1)
    sm = r.summary
    assert sm["flaky_cases"] and sm["pass^4"] < sm["pass_rate"]


def test_save_and_load_roundtrip(cases, tmp_path):
    r = run(refund_agent.agent_v1, cases, repeats=2, label="v1")
    p = r.save(str(tmp_path / "run.json"))
    back = Run.load(p)
    assert back.summary == r.summary or back.summary["pass_rate"] == r.summary["pass_rate"]
    assert back.meta["label"] == "v1" and len(back.results) == 8


def test_gate_catches_regression_and_passes_identical(cases):
    base = run(refund_agent.agent_v1, cases, label="v1")
    same = run(refund_agent.agent_v1, cases, label="v1-again")
    assert gate(same, base).passed

    worse = run(refund_agent.agent_v2, cases, label="v2")
    res = gate(worse, base, GateConfig(max_drop=0.05))
    assert not res.passed and res.verdict == "FAIL"
    # refund-in-window still gets the right answer, but skipped the policy check: caught too
    assert set(res.regressions) == {"refund-in-window", "refund-damaged", "no-order-number",
                                    "refund-expired"}
    in_window = worse.by_case()["refund-in-window"][0]
    assert [c.check for c in in_window.failed_checks] == ["tool_order"]
    assert any("must-pass" in r for r in res.reasons)
    assert any("dropped" in r for r in res.reasons)
    assert res.delta["estimate"] == pytest.approx(-1.0)


def test_gate_significance_needs_enough_discordant_pairs():
    s = from_list([{"id": f"c{i}", "input": i, "expected": {"answer": "ok"}} for i in range(40)])
    base = run(lambda x: "ok", s)
    two_broke = run(lambda x: "no" if x < 2 else "ok", s)
    res = gate(two_broke, base)
    assert res.passed and res.warnings  # 2 vs 0 is not significant: warn, do not fail
    many_broke = run(lambda x: "no" if x < 10 else "ok", s)
    res = gate(many_broke, base)
    assert not res.passed and res.mcnemar_p < 0.01


def test_gate_absolute_rules_without_baseline(cases):
    r = run(refund_agent.agent_v2, cases)
    res = gate(r, None, GateConfig(min_pass_rate=0.9, min_withheld=0.9, enforce_must_pass=False))
    assert len(res.reasons) == 2
    with pytest.raises(ValueError):
        GateConfig.from_dict({"max_dorp": 0.1})
