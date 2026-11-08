"""Recomputes every published number offline from the recorded model SQL (no Ollama): strict and lenient scoring per split.
Usage: python eval/score.py   -> prints a table and writes eval/scores.json (read by the Streamlit app)."""
import json
import os
import statistics
import sys
sys.path.insert(0, "src")
from risksql import executor, evaluate as ev

con = executor.connect("data/risk.duckdb")
out = {}
for split, label in (("test", "v1"), ("test2", "v2"), ("test3", "v3")):
    path = f"eval/llm_{split}.json"
    if not os.path.exists(path):
        continue
    items = {it["id"]: it for it in ev.load(split)}
    rec = json.load(open(path, encoding="utf8"))
    strict, lenient, rows = [], [], []
    for r in rec:
        it = items[r["id"]]
        _, ref = executor.run(con, it["reference_sql"])
        got = None
        if r["sql"]:
            try:
                _, got = executor.run(con, r["sql"])
            except Exception:
                got = None
        o = ev.outcome(ref, got, it["ordered"])
        strict.append(o)
        lenient.append("correct" if o == "correct" or (got is not None and ev.same_lenient(ref, got, it["ordered"])) else o)
        if o != "correct":
            rows.append(dict(id=r["id"], question=it["question"], outcome=o, reference_sql=it["reference_sql"], got_sql=r["sql"], error=r["error"]))
    sec = sorted(r["seconds"] for r in rec)
    out[label] = dict(n=len(rec), strict=ev.summarize(strict), lenient=ev.summarize(lenient), failures=rows,
                      p50_s=round(statistics.median(sec), 1), p95_s=round(sec[int(0.95 * (len(sec) - 1))], 1))
    s, l = out[label]["strict"], out[label]["lenient"]
    print(f"{label} n={len(rec)} strict {s['execution_accuracy']['k']}/{len(rec)} lenient {l['execution_accuracy']['k']}/{len(rec)} "
          f"silent_wrong {s['silent_wrong']['k']} declared {s['declared_failure']['k']}")
json.dump(out, open("eval/scores.json", "w", encoding="utf8"), ensure_ascii=False, indent=1)
