"""Record the SQL the model produced for every evaluation question, so the online demo can replay it (no model there).
Latest run per question wins: test v2 and dev (current prompt) over test v1 (old prompt, kept only for questions not re-asked)."""
import json
import sys
sys.path.insert(0, "src")
from risksql import evaluate as ev

rec = {}
for split in ("test", "dev", "test2"):  # later splits override earlier ones
    qs = {x["id"]: x["question"] for x in ev.load(split)}
    for r in json.load(open(f"eval/llm_{split}.json", encoding="utf8")):
        rec[qs[r["id"]].strip()] = dict(sql=r["sql"], error=r["error"])
json.dump(rec, open("src/risksql/replay.json", "w", encoding="utf8"), ensure_ascii=False, indent=1)
print(len(rec), "recorded")
