import threading

import pytest

import holdline
from holdline.trace import Trace, bind, read_jsonl, to_otel, unbind, write_jsonl


@holdline.tool
def add(a, b):
    return a + b


@holdline.tool(name="explode")
def boom():
    raise RuntimeError("nope")


def test_noop_outside_a_run():
    assert holdline.step("tool", "x") is None
    assert add(1, 2) == 3
    assert holdline.current() is None


def test_records_tool_calls_and_errors():
    tr = Trace("c1")
    tok = bind(tr)
    try:
        add(2, b=3)
        holdline.step("llm", "some-model", "prompt", "reply", tokens=12, cost=0.001)
        with pytest.raises(RuntimeError):
            boom()
    finally:
        unbind(tok)
    assert [s.name for s in tr.steps] == ["add", "some-model", "explode"]
    assert tr.steps[0].input == {"args": [2], "kwargs": {"b": 3}}
    assert tr.steps[0].output == 5
    assert tr.steps[2].error == "RuntimeError: nope"
    assert tr.tool_names() == ["add", "explode"]
    assert tr.total_tokens == 12 and tr.total_cost == 0.001


def test_unknown_kind_becomes_other_and_unserialisable_is_repr():
    tr = Trace("c")
    tok = bind(tr)
    holdline.step("weird", "x", object())
    unbind(tok)
    assert tr.steps[0].kind == "other"
    assert isinstance(tr.steps[0].input, str)


def test_traces_are_isolated_per_thread():
    seen = {}

    def worker(i):
        tr = Trace(f"c{i}")
        tok = bind(tr)
        for _ in range(50):
            add(i, i)
        unbind(tok)
        seen[i] = len(tr.steps)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert seen == {i: 50 for i in range(8)}


def test_jsonl_roundtrip_and_otel(tmp_path):
    tr = Trace("c1", output={"answer": "ok"}, ms=12.5)
    tok = bind(tr)
    add(1, 1)
    holdline.step("llm", "m", tokens=5)
    unbind(tok)
    p = tmp_path / "t.jsonl"
    write_jsonl([tr], str(p))
    back = list(read_jsonl(str(p)))[0]
    assert back.case_id == "c1" and back.tool_names() == ["add"] and back.output == {"answer": "ok"}
    doc = to_otel(tr)
    spans = doc["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert len(spans) == 3 and spans[1]["parentSpanId"] == spans[0]["spanId"]
    assert {"key": "gen_ai.tool.name", "value": {"stringValue": "add"}} in spans[1]["attributes"]
