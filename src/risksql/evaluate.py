"""Scoring: compare result sets, then report accuracy with Wilson intervals and a paired McNemar test."""
import itertools
import json
import math
from collections import Counter
import pandas as pd
from statsmodels.stats.contingency_tables import mcnemar
from statsmodels.stats.proportion import proportion_confint

SIG = 6  # significant digits kept when comparing numbers


def _cell(v):
    if v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NaT:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(f"{float(v):.{SIG - 1}e}")
    return str(v)


def _rows(df, perm):
    return [tuple(_cell(r[i]) for i in perm) for r in df.itertuples(index=False, name=None)]


def same(ref, got, ordered=False):
    """True if got equals ref up to column order (and row order unless ordered). NULLs are compared as values."""
    if ref.shape != got.shape:
        return False
    target = _rows(ref, range(ref.shape[1]))
    for perm in itertools.permutations(range(got.shape[1])):
        rows = _rows(got, perm)
        if (rows == target) if ordered else (Counter(rows) == Counter(target)):
            return True
    return False


def same_lenient(ref, got, ordered=False):
    """Secondary metric: the reference columns appear among the returned columns (extra columns allowed)."""
    if got.shape[0] != ref.shape[0] or ref.shape[1] > got.shape[1]:
        return False
    return any(same(ref, got.iloc[:, list(c)], ordered) for c in itertools.permutations(range(got.shape[1]), ref.shape[1]))


def outcome(ref, got, ordered=False):
    """'correct', 'silent_wrong' (ran, wrong answer) or 'declared' (refused / rejected / error: got is None)."""
    if got is None:
        return "declared"
    return "correct" if same(ref, got, ordered) else "silent_wrong"


def wilson(k, n):
    lo, hi = proportion_confint(k, n, method="wilson") if n else (float("nan"),) * 2
    return k / n if n else float("nan"), lo, hi


def summarize(outcomes):
    n = len(outcomes)
    c = Counter(outcomes)
    return {name: dict(zip(("rate", "lo", "hi"), wilson(c[key], n)), k=c[key], n=n)
            for name, key in (("execution_accuracy", "correct"), ("silent_wrong", "silent_wrong"), ("declared_failure", "declared"))}


def mcnemar_p(a, b):
    """Exact McNemar on paired 'correct' flags; a and b are equal-length lists of outcomes."""
    ca, cb = [x == "correct" for x in a], [x == "correct" for x in b]
    t = [[sum(x and y for x, y in zip(ca, cb)), sum(x and not y for x, y in zip(ca, cb))],
         [sum(not x and y for x, y in zip(ca, cb)), sum(not x and not y for x, y in zip(ca, cb))]]
    return mcnemar(t, exact=True).pvalue, t[0][1], t[1][0]  # p, only-a-correct, only-b-correct


def load(split):
    return json.load(open(f"eval/{split}.json", encoding="utf8"))
