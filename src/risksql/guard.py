"""Deterministic SQL guard. The model proposes, this decides: one read-only statement, catalogue views only,
whitelisted functions, no invented columns. Nothing here calls a model."""
from pathlib import Path
import sqlglot
import yaml
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify

CAT = yaml.safe_load((Path(__file__).parent / "catalog.yaml").read_text(encoding="utf8"))
SCHEMA = {v: {c: t for c, (t, _) in d["columns"].items()} for v, d in CAT["views"].items()}
ALLOWED_FUNCS = set(CAT["functions"])
LIMIT = 1000
WRITE = (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter, exp.Command, exp.Copy, exp.Merge,
         exp.Set, exp.Use, exp.Pragma, exp.Attach, exp.Detach, exp.Transaction, exp.Commit, exp.Rollback, exp.Install)
# names that parse as plain Column/Anonymous in some dialect versions
FORBIDDEN_NAMES = {"current_date", "current_timestamp", "now", "today", "getenv", "read_csv", "read_parquet",
                   "read_json", "glob", "range", "generate_series", "query", "system", "random"}


SKIP = (exp.Binary, exp.Unary, exp.Case, exp.If, exp.Window, exp.Exists, exp.In, exp.Between, exp.Paren, exp.Extract, exp.Interval)


class Rejected(ValueError):
    """The SQL is refused; the message is precise enough to send back to the model for a repair."""


def check(sql):
    """Return the validated SQL (LIMIT added if missing) or raise Rejected."""
    try:
        stmts = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise Rejected(f"syntax error: {str(e).splitlines()[0]}")
    if len(stmts) != 1:
        raise Rejected("exactly one statement is allowed")
    tree = stmts[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.Subquery)):
        raise Rejected(f"only SELECT is allowed, got {type(tree).__name__}")
    for node in tree.walk():
        if isinstance(node, WRITE):
            raise Rejected(f"forbidden statement: {type(node).__name__}")
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for t in tree.find_all(exp.Table):
        if not t.name:
            raise Rejected("table function not allowed")
        if t.name.lower() not in SCHEMA and t.name.lower() not in ctes:
            raise Rejected(f"unknown table or view {t.name}; allowed: {', '.join(SCHEMA)}")
        if t.args.get("db") or t.args.get("catalog"):
            raise Rejected("qualified table names are not allowed")
    for f in tree.find_all(exp.Func):
        if isinstance(f, (exp.Cast, exp.TryCast)):
            continue
        name = f.sql_name().lower() if not isinstance(f, exp.Anonymous) else f.name.lower()
        if name in FORBIDDEN_NAMES:
            raise Rejected(f"function {name} is forbidden")
        if name not in ALLOWED_FUNCS and not isinstance(f, SKIP):
            raise Rejected(f"function {name} is not in the allow-list")
    for c in tree.find_all(exp.CurrentDate, exp.CurrentTimestamp, exp.CurrentTime):
        raise Rejected("current_date / now are forbidden: the reference date is the last date of the database")
    try:
        qualify(tree.copy(), schema=SCHEMA, dialect="duckdb", validate_qualify_columns=True,
                quote_identifiers=False, identify=False)
    except sqlglot.errors.OptimizeError as e:
        raise Rejected(f"{e}; available columns: " + "; ".join(f"{v}({', '.join(c)})" for v, c in SCHEMA.items()))
    if not tree.args.get("limit") and isinstance(tree, exp.Select):
        tree = tree.limit(LIMIT)
    return tree.sql(dialect="duckdb")
