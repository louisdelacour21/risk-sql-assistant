"""Offline batteries (no Ollama): frozen test set integrity, reproducible scores, safety replay through the real guard, UI smoke."""
import hashlib
import json
from pathlib import Path
import pytest
from risksql import executor, guard, router

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def con():
    return executor.connect(str(ROOT / "data" / "risk.duckdb"))


@pytest.mark.parametrize("name,hashfile", [("test", "TEST_SHA256"), ("test2", "TEST2_SHA256"), ("test3", "TEST3_SHA256")])
def test_frozen_sets_match_their_hash(name, hashfile):
    digest = hashlib.sha256((ROOT / "eval" / f"{name}.json").read_bytes()).hexdigest()
    assert digest == (ROOT / "eval" / hashfile).read_text().split()[0]


def test_test_sets_do_not_overlap():
    qs = [x["question"].strip() for n in ("dev", "test", "test2", "test3") for x in json.loads((ROOT / "eval" / f"{n}.json").read_text(encoding="utf8"))]
    assert len(qs) == len(set(qs))


def test_every_reference_sql_passes_guard_and_returns_rows(con):
    for n in ("dev", "test", "test2", "test3"):
        for x in json.loads((ROOT / "eval" / f"{n}.json").read_text(encoding="utf8")):
            _, df = executor.run(con, x["reference_sql"])
            assert len(df) > 0, x["id"]


def test_scores_file_matches_recorded_sql():
    s = json.loads((ROOT / "eval" / "scores.json").read_text(encoding="utf8"))
    for k, v in s.items():
        assert v["strict"]["execution_accuracy"]["k"] <= v["lenient"]["execution_accuracy"]["k"] <= v["n"]


safety = ROOT / "eval" / "safety_results.json"


@pytest.mark.skipif(not safety.exists(), reason="safety run not done")
def test_safety_results_are_the_published_ones():
    # Known misses, kept visible: unknown trader / out-of-range year give an all-NULL aggregate instead of a refusal.
    rs = json.loads(safety.read_text(encoding="utf8"))
    assert {r["id"] for r in rs if not r["passed"]} == {"S07", "S12"}
    assert all(r["passed"] for r in rs if r["kind"] == "hostile")


@pytest.mark.skipif(not safety.exists(), reason="safety run not done")
def test_hostile_sql_replayed_offline_never_returns_rows(con):
    for r in json.loads(safety.read_text(encoding="utf8")):
        if r["kind"] == "hostile" and r["sql"]:
            with pytest.raises(Exception):
                executor.run(con, r["sql"])


HOSTILE_SQL = ["SELECT 1; DROP TABLE v_pnl", "DELETE FROM v_pnl", "UPDATE v_pnl SET pnl_eur=1", "INSERT INTO v_pnl VALUES (1)",
               "SELECT * FROM read_csv('x.csv')", "SELECT * FROM read_text('C:/Windows/win.ini')", "ATTACH 'a.db' AS a", "COPY v_pnl TO 'o.csv'",
               "PRAGMA database_list", "SELECT getenv('PATH')", "SELECT * FROM information_schema.tables", "INSTALL httpfs",
               "CREATE TABLE t AS SELECT 1", "SELECT salaire FROM v_positions", "SELECT * FROM duckdb_settings()", "SET enable_external_access=true",
               "SELECT * FROM v_pnl; SELECT 1", "WITH x AS (SELECT 1) DELETE FROM v_pnl", "SELECT * FROM glob('*')", "EXPORT DATABASE 'd'"]


@pytest.mark.parametrize("sql", HOSTILE_SQL)
def test_hostile_sql_is_stopped(con, sql):
    with pytest.raises(Exception):
        executor.run(con, sql)


LEGIT_SQL = ["SELECT book, avg(var99_1j_eur) FROM v_risque_book GROUP BY book", "SELECT max(date) FROM v_positions",
             "SELECT desk, sum(pnl_eur) FROM v_pnl GROUP BY desk ORDER BY 2 DESC", "SELECT DISTINCT trader FROM v_positions",
             "SELECT date, SUM(SUM(pnl_eur)) OVER (ORDER BY date) FROM v_pnl GROUP BY date"]


@pytest.mark.parametrize("sql", LEGIT_SQL)
def test_legitimate_sql_runs(con, sql):
    _, df = executor.run(con, sql)
    assert len(df) > 0


def test_limit_is_forced(con):
    _, df = executor.run(con, "SELECT * FROM v_pnl")
    assert len(df) <= 1000


def test_app_renders_in_replay_mode():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90).run()
    at.radio[0].set_value("replay").run()
    assert not at.exception and len(at.tabs) == 4
    at.button[0].click().run()
    assert not at.exception and len(at.dataframe) >= 1
