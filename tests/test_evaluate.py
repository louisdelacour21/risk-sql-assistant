import hashlib
import pandas as pd
import pytest
from risksql import executor, evaluate as ev


def test_comparator_rules():
    a = pd.DataFrame({"x": [1.0000001, 2.0], "y": ["a", "b"]})
    assert ev.same(a, pd.DataFrame({"y": ["b", "a"], "x": [2.0, 1.0]}))  # column + row order ignored
    assert not ev.same(a, pd.DataFrame({"y": ["b", "a"], "x": [2.0, 1.0]}), ordered=True)
    assert not ev.same(a, pd.DataFrame({"x": [1.1, 2.0], "y": ["a", "b"]}))
    assert ev.same(pd.DataFrame({"x": [None, 1.0]}), pd.DataFrame({"x": [1.0, float("nan")]}))  # NULL is a value
    assert not ev.same(pd.DataFrame({"x": [1, 1]}), pd.DataFrame({"x": [1]}))  # multiset, not set
    assert ev.outcome(a, None) == "declared"


def test_reference_vs_reference_is_100_percent():
    con = executor.connect("data/risk.duckdb")
    for split in ("dev", "test"):
        out = []
        for it in ev.load(split):
            _, ref = executor.run(con, it["reference_sql"])
            _, got = executor.run(con, it["reference_sql"])
            out.append(ev.outcome(ref, got, it["ordered"]))
        assert set(out) == {"correct"}, split


def test_test_set_is_frozen():
    assert hashlib.sha256(open("eval/test.json", "rb").read()).hexdigest() + "\n" == open("eval/TEST_SHA256").read()


def test_stats_sanity():
    s = ev.summarize(["correct"] * 8 + ["silent_wrong"] + ["declared"])
    assert s["execution_accuracy"]["k"] == 8 and s["execution_accuracy"]["lo"] < 0.8 < s["execution_accuracy"]["hi"]
    p, only_a, only_b = ev.mcnemar_p(["correct"] * 10 + ["declared"] * 10, ["declared"] * 10 + ["declared"] * 10)
    assert only_a == 10 and only_b == 0 and p < 0.01
