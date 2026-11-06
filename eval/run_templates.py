"""Score the templates alone (no LLM). Unmatched question = declared failure (the router would send it to the LLM).
Usage: python eval/run_templates.py dev|test"""
import json
import sys
sys.path.insert(0, "src")
from risksql import executor, evaluate as ev, templates

split = sys.argv[1]
con = executor.connect("data/risk.duckdb")
res = []
for it in ev.load(split):
    _, ref = executor.run(con, it["reference_sql"])
    m = templates.match(it["question"])
    got, sql = None, None
    if m:
        sql = m[1]
        try:
            _, got = executor.run(con, sql)
        except Exception as e:
            got = None
    res.append(dict(id=it["id"], template=m[0] if m else None, sql=sql, outcome=ev.outcome(ref, got, it["ordered"]), fired=bool(m)))
fired = [r for r in res if r["fired"]]
print(split, "coverage", f"{len(fired)}/{len(res)}", "| correct among fired",
      f"{sum(r['outcome'] == 'correct' for r in fired)}/{len(fired)}",
      "| silent wrong", [r["id"] for r in fired if r["outcome"] == "silent_wrong"])
json.dump(res, open(f"eval/templates_{split}.json", "w"), indent=1)
print(ev.summarize([r["outcome"] for r in res]))
