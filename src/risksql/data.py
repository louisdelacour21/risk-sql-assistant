"""Frozen synthetic risk database: 60 positions over 250 business days, 2 desks, 3 books, 6 traders.
P&L is first order (DV01 x rate move, FX delta x spot return); VaR 99% / ES 97.5% are historical on 250 scenarios.
Everything is generated from a seed, so `python -m risksql.data` rebuilds the same file."""
import sys
import duckdb
import numpy as np
import pandas as pd

AS_OF = "2026-10-30"
N_DAYS, N_HIST = 250, 250
PILLARS = {"2Y": 2, "5Y": 5, "10Y": 10}
BOOKS = {  # book -> (desk, currency, traders)
    "TAUX_EUR": ("Taux", "EUR", ["Martin", "Bernard"]),
    "TAUX_USD": ("Taux", "USD", ["Dubois", "Thomas"]),
    "FX_SPOT": ("Change", "USD", ["Robert", "Petit"]),
}


def _ou(rng, n, x0, kappa, sig):
    x = np.empty(n)
    x[0] = x0
    for t in range(1, n):
        x[t] = x[t - 1] + kappa * (x0 - x[t - 1]) + rng.normal(0, sig)
    return x


def _market(rng, dates):
    """Mean-reverting synthetic curves (rates in %), so levels stay plausible over 500 days."""
    n = len(dates)
    out = {}
    for ccy, base in (("EUR", [2.1, 2.4, 2.7]), ("USD", [4.0, 4.1, 4.3])):
        common = _ou(rng, n, 0.0, 0.01, 0.035)
        for (p, _), b in zip(PILLARS.items(), base):
            out[f"{ccy}_{p}"] = b + common + _ou(rng, n, 0.0, 0.02, 0.012)
    out["EURUSD"] = np.exp(_ou(rng, n, np.log(1.08), 0.01, 0.0045))
    return pd.DataFrame(out, index=dates)


def _var_es(pnl):
    q = np.sort(pnl)
    k = max(int(np.ceil(0.025 * len(q))), 1)
    return -np.quantile(pnl, 0.01), -q[:k].mean()


def build(path="data/risk.duckdb", seed=7):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=AS_OF, periods=N_DAYS + N_HIST + 1)
    mk = _market(rng, dates)
    d_bp = mk.drop(columns="EURUSD").diff() * 100
    fx_ret = mk["EURUSD"].pct_change()
    # 60 positions: 20 per book, one pillar / one currency each
    pos = []
    for book, (desk, ccy, traders) in BOOKS.items():
        for i in range(20):
            pil = list(PILLARS)[i % 3]
            notional = float(rng.choice([5, 10, 20, 40])) * 1e6 * rng.choice([-1, 1])
            pos.append(dict(position_id=f"{book}-{i + 1:02d}", desk=desk, book=book, trader=traders[i % 2],
                            instrument=f"IRS {pil}" if desk == "Taux" else "EURUSD spot", devise=ccy, pillar=pil,
                            base=notional))
    days = dates[-N_DAYS:]
    rows = []
    for p in pos:
        scale = np.exp(rng.normal(0, 0.004, len(days)).cumsum())
        for d, s in zip(days, scale):
            nom = p["base"] * s
            if p["desk"] == "Taux":
                dv01, dfx = nom * PILLARS[p["pillar"]] * 1e-4 * 0.9, 0.0  # DV01 EUR ~ notional x duration x 1bp
            else:
                dv01, dfx = 0.0, nom
            rows.append((d, p["desk"], p["book"], p["trader"], p["position_id"], p["instrument"], p["devise"],
                         round(nom, 2), round(dv01, 2), round(dfx, 2), p["pillar"]))
    P = pd.DataFrame(rows, columns=["date", "desk", "book", "trader", "position_id", "instrument", "devise",
                                    "notionnel", "dv01_eur", "delta_fx_eur", "pillar"])
    risk_rows = []
    P["pnl_eur"] = [
        round(-r.dv01_eur * (d_bp.loc[r.date, f"{r.devise}_{r.pillar}"] if r.desk == "Taux" else 0.0)
              + r.delta_fx_eur * fx_ret.loc[r.date], 2) for r in P.itertuples(index=False)]
    for (d, book), g in P.groupby(["date", "book"]):
        loc = dates.get_loc(d)
        win = dates[loc - N_HIST:loc]  # 250 scenarios strictly before d
        scen = np.zeros(N_HIST)
        for r in g.itertuples(index=False):
            if r.desk == "Taux":
                scen += -r.dv01_eur * d_bp.loc[win, f"{r.devise}_{r.pillar}"].to_numpy()
            else:
                scen += r.delta_fx_eur * fx_ret.loc[win].to_numpy()
        var, es = _var_es(scen)
        risk_rows.append((d, book, round(var, 2), round(es, 2), round(g.pnl_eur.sum(), 2)))
    R = pd.DataFrame(risk_rows, columns=["date", "book", "var99_1j_eur", "es975_1j_eur", "pnl_eur"])
    R["depassement_var"] = R.pnl_eur < -R.var99_1j_eur
    lim = (R.groupby("book").var99_1j_eur.median() * 1.3).round(-3)
    L = R[["date", "book", "var99_1j_eur"]].copy()
    L["limite_eur"] = L.book.map(lim)
    L["utilisation_pct"] = (100 * L.var99_1j_eur / L.limite_eur).round(2)
    M = mk.loc[days].reset_index(names="date").melt("date", var_name="serie", value_name="valeur")
    meta = {s: (f"{s[:3]} {s[4:]}" if s != "EURUSD" else "EUR/USD", "pct" if s != "EURUSD" else "USD par EUR")
            for s in M.serie.unique()}
    M["libelle"] = M.serie.map(lambda s: meta[s][0])
    M["unite"] = M.serie.map(lambda s: meta[s][1])
    M["valeur"] = M.valeur.round(4)
    M = M[["date", "serie", "libelle", "unite", "valeur"]]
    P = P.drop(columns="pillar")
    con = duckdb.connect(path)
    for name, df in (("positions", P), ("risque_book", R), ("limites", L), ("marche", M)):
        con.execute(f"CREATE OR REPLACE TABLE t_{name} AS SELECT * FROM df")
    con.execute("CREATE OR REPLACE VIEW v_positions AS SELECT date,desk,book,trader,position_id,instrument,devise,notionnel,dv01_eur,delta_fx_eur FROM t_positions")
    con.execute("CREATE OR REPLACE VIEW v_pnl AS SELECT date,desk,book,trader,pnl_eur FROM t_positions")
    con.execute("CREATE OR REPLACE VIEW v_risque_book AS SELECT date,book,var99_1j_eur,es975_1j_eur,pnl_eur,depassement_var FROM t_risque_book")
    con.execute("CREATE OR REPLACE VIEW v_limites AS SELECT date,book,var99_1j_eur,limite_eur,utilisation_pct FROM t_limites")
    con.execute("CREATE OR REPLACE VIEW v_marche AS SELECT date,serie,libelle,unite,valeur FROM t_marche")
    con.close()
    return path


if __name__ == "__main__":
    print("built", build(*(sys.argv[1:2] or [])))
