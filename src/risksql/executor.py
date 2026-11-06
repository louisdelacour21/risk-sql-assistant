"""Read-only execution with a hard time limit. Defence in depth: even if the guard missed something, the connection
cannot write, cannot touch files or the network, and cannot change its own settings."""
import threading
import duckdb
import pandas as pd
from .guard import check

TIMEOUT_S = 5


def connect(path="data/risk.duckdb"):
    con = duckdb.connect(path, read_only=True, config={"enable_external_access": False})
    con.execute("SET lock_configuration = true")
    return con


def run(con, sql, timeout=TIMEOUT_S):
    """Guard, then execute. Returns (validated_sql, DataFrame). Raises guard.Rejected or TimeoutError."""
    sql = check(sql)
    timer = threading.Timer(timeout, con.interrupt)
    timer.start()
    try:
        return sql, con.execute(sql).df()
    except duckdb.InterruptException:
        raise TimeoutError(f"query stopped after {timeout} s")
    except duckdb.Error as e:
        raise ValueError(f"execution error: {str(e).splitlines()[0]}")
    finally:
        timer.cancel()
