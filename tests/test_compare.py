import json

import pytest
from conftest import EXAMPLES

from holdline import cli, gate
from holdline.importers import ResultsError, as_pass, load_results
from holdline.runner import Run


def test_csv_export_reaches_the_same_verdict_as_the_native_gate():
    base_native = Run.load(f"{EXAMPLES}/helpdesk/results/production-k3.json")
    cand_native = Run.load(f"{EXAMPLES}/helpdesk/results/one-sample-k3.json")
    base_csv = load_results(f"{EXAMPLES}/compare/helpdesk-5-samples.csv")
    cand_csv = load_results(f"{EXAMPLES}/compare/helpdesk-1-sample.csv")
    a, b = gate(cand_native, base_native), gate(cand_csv, base_csv)
    assert (a.passed, a.regressions, a.fixes, a.mcnemar_p, a.delta) == \
           (b.passed, b.regressions, b.fixes, b.mcnemar_p, b.delta)
    assert base_csv.summary["pass^3"] == base_native.summary["pass^3"]
    assert base_csv.meta["columns"] == {"id": "case_id", "pass": "passed", "repeat": "run",
                                        "tags": "group", "must_pass": None}


def test_formats_scores_and_explicit_columns(tmp_path):
    rows = [{"test": "a", "grade": 0.9}, {"test": "a", "grade": 0.2}, {"test": "b", "grade": 0.7}]
    p = tmp_path / "r.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows))
    with pytest.raises(ResultsError, match="--id-col"):
        load_results(str(p))
    run = load_results(str(p), id_col="test", threshold=0.5)
    assert [c.id for c in run.cases] == ["a", "b"]
    assert run.meta["repeats"] == 2
    assert run.summary["flaky_cases"] == ["a"]
    assert run.results[0].checks[0].score == 0.9

    wrapped = tmp_path / "w.json"
    wrapped.write_text(json.dumps({"results": {"results": [{"id": "x", "success": True}]}}))
    assert load_results(str(wrapped)).results[0].passed

    tsv = tmp_path / "t.tsv"
    tsv.write_text("id\tverdict\tmust_pass\nq1\tyes\ttrue\nq2\tno\tfalse\n")
    r = load_results(str(tsv))
    assert [c.must_pass for c in r.cases] == [True, False]
    assert r.summary["must_pass_failed"] == []


def test_bad_values_are_reported(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("id,passed\nq1,maybe\n")
    with pytest.raises(ResultsError, match="cannot read"):
        load_results(str(p))
    assert as_pass("PASS") and not as_pass("Fail") and as_pass(0.75) and not as_pass("0.2")


def test_holdline_run_files_pass_through(tmp_path):
    r = load_results(f"{EXAMPLES}/helpdesk/results/production-k3.json", label="prod")
    assert r.meta["label"] == "prod" and len(r.results) == 204


def test_cli_compare(tmp_path, capsys):
    b, c = f"{EXAMPLES}/compare/helpdesk-5-samples.csv", f"{EXAMPLES}/compare/helpdesk-1-sample.csv"
    html = tmp_path / "r.html"
    assert cli.main(["compare", b, c, "--html", str(html)]) == 0
    out = capsys.readouterr().out
    assert "PASS" in out and "68" in out
    page = html.read_text()
    assert "Imported record" in page and "Trace," not in page
    worse = tmp_path / "worse.csv"
    worse.write_text("".join(line.replace(",pass,", ",fail,") if line.startswith(("what", "how", "which", "can", "i-"))
                             else line for line in open(c)))
    assert cli.main(["compare", b, str(worse)]) == 1
    assert cli.main(["compare", b, str(tmp_path / "missing.csv")]) == 2
