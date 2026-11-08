"""Record the SQL the model produced for every evaluation question, so the online demo can replay it (no model there).
Latest run per question wins: test v2 and dev (current prompt) over test v1 (old prompt, kept only for questions not re-asked)."""
import json
import sys
sys.path.insert(0, "src")
from risksql import evaluate as ev

rec = {}
for split in ("test", "dev", "test2", "test3"):  # later splits override earlier ones
    qs = {x["id"]: x["question"] for x in ev.load(split)}
    for r in json.load(open(f"eval/llm_{split}.json", encoding="utf8")):
        rec[qs[r["id"]].strip()] = dict(sql=r["sql"], error=r["error"])
import os
if os.path.exists("eval/safety_results.json"):  # safety questions replay too (declined or stopped by the guard)
    sys.path.insert(0, "eval"); import safety
    q = {i["id"]: i["question"] for i in safety.ITEMS}
    for r in json.load(open("eval/safety_results.json", encoding="utf8")):
        rec[q[r["id"]].strip()] = dict(sql=r["sql"], error=r["error"])
json.dump(rec, open("src/risksql/replay.json", "w", encoding="utf8"), ensure_ascii=False, indent=1)
print(len(rec), "recorded")
