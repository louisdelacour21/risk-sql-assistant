"""Build src/risksql/questions.json for the demo: every recorded question with a category, an English gloss and how it was answered.
Order of eval/questions_en.txt: test, dev, test2, test3, then the 20 out-of-scope and 20 hostile safety questions."""
import json
import re
import sys
sys.path.insert(0, "src")
sys.path.insert(0, "eval")
from risksql import evaluate as ev, executor, router
import safety

CATEGORY = {"risque_book": "VaR, ES and exceptions", "pnl": "P&L", "positions": "Positions and sensitivities",
            "limites": "Limits", "marche": "Market data"}
con = executor.connect("data/risk.duckdb")
en = [l.strip() for l in open("eval/questions_en.txt", encoding="utf8") if l.strip()]
fr = [dict(x, source=s) for s in ("test", "dev", "test2", "test3") for x in ev.load(s)] + \
     [dict(question=i["question"], source="safety", kind=i["kind"], id=i["id"]) for i in safety.ITEMS]
assert len(en) == len(fr), (len(en), len(fr))

key = lambda s: sorted(re.findall(r"TAUX_EUR|TAUX_USD|FX_SPOT|\d+", s.replace(",", "").replace("1er", "1")))
for f, e in zip(fr, en):  # catches a shifted line in the translation file
    assert key(f["question"]) == key(e) or f["source"] == "safety", (f["question"], e)

missed = {r["id"] for r in json.load(open("eval/safety_results.json", encoding="utf8")) if not r["passed"]}
out = []
for f, e in zip(fr, en):
    if f["source"] == "safety":
        cat = "Out of scope (should be declined)" if f["kind"] == "out_of_scope" else "Hostile requests (should be blocked)"
        status = "missed" if f["id"] in missed else "stopped"
    else:
        views = re.findall(r"\bv_(\w+)", f["reference_sql"])
        cat = CATEGORY[views[0]]
        r = router.answer(con, f["question"], "replay")
        _, ref = executor.run(con, f["reference_sql"])
        status = ev.outcome(ref, r["df"], f["ordered"])
        status = "correct" if status == "correct" else "wrong"
    out.append(dict(question=f["question"], en=e, category=cat, status=status, template=router.templates.match(f["question"]) is not None))
json.dump(out, open("src/risksql/questions.json", "w", encoding="utf8"), ensure_ascii=False, indent=1)
import collections
print(len(out), collections.Counter((o["category"], o["status"]) for o in out))
