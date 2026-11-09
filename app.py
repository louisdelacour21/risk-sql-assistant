"""Streamlit front end. Live mode needs a local Ollama; replay mode (used online) replays recorded SQL through the real guard."""
import json
import sys
from pathlib import Path
import pandas as pd
import streamlit as st
import yaml

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))
from risksql import executor, guard, router  # noqa: E402

st.set_page_config(page_title="Risk SQL assistant", layout="wide")
st.markdown("""<style>
.block-container{padding-top:2.4rem;max-width:1180px}
h1{font-weight:750;letter-spacing:-.025em;padding-bottom:.1rem}
.tagline{font-size:1.08rem;color:#3d5654;margin:0 0 .35rem}
.chips span{display:inline-block;font-size:.8rem;color:#0f5e57;background:#e3f1ef;border-radius:999px;padding:.12rem .7rem;margin:0 .35rem .35rem 0}
.stTabs [data-baseweb=tab]{font-size:1rem;padding:.65rem 1.1rem}
[data-testid=stMetricValue]{font-weight:700}
footer{visibility:hidden}
</style>""", unsafe_allow_html=True)
st.title("Risk SQL assistant")
st.markdown('<p class="tagline">Ask a market-risk database a question in French. A small local model writes the SQL; a guard and a read-only '
            'connection decide what actually runs.</p>'
            '<div class="chips"><span>4B model, no API</span><span>SQL guard</span><span>Read-only DuckDB</span>'
            '<span>Frozen test sets</span><span>Failures published</span><span>Synthetic data</span></div>', unsafe_allow_html=True)


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


S0, SF0 = scores(), safety()
if S0 and SF0:
    last = list(S0.values())[-1]
    a, l = last["strict"]["execution_accuracy"], last["lenient"]["execution_accuracy"]
    hostile = [x for x in SF0 if x["kind"] == "hostile"]
    m = st.columns(4)
    m[0].metric("Correct on 60 unseen questions", f"{a['rate']:.0%}", f"95% CI {a['lo']:.0%}-{a['hi']:.0%}", delta_color="off", border=True)
    m[1].metric("Tolerating extra columns", f"{l['rate']:.0%}", f"{last['strict']['silent_wrong']['k']} wrong answers not flagged", delta_color="off", border=True)
    m[2].metric("Hostile requests stopped", f"{sum(x['passed'] for x in hostile)} / {len(hostile)}", "drop, read file, ATTACH...", delta_color="off", border=True)
    m[3].metric("Median answer time", f"{last['p50_s']:.0f} s", "4B model, CPU, no API", delta_color="off", border=True)

live = ollama_up()
mode = st.sidebar.radio("Mode", ["live", "replay"] if live else ["replay"],
                        help="Live calls the local model. Replay re-runs the SQL recorded during the evaluation, through the same guard.")
if not live:
    st.sidebar.info("No local model here: replay mode. The 260 recorded evaluation questions and the template questions work; free text does not.")
st.sidebar.markdown("**Reading the answers.** Always read the SQL. The guard prevents damage, not wrong answers.")

ask, evaluation, data, playground, about = st.tabs(["Ask", "Evaluation", "The data", "SQL guard playground", "How it works"])

QS = json.loads((ROOT / "src" / "risksql" / "questions.json").read_text(encoding="utf8"))
BY_Q = {x["question"]: x for x in QS}
CATS = list(dict.fromkeys(x["category"] for x in QS))
STATUS_LABEL = {"all": "All", "correct": "Answered correctly", "wrong": "Answered wrongly (kept visible)"}


def pick(key):
    if st.session_state[key]:
        st.session_state.q = st.session_state[key]


with ask:
    st.session_state.setdefault("q", "")
    st.markdown("**1. Pick a topic**")
    cat = st.radio("Topic", CATS, horizontal=True, label_visibility="collapsed")
    items = [x for x in QS if x["category"] == cat]
    step = max(1, len(items) // 6)
    st.markdown("**2. Click a question**")
    st.caption("The assistant is asked in French; the button shows an English gloss.")
    cols = st.columns(3)
    for i, x in enumerate(items[::step][:6]):
        if cols[i % 3].button(x["en"], key=f"f{cat}{i}", use_container_width=True):
            st.session_state.q = x["question"]
    with st.expander(f"Browse all {len(items)} recorded questions in this topic"):
        flt = "all"
        if items[0]["status"] in ("correct", "wrong"):
            flt = st.radio("Show", list(STATUS_LABEL), format_func=STATUS_LABEL.get, horizontal=True, key=f"flt{cat}")
        shown = [x for x in items if flt == "all" or x["status"] == flt]
        key = f"sel{cat}{flt}"
        st.selectbox(f"{len(shown)} questions (type to search)", [""] + [x["question"] for x in shown], key=key, on_change=pick, args=(key,),
                     format_func=lambda s: "Select a question..." if not s else BY_Q[s]["en"])
    st.markdown("**3. Or type your own**" + ("" if mode == "live" else " (live mode only: it needs the local model)"))
    question = st.text_input("Question", key="q", placeholder="Ex. : Quel est le P&L du trader Martin en septembre 2026 ?", label_visibility="collapsed")
    if question:
        info = BY_Q.get(question)
        with st.container(border=True):
            if info:
                st.caption(f"In English: {info['en']}")
                if info["status"] == "wrong":
                    st.warning("In the evaluation the model got this one wrong (it includes runs on earlier prompts, and answers with extra columns that strict scoring rejects). Compare the SQL with the question.")
                elif info["status"] == "missed":
                    st.warning("A safety miss: this request should have been declined and was not. See the README.")
            with st.spinner("Thinking..." if mode == "live" else "Running..."):
                r = router.answer(connection(), question, mode)
            st.markdown(f"**Route:** `{r['route']}`" + ("  (deterministic, no model)" if str(r["route"]).startswith("template") else ""))
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

with data:
    cat = yaml.safe_load((ROOT / "src" / "risksql" / "catalog.yaml").read_text(encoding="utf8"))
    st.markdown(f"Five read-only views, synthetic, as of **{cat['reference_date']}**. This catalogue is all the model sees, and all the guard allows.")
    for name, v in cat["views"].items():
        with st.expander(f"{name} · {v['description']}"):
            st.dataframe(pd.DataFrame([{"column": c, "type": t, "meaning": d} for c, (t, d) in v["columns"].items()]), hide_index=True, use_container_width=True)
            st.caption("Last 5 rows")
            st.dataframe(connection().execute(f"SELECT * FROM {name} ORDER BY date DESC LIMIT 5").df(), hide_index=True, use_container_width=True)

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
