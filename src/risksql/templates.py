"""Deterministic templates for the frequent question shapes. Each returns SQL or None (None = not my question).
Entities (book, trader, desk, month, series, threshold) are extracted with regexes and a fuzzy match on names."""
import calendar
import re
import unicodedata
import dateparser
from rapidfuzz import process, fuzz

BOOKS = ["TAUX_EUR", "TAUX_USD", "FX_SPOT"]
TRADERS = ["Martin", "Bernard", "Dubois", "Thomas", "Robert", "Petit"]
DESKS = ["Taux", "Change"]
SERIES = ["EUR_2Y", "EUR_5Y", "EUR_10Y", "USD_2Y", "USD_5Y", "USD_10Y", "EURUSD"]
LAST = "(SELECT max(date) FROM {t})"


def _fold(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _pick(text, names, key=lambda n: n):
    """Exact word hit first, then fuzzy (typos, missing underscore) at 85."""
    toks = re.findall(r"[a-z0-9_]+", _fold(text))
    low = {_fold(key(n)): n for n in names}
    for t in toks:
        if t in low:
            return low[t]
    for t in toks:
        m = process.extractOne(t, list(low), scorer=fuzz.ratio, score_cutoff=85)
        if m:
            return low[m[0]]
    return None


def book(q):
    t = _fold(q).replace(" ", "_")
    for b in BOOKS:
        if b.lower() in t:
            return b
    return _pick(q, BOOKS)


def trader(q):
    return _pick(q, TRADERS)


def desk(q):
    m = re.search(r"desk\s+(\w+)", _fold(q))
    return _pick(m.group(1), DESKS) if m else None


def month(q):
    """'septembre 2026' -> ('2026-09-01', '2026-09-30')."""
    m = re.search(r"(?:en|sur|de|d')\s*(?:le mois d'|mois d')?\s*([a-zéû]+)\s+(\d{4})", q.lower())
    d = dateparser.parse(f"1 {m.group(1)} {m.group(2)}", languages=["fr"]) if m else None
    if not d:
        return None
    return d.strftime("%Y-%m-01"), d.strftime(f"%Y-%m-{calendar.monthrange(d.year, d.month)[1]}")


def day(q):
    m = re.search(r"le (\d{1,2}|1er) ([a-zéû]+) (\d{4})", q.lower())
    d = dateparser.parse(f"{m.group(1).replace('er', '')} {m.group(2)} {m.group(3)}", languages=["fr"]) if m else None
    return d.strftime("%Y-%m-%d") if d else None


def series(q):
    f = _fold(q).replace("-", " ")
    if "eurusd" in f.replace("/", ""):
        return "EURUSD"
    m = re.search(r"taux\s+(eur|usd)\s+(\d+)\s*y", f)
    return f"{m.group(1).upper()}_{m.group(2)}Y" if m else None


def has(q, *words):
    f = _fold(q)
    return all(w in f for w in words)


def t_var_es_book_last(q):  # VaR / ES du book X au dernier jour
    f = _fold(q)
    b = book(q)
    if not b or "dernier jour" not in f or "utilisation" in f or "limite" in f or not re.search(r"\b(var|es)\b", f):
        return None
    col = "es975_1j_eur" if re.search(r"\bes\b", f) else "var99_1j_eur"
    return f"SELECT {col} FROM v_risque_book WHERE book='{b}' AND date={LAST.format(t='v_risque_book')}"


def t_var_es_book_day(q):  # VaR / ES du book X le <date>
    f = _fold(q)
    b, d = book(q), day(q)
    if not (b and d) or "limite" in f or not re.search(r"\b(var|es)\b", f):
        return None
    col = "es975_1j_eur" if re.search(r"\bes\b", f) else "var99_1j_eur"
    return f"SELECT {col} FROM v_risque_book WHERE book='{b}' AND date=DATE '{d}'"


def t_pnl_total_entity(q):  # P&L total du desk/book/trader X [en mois annee | au dernier jour]
    f = _fold(q)
    if not re.search(r"p&l total (du|de|des)|p&l (du|des) \w+ (le|en)", f) or "plus" in f or " par " in f or "ecart" in f or "part " in f or "cumul" in f:
        return None
    ent = ("desk", desk(q)) if desk(q) else (("book", book(q)) if book(q) else (("trader", trader(q)) if trader(q) else None))
    if not ent or not ent[1]:
        return None
    where = f"{ent[0]}='{ent[1]}'"
    if m := month(q):
        where += f" AND date BETWEEN DATE '{m[0]}' AND DATE '{m[1]}'"
    elif "dernier jour" in f or "plus recent" in f:
        where += f" AND date={LAST.format(t='v_pnl')}"
    return f"SELECT sum(pnl_eur) FROM v_pnl WHERE {where}"


def t_pnl_by(q):  # P&L total par book/desk/trader
    f = _fold(q)
    m = re.search(r"p&l total par (book|desk|trader)", f)
    return f"SELECT {m.group(1)}, sum(pnl_eur) FROM v_pnl GROUP BY {m.group(1)}" if m else None


def t_days_over_limit(q):  # Combien de jours le book X a-t-il depasse N % de sa limite
    f = _fold(q)
    m = re.search(r"(\d+)\s*%", f)
    b = book(q)
    if not (m and b and "combien de jours" in f and "limite" in f):
        return None
    return f"SELECT count(*) FROM v_limites WHERE book='{b}' AND utilisation_pct>{m.group(1)}"


def t_var_breaches(q):  # Combien de depassements de VaR [par book | du book X | au total]
    f = _fold(q)
    if "combien de depassements de var" not in f:
        return None
    if " par book" in f:
        return "SELECT book, count(*) FROM v_risque_book WHERE depassement_var GROUP BY book"
    if b := book(q):
        return f"SELECT count(*) FROM v_risque_book WHERE book='{b}' AND depassement_var"
    return "SELECT count(*) FROM v_risque_book WHERE depassement_var" if "total" in f else None


def t_avg_by_book(q):  # VaR / ES moyen(ne) par book, VaR maximale par book
    f = _fold(q)
    m = re.match(r"(var|es)\s+(moyenne?|maximale)\s+par book", f)
    if not m:
        return None
    col = "es975_1j_eur" if m.group(1) == "es" else "var99_1j_eur"
    fn = "max" if m.group(2) == "maximale" else "avg"
    return f"SELECT book, {fn}({col}) FROM v_risque_book GROUP BY book"


def t_rate_last(q):  # taux X au dernier jour
    s = series(q)
    if not s or "dernier jour" not in _fold(q) or "pente" in _fold(q) or "evolution" in _fold(q):
        return None
    return f"SELECT valeur FROM v_marche WHERE serie='{s}' AND date={LAST.format(t='v_marche')}"


def t_rate_day(q):  # valeur de l'EURUSD / du taux X le <date>
    s, d = series(q), day(q)
    return f"SELECT valeur FROM v_marche WHERE serie='{s}' AND date=DATE '{d}'" if s and d and "variation" not in _fold(q) else None


def t_limit_usage_last(q):  # utilisation de la limite du book X au dernier jour
    f = _fold(q)
    b = book(q)
    if not (b and "utilisation" in f and "limite" in f and "dernier jour" in f):
        return None
    return f"SELECT utilisation_pct FROM v_limites WHERE book='{b}' AND date={LAST.format(t='v_limites')}"


def t_positions_trader(q):  # Combien de positions a le trader X au dernier jour
    f = _fold(q)
    t = trader(q)
    if not (t and "combien de positions a le trader" in f and "dernier jour" in f):
        return None
    return f"SELECT count(DISTINCT position_id) FROM v_positions WHERE trader='{t}' AND date={LAST.format(t='v_positions')}"


TEMPLATES = [t_var_es_book_last, t_var_es_book_day, t_pnl_total_entity, t_pnl_by, t_days_over_limit, t_var_breaches,
             t_avg_by_book, t_rate_last, t_rate_day, t_limit_usage_last, t_positions_trader]


def match(question):
    """First template that fires -> (name, sql); else None."""
    for t in TEMPLATES:
        sql = t(question)
        if sql:
            return t.__name__, sql
    return None
