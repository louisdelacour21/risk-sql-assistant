"""Offline checks (no Ollama): replay mode runs recorded SQL through the real guard, and the published numbers reproduce."""
import json
import pytest
from risksql import executor, router, evaluate as ev


@pytest.fixture(scope="module")
def con():
    return executor.connect("data/risk.duckdb")


def test_template_question_needs_no_model(con):
    r = router.answer(con, "Quelle est la VaR du book FX_SPOT au dernier jour ?", "replay")
    assert r["route"].startswith("template:") and r["df"].shape == (1, 1)


def test_unknown_question_is_declined_in_replay(con):
    assert router.answer(con, "Question inconnue", "replay")["error"]


def test_replay_never_bypasses_guard(con, monkeypatch):
    monkeypatch.setattr(router, "REPLAY", router.REPLAY)
    bad = {"q": {"sql": "DROP TABLE v_pnl", "error": None}}
    monkeypatch.setattr(router.json, "loads", lambda _: bad)
    r = router.answer(con, "q", "replay")
    assert r["df"] is None and "Rejected" in r["error"]


def test_test_v2_numbers_reproduce_from_recorded_sql(con):
    items = ev.load("test2")
    assert open("eval/TEST2_SHA256").read().strip() == __import__("hashlib").sha256(open("eval/test2.json", "rb").read()).hexdigest()
    outcomes = []
    for it in items:
        _, ref = executor.run(con, it["reference_sql"])
        got = None
        try:
            _, got = executor.run(con, json.load(open("eval/llm_test2.json", encoding="utf8"))[int(it["id"][1:]) - 1]["sql"] or "")
        except Exception:
            pass
        outcomes.append(ev.outcome(ref, got, it["ordered"]))
    assert outcomes.count("correct") == 53 and outcomes.count("silent_wrong") == 6
