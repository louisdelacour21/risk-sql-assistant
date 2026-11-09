"""Template first (fast, deterministic), else LLM. Everything goes through the guard and the read-only executor."""
import json
from pathlib import Path
from . import executor, templates, llm

REPLAY = Path(__file__).parent / "replay.json"  # question -> recorded SQL, produced by eval/make_replay.py


def answer(con, question, mode="live", client=None):
    """Returns dict(route, sql, df, hypotheses, error). mode: 'live' (Ollama) or 'replay' (recorded SQL, still guarded)."""
    out = dict(route=None, sql=None, df=None, hypotheses=[], graphique=None, error=None)
    if m := templates.match(question):
        out.update(route=f"template:{m[0]}", sql=m[1])
    elif mode == "replay":
        rec = json.loads(REPLAY.read_text(encoding="utf8")).get(question.strip())
        if not rec:
            out.update(route="replay", error="Question not in the recorded set (replay mode cannot call the model).")
            return out
        out.update(route="replay", sql=rec["sql"], error=rec.get("error"))
        if not rec["sql"]:
            return out
    else:
        r = llm.propose(question, client)
        out.update(route="llm", sql=r["sql"], error=r["error"])
        if r["answer"]:
            out.update(hypotheses=r["answer"].hypotheses, graphique=r["answer"].graphique)
        if not r["sql"]:
            return out
    try:
        out["sql"], out["df"] = executor.run(con, out["sql"])
        out["error"] = None
        if out["df"].isna().all(axis=None):  # an aggregate over no rows: say so instead of showing a row of NULLs
            out.update(df=None, error="No data matches this question (the trader, book or period asked for may not exist in this database).")
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out
