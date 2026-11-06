import time
import pytest
from risksql.guard import check, Rejected
from risksql import executor

HOSTILE = [
    "DROP TABLE t_positions", "DROP VIEW v_pnl", "DELETE FROM t_positions", "UPDATE t_positions SET notionnel = 0",
    "INSERT INTO t_positions SELECT * FROM t_positions", "CREATE TABLE x AS SELECT 1", "ALTER TABLE t_pnl ADD COLUMN a INT",
    "ATTACH 'other.db'", "DETACH risk", "COPY v_pnl TO 'out.csv'", "PRAGMA version", "INSTALL httpfs", "LOAD httpfs",
    "SET threads = 1", "SET lock_configuration = false", "SELECT 1; SELECT 2", "SELECT 1; DROP TABLE t_positions",
    "SELECT * FROM read_csv('x.csv')", "SELECT * FROM read_parquet('x.parquet')", "SELECT * FROM glob('*')",
    "SELECT getenv('PATH')", "SELECT * FROM t_positions", "SELECT * FROM main.v_pnl", "SELECT * FROM information_schema.tables",
    "SELECT * FROM duckdb_tables()", "SELECT dv01 FROM v_positions", "SELECT trader_name FROM v_pnl",
    "SELECT current_date", "SELECT * FROM v_pnl WHERE date = now()", "SELECT * FROM v_pnl WHERE date = current_timestamp",
    "SELECT random()", "SELECT * FROM range(10)", "SELECT * FROM v_pnl, read_csv('x.csv')", "", "   ", "SELEC * FROM v_pnl",
    "SELECT * FROM v_pnl WHERE", "WITH x AS (DROP TABLE t_pnl) SELECT 1", "EXPLAIN SELECT * FROM v_pnl",
    "SELECT * FROM v_pnl WHERE book = (SELECT getenv('HOME'))",
]
LEGIT = [
    "SELECT * FROM v_pnl", "SELECT book, sum(pnl_eur) FROM v_pnl GROUP BY book",
    "SELECT book, count(*) AS j, max(utilisation_pct) AS pic FROM v_limites WHERE date BETWEEN DATE '2026-09-01' AND DATE '2026-09-30' AND utilisation_pct > 80 GROUP BY book ORDER BY j DESC",
    "SELECT trader, sum(abs(dv01_eur)) AS d FROM v_positions WHERE date = (SELECT max(date) FROM v_positions) GROUP BY trader ORDER BY d DESC LIMIT 3",
    "WITH d AS (SELECT max(date) AS m FROM v_positions) SELECT sum(notionnel) FROM v_positions, d WHERE date = d.m AND devise = 'USD'",
    "SELECT date, var99_1j_eur - lag(var99_1j_eur) OVER (PARTITION BY book ORDER BY date) AS d FROM v_risque_book",
    "SELECT strftime(date, '%Y-%m') AS mois, sum(pnl_eur) FROM v_pnl GROUP BY 1 ORDER BY 1",
    "SELECT CASE WHEN depassement_var THEN 'oui' ELSE 'non' END AS exc, count(*) FROM v_risque_book GROUP BY 1",
    "SELECT book, avg(es975_1j_eur) FROM v_risque_book GROUP BY book HAVING avg(es975_1j_eur) > 1000",
    "SELECT serie, valeur FROM v_marche WHERE date = DATE '2026-10-30' AND serie LIKE 'EUR%'",
    "SELECT desk, book, sum(pnl_eur) OVER (PARTITION BY book ORDER BY date) AS cum FROM v_pnl",
    "SELECT date, sum(pnl_eur) FROM v_pnl WHERE date >= DATE '2026-10-01' GROUP BY date ORDER BY date",
    "SELECT book, median(utilisation_pct), quantile_cont(utilisation_pct, 0.95) FROM v_limites GROUP BY book",
    "SELECT a.book FROM v_limites a JOIN v_risque_book b ON a.date = b.date AND a.book = b.book WHERE b.depassement_var",
    "SELECT * FROM v_pnl UNION ALL SELECT * FROM v_pnl",
    "SELECT round(sum(delta_fx_eur) / 1e6, 2) AS mm FROM v_positions WHERE date = DATE '2026-10-30'",
    "SELECT count(DISTINCT position_id) FROM v_positions",
    "SELECT trader, coalesce(sum(pnl_eur), 0) FROM v_pnl GROUP BY trader",
    "select BOOK from V_PNL",
    "SELECT book FROM v_pnl -- commentaire",
    "SELECT book, pnl_eur FROM v_pnl ORDER BY pnl_eur LIMIT 5",
]


@pytest.mark.parametrize("sql", HOSTILE)
def test_hostile_rejected(sql):
    with pytest.raises(Rejected):
        check(sql)


@pytest.mark.parametrize("sql", LEGIT)
def test_legit_accepted(sql):
    assert check(sql).upper().startswith(("SELECT", "WITH"))


def test_limit_added_once():
    assert check("SELECT * FROM v_pnl").endswith("LIMIT 1000")
    assert check("SELECT * FROM v_pnl LIMIT 5").endswith("LIMIT 5")


@pytest.fixture(scope="module")
def con():
    return executor.connect("data/risk.duckdb")


def test_execution_and_readonly(con):
    _, df = executor.run(con, "SELECT count(*) AS n FROM v_positions")
    assert df.n[0] == 15000
    with pytest.raises(Exception):
        con.execute("CREATE TABLE x AS SELECT 1")  # bypasses the guard on purpose: the connection itself must refuse
    with pytest.raises(Exception):
        con.execute("SET enable_external_access = true")
    with pytest.raises(Exception):
        con.execute("SELECT * FROM read_csv('data/risk.duckdb')")


def test_cartesian_product_interrupted(con):
    t = time.time()
    with pytest.raises(TimeoutError):
        executor.run(con, "SELECT count(*) FROM v_positions a, v_positions b, v_positions c, v_positions d", timeout=2)
    assert time.time() - t < 6
