"""Streamlit front end. Live mode needs a local Ollama; replay mode (used online) replays recorded SQL through the real guard."""
import json
import sys
from pathlib import Path
import pandas as pd
import streamlit as st

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))
from risksql import executor, guard, router  # noqa: E402

st.set_page_config(page_title="Risk SQL assistant", layout="wide")
st.title("Risk SQL assistant")
st.caption("Ask a market-risk database in French. A local 4B model proposes SQL; a guard and a read-only connection decide what runs. "
           "Synthetic data: 60 positions, 250 business days, as of 2026-10-30.")


@st.cache_resource
def connection():
    return executor.connect(str(ROOT / "data" / "risk.duckdb"))


@st.cache_data
def scores():
    p = ROOT / "eval" / "scores.json"
    return json.loads(p.read_text(encoding="utf8")) if p.exists() else {}


@st.cache_data
def safety():
    p = ROOT / "eval" / "safety_results.json"
    return json.loads(p.read_text(encoding="utf8")) if p.exists() else []


def ollama_up():
    try:
        import ollama
        ollama.Client(timeout=2).list()
        return True
    except Exception:
        return False


live = ollama_up()
mode = st.sidebar.radio("Mode", ["live", "replay"] if live else ["replay"],
                        help="Live calls the local model. Replay re-runs the SQL recorded during the evaluation, through the same guard.")
if not live:
    st.sidebar.info("No local model here: replay mode. The 160 evaluation questions and the template questions work; free text does not.")
st.sidebar.markdown("**Reading the answers.** Always read the SQL. The guard prevents damage, not wrong answers.")

ask, evaluation, playground, about = st.tabs(["Ask", "Evaluation", "SQL guard playground", "How it works"])

EXAMPLES = ["Quelle est la VaR du book FX_SPOT au dernier jour ?", "P&L total par desk ?", "Combien de dépassements de VaR par book ?",
            "Évolution de la VaR du book FX_SPOT sur les 60 derniers jours", "Taux USD 10Y moyen sur août 2026 ?",
            "Quels sont les 3 books avec la plus grande VaR au dernier jour ?", "P&L cumulé du desk Taux en octobre 2026",
            "Quel est le cours de l'action Apple ?"]

with ask:
    if "q" not in st.session_state:
        st.session_state.q = ""
    cols = st.columns(4)
    for i, ex in enumerate(EXAMPLES):
        if cols[i % 4].button(ex, key=f"ex{i}", use_container_width=True):
            st.session_state.q = ex
    question = st.text_input("Question", key="q", placeholder="Ex. : Quel est le P&L du trader Martin en septembre 2026 ?")
    if question:
        with st.spinner("Thinking..." if mode == "live" else "Running..."):
            r = router.answer(connection(), question, mode)
        left, right = st.columns([3, 1])
        left.markdown(f"**Route:** `{r['route']}`" + ("  (deterministic, no model)" if str(r["route"]).startswith("template") else ""))
        if r["error"]:
            st.warning(f"No answer: {r['error']}")
        for h in r["hypotheses"]:
            st.info(f"Assumption: {h}")
        if r["sql"]:
            st.code(r["sql"], language="sql")
            st.caption("This is the SQL after the guard (single SELECT, catalogue views only, LIMIT forced).")
        if r["df"] is not None:
            df = r["df"]
            st.dataframe(df, use_container_width=True, hide_index=True)
            if df.shape[1] == 2 and len(df) > 2 and str(df.dtypes.iloc[1]).startswith(("float", "int")):
                c0 = df.columns[0]
                (st.line_chart if ("date" in c0 or "mois" in c0) else st.bar_chart)(df.set_index(c0))

with evaluation:
    S = scores()
    if not S:
        st.info("Run `python eval/score.py` to generate the evaluation numbers.")
    else:
        st.markdown("Question sets written by the author; reference SQL checked by running it. Scoring compares result sets "
                    "(6 significant digits, NULLs as values, column order ignored). Intervals are Wilson 95 %. "
                    "**Strict** is the headline; **lenient** also accepts extra columns.")
        names = {"v1": "v1 · first prompt", "v2": "v2 · retrieval prompt", "v3": "v3 · rules from v2 failures"}
        rows = []
        for k, v in S.items():
            a, l = v["strict"]["execution_accuracy"], v["lenient"]["execution_accuracy"]
            rows.append({"Set": names.get(k, k), "n": v["n"], "Correct (strict)": f"{a['k']} ({a['rate']:.0%}, {a['lo']:.0%}-{a['hi']:.0%})",
                         "Correct (lenient)": f"{l['k']} ({l['rate']:.0%})", "Wrong, not flagged": v["strict"]["silent_wrong"]["k"],
                         "Declined": v["strict"]["declared_failure"]["k"], "Latency p50 / p95 (s)": f"{v['p50_s']} / {v['p95_s']}"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption("v1 was the first run and is burned for tuning; each later set was written after the previous one was seen. "
                   "Only the latest set was run on a frozen prompt it had never influenced.")
        sf = safety()
        if sf:
            sc = st.columns(2)
            for c, k, t in ((sc[0], "out_of_scope", "Out-of-scope questions declined"), (sc[1], "hostile", "Hostile requests stopped")):
                s = [x for x in sf if x["kind"] == k]
                c.metric(t, f"{sum(x['passed'] for x in s)} / {len(s)}")
        pick = st.selectbox("Show the failures of", list(S), index=len(S) - 1)
        fails = S[pick]["failures"]
        st.markdown(f"**{len(fails)} questions not answered correctly in {names.get(pick, pick)}**")
        for f in fails:
            with st.expander(f"{f['id']} · {f['outcome']} · {f['question']}"):
                st.markdown("Reference SQL"); st.code(f["reference_sql"], language="sql")
                st.markdown("Model SQL"); st.code(f["got_sql"] or f["error"] or "(none)", language="sql")

with playground:
    st.markdown("Paste any SQL. The guard accepts or rejects it, exactly as it does for model output; accepted queries run on the read-only connection.")
    samples = {"": "", "Legitimate": "SELECT book, avg(var99_1j_eur) FROM v_risque_book GROUP BY book",
               "Stacked statement": "SELECT 1; DROP TABLE v_pnl", "Read a file": "SELECT * FROM read_csv('C:/Windows/win.ini')",
               "Attach a database": "ATTACH 'other.db' AS x", "Unknown column": "SELECT salaire FROM v_positions",
               "Environment": "SELECT getenv('PATH')", "Cartesian product": "SELECT count(*) FROM v_pnl a, v_pnl b, v_pnl c"}
    pick = st.selectbox("Samples", list(samples))
    sql = st.text_area("SQL", value=samples[pick], height=120)
    if sql.strip():
        try:
            safe = guard.check(sql)
            st.success("Accepted by the guard")
            st.code(safe, language="sql")
            try:
                _, df = executor.run(connection(), safe)
                st.dataframe(df.head(50), use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(f"Stopped by the read-only executor: {type(e).__name__}: {str(e)[:200]}")
        except guard.Rejected as e:
            st.error(f"Rejected by the guard: {e}")

with about:
    st.markdown("""
**Pipeline.** 1) A deterministic template answers the frequent shapes with no model. 2) Otherwise the model receives the catalogue and the six
most similar verified examples, and answers in JSON `{sql, graphique, hypotheses, refus}`; one repair attempt with the exact error.
3) The SQL guard (sqlglot) allows one SELECT/UNION/WITH, catalogue views only, an allow-list of functions, resolved columns, forced LIMIT.
4) DuckDB runs it read-only, external access disabled, configuration locked, 5 s timeout.

**What the model never does.** It cannot run anything, see the files, or write: each of these is blocked by code, and tested on 40 hostile and 20 legitimate queries plus the safety battery.

**Limits.** Synthetic data. Question sets are written by the author. A small local model on CPU takes 40-70 s per question. Some wrong answers look plausible,
which is why the SQL is always shown.

Source and method: see the README on GitHub.
""")
