"""Streamlit front end. Live mode needs a local Ollama; replay mode (used online) replays recorded SQL through the real guard."""
import sys
from pathlib import Path
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "src"))
from risksql import executor, router, templates  # noqa: E402

st.set_page_config(page_title="Risk SQL assistant", layout="wide")
st.title("Risk SQL assistant")
st.caption("Ask in French about a synthetic risk database (60 positions, 250 days, as of 2026-10-30). "
           "Every query is checked by a SQL guard and run on a read-only connection.")


@st.cache_resource
def connection():
    return executor.connect(str(Path(__file__).parent / "data" / "risk.duckdb"))


def ollama_up():
    try:
        import ollama
        ollama.Client(timeout=2).list()
        return True
    except Exception:
        return False


live = ollama_up()
mode = st.sidebar.radio("Mode", ["live", "replay"] if live else ["replay"], help="Replay uses recorded SQL for the evaluation questions; the model is not called.")
if not live:
    st.sidebar.info("No local model here: replay mode. Templates still run live.")
examples = ["Quelle est la VaR du book FX_SPOT au dernier jour ?", "P&L total par desk ?", "Combien de dépassements de VaR par book ?",
            "Évolution de la VaR du book FX_SPOT sur les 60 derniers jours", "Taux USD 10Y moyen sur août 2026 ?"]
pick = st.selectbox("Example", [""] + examples)
question = st.text_input("Question", value=pick)
if question:
    with st.spinner("..."):
        r = router.answer(connection(), question, mode)
    st.write(f"Route: `{r['route']}`")
    if r["sql"]:
        st.code(r["sql"], language="sql")
    for h in r["hypotheses"]:
        st.info(f"Assumption: {h}")
    if r["error"]:
        st.warning(f"Declined: {r['error']}")
    elif r["df"] is not None:
        df = r["df"]
        st.dataframe(df, use_container_width=True)
        if df.shape[1] == 2 and len(df) > 2 and str(df.dtypes.iloc[1]).startswith(("float", "int")):
            st.line_chart(df.set_index(df.columns[0])) if "date" in df.columns[0] or "mois" in df.columns[0] else st.bar_chart(df.set_index(df.columns[0]))
