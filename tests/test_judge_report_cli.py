import json
import random

import pytest

import refund_agent
from conftest import EXAMPLES
from holdline import cli, report, run, suite
from holdline.judge import as_bool, calibrate, llm_judge
from holdline.suite import Case
from holdline.trace import Trace


def _labels(n, flip_fail_to_pass=0.0, flip_pass_to_fail=0.0, group=None, seed=0):
    rng = random.Random(seed)
    items = []
    for i in range(n):
        human = i % 2 == 0
        judge = human
        if not human and rng.random() < flip_fail_to_pass:
            judge = True
        if human and rng.random() < flip_pass_to_fail:
            judge = False
        it = {"id": f"{group}-{i}", "human": human, "judge": judge}
        if group:
            it["group"] = group
        items.append(it)
    return items


def test_good_judge_is_fit():
    rep = calibrate(_labels(80, 0.02, 0.02))
    assert rep["fit_to_gate"], rep["reasons"]
    assert rep["overall"]["kappa"] > 0.85


def test_lenient_judge_is_not_fit():
    rep = calibrate(_labels(80, flip_fail_to_pass=0.4))
    assert not rep["fit_to_gate"]
    assert rep["overall"]["bias"] > 0
    assert any("false-pass" in r for r in rep["reasons"])


def test_sign_reversal_is_detected():
    easy = _labels(40, flip_fail_to_pass=0.5, group="easy", seed=1)
    hard = _labels(40, flip_pass_to_fail=0.5, group="hard", seed=2)
    rep = calibrate(easy + hard)
    assert rep["sign_reversal"]
    assert rep["lenient_groups"] == ["easy"] and rep["harsh_groups"] == ["hard"]
    assert not rep["fit_to_gate"]


def test_small_sample_not_fit_and_threshold_tuning():
    assert any("labelled items" in r for r in calibrate(_labels(10))["reasons"])
    rng = random.Random(3)
    items = []
    for i in range(60):
        human = i % 2 == 0
        score = (0.7 if human else 0.3) + rng.uniform(-0.25, 0.25)
        items.append({"human": human, "judge": score >= 0.5, "judge_score": round(score, 3)})
    t = calibrate(items)["threshold"]
    assert 0.3 < t["threshold"] < 0.75 and t["kappa_held_out_half"] > 0.6


def test_as_bool():
    assert as_bool("PASS") and not as_bool("fail") and as_bool(1) and not as_bool(0.2)
    with pytest.raises(ValueError):
        as_bool("maybe")


def test_llm_judge_parses_verdict():
    seen = {}

    def fake_model(prompt):
        seen["prompt"] = prompt
        return "Polite and correct.\nVERDICT: PASS"

    j = llm_judge(fake_model)
    case = Case("c", "hello", expected={"rubric": "must be polite"})
    out = j(case, Trace("c", output={"answer": "Hi there"}))
    assert out["pass"] and "must be polite" in seen["prompt"] and "Hi there" in seen["prompt"]
    bad = llm_judge(lambda p: "looks fine to me")(case, Trace("c", output="x"))
    assert not bad["pass"] and bad["reason"].startswith("unparseable")


def test_reports_render():
    s = suite.load(f"{EXAMPLES}/refund_cases.jsonl")
    base = run(refund_agent.agent_v1, s, label="v1")
    cand = run(refund_agent.agent_v2, s, label="v2")
    from holdline import gate
    res = gate(cand, base)
    md = report.gate_markdown(res, cand, base)
    assert "FAIL" in md and "| pass rate |" in md and "refund-damaged" in md
    page = report.run_html(cand, res, base)
    assert page.startswith("<!doctype html>") and "refund-damaged" in page
    assert "src=" not in page and "href=\"http" not in page and "@import" not in page  # self-contained
    assert "pass rate" in report.text_summary(base)


def test_cli_end_to_end(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(EXAMPLES)
    summary = tmp_path / "step_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    b, c = str(tmp_path / "b.json"), str(tmp_path / "c.json")
    assert cli.main(["run", "--suite", "refund_cases.jsonl", "--target", "refund_agent:agent_v1",
                     "-k", "2", "--out", b, "--html", str(tmp_path / "r.html"), "-q"]) == 0
    assert cli.main(["run", "--suite", "refund_cases.jsonl", "--target", "refund_agent:agent_v2",
                     "--out", c, "-q"]) == 0
    assert cli.main(["gate", "--baseline", b, "--candidate", b]) == 0
    assert cli.main(["gate", "--baseline", b, "--candidate", c, "--markdown",
                     str(tmp_path / "g.md")]) == 1
    assert "FAIL" in summary.read_text()
    assert cli.main(["show", b]) == 0
    assert cli.main(["report", c, "--baseline", b, "--html", str(tmp_path / "x.html")]) == 0

    labels = tmp_path / "labels.jsonl"
    labels.write_text("\n".join(json.dumps(x) for x in _labels(10)))
    assert cli.main(["calibrate", "--labels", str(labels)]) == 0
    assert cli.main(["calibrate", "--labels", str(labels), "--strict"]) == 1
    assert cli.main(["run", "--suite", "missing.jsonl", "--target", "refund_agent:agent_v1"]) == 2
