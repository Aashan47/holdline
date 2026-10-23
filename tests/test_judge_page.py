"""The browser judge check (site/judge/judge.js) must agree with holdline.judge.calibrate."""

import json
import os
import random
import shutil
import subprocess

import pytest
from conftest import EXAMPLES, ROOT

from holdline.judge import calibrate, load_labels

JS = os.path.join(ROOT, "site", "judge", "judge.js")
node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node is not installed")


def _js(items, opts=None):
    script = ("const J=require(process.argv[1]);let d='';process.stdin.on('data',c=>d+=c);"
              "process.stdin.on('end',()=>{const x=JSON.parse(d);console.log(JSON.stringify(J.calibrate(x.items,x.opts)));});")
    out = subprocess.run([node, "-e", script, JS], input=json.dumps({"items": items, "opts": opts or {}}),
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def _same_point_estimates(py, js):
    for key in ("n", "agreement", "kappa", "kappa_band", "confusion", "bias", "false_pass_rate", "false_fail_rate"):
        assert py["overall"][key] == js["overall"][key], key
    assert py["groups"].keys() == js["groups"].keys()
    for g in py["groups"]:
        for key in ("n", "agreement", "kappa", "bias", "false_pass_rate"):
            assert py["groups"][g][key] == js["groups"][g][key], (g, key)
    for key in ("sign_reversal", "lenient_groups", "harsh_groups"):
        assert py[key] == js[key], key


def test_synthetic_labels_match_python():
    items = load_labels(f"{EXAMPLES}/judge_labels_synthetic.jsonl")
    py, js = calibrate(items), _js(items)
    _same_point_estimates(py, js)
    # interval: different random stream, same method; must agree within sampling error
    assert abs(py["overall"]["kappa_ci"][0] - js["overall"]["kappa_ci"][0]) < 0.05
    assert abs(py["overall"]["kappa_ci"][1] - js["overall"]["kappa_ci"][1]) < 0.05
    assert py["fit_to_gate"] == js["fit_to_gate"] is False


def test_random_label_sets_match_python():
    rng = random.Random(11)
    for _ in range(20):
        n = rng.randint(4, 90)
        items = [{"human": rng.random() < 0.6, "judge": rng.random() < 0.6,
                  "group": rng.choice(["a", "b", "c"])} for _ in range(n)]
        _same_point_estimates(calibrate(items), _js(items))


def test_threshold_tuning_is_reported():
    rng = random.Random(3)
    items = []
    for i in range(60):
        human = i % 2 == 0
        score = round((0.7 if human else 0.3) + rng.uniform(-0.25, 0.25), 3)
        items.append({"human": human, "judge": score >= 0.5, "judge_score": score})
    js = _js(items)
    assert 0.3 < js["threshold"]["threshold"] < 0.75 and js["threshold"]["kappa_held_out_half"] > 0.5


def test_parsers():
    script = ("const J=require(process.argv[1]);const r={csv:J.parse('id,human,judge\\n1,\"pass, sure\",fail\\n2,pass,pass\\n'),"
              "jsonl:J.parse('{\"human\":1,\"judge\":0}\\n{\"human\":0,\"judge\":0}'),"
              "wrapped:J.parse('{\"labels\":[{\"human\":true,\"judge\":true}]}'),"
              "guess:J.guessColumns(['ID','Human_Label','LLM_Judge','Difficulty','score'])};console.log(JSON.stringify(r));")
    out = json.loads(subprocess.run([node, "-e", script, JS], capture_output=True, text=True, check=True).stdout)
    assert out["csv"][0]["human"] == "pass, sure" and len(out["csv"]) == 2
    assert len(out["jsonl"]) == 2 and out["wrapped"][0]["judge"] is True
    assert out["guess"] == {"human": "Human_Label", "judge": "LLM_Judge", "group": "Difficulty",
                            "judge_score": "score", "id": "ID"}
