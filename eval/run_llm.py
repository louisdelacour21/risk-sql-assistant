"""Score the LLM path alone on every question of a split (resumable: results are appended per question).
Usage: python eval/run_llm.py dev|test"""
import json
import os
import sys
sys.path.insert(0, "src")
import ollama
from risksql import executor, evaluate as ev, llm

split = sys.argv[1]
path = f"eval/llm_{split}.json"
done = json.load(open(path, encoding="utf8")) if os.path.exists(path) else []
seen = {r["id"] for r in done}
con = executor.connect("data/risk.duckdb")
client = ollama.Client(timeout=600)
for it in ev.load(split):
    if it["id"] in seen:
        continue
    _, ref = executor.run(con, it["reference_sql"])
    r = llm.propose(it["question"], client)
    got, err = None, r["error"]
    if r["sql"]:
        try:
            _, got = executor.run(con, r["sql"])
        except Exception as e:  # runtime error or timeout -> declared failure
            err = f"{type(e).__name__}: {e}"
    done.append(dict(id=it["id"], sql=r["sql"], outcome=ev.outcome(ref, got, it["ordered"]), attempts=r["attempts"],
                     seconds=round(r["seconds"], 1), error=err))
    json.dump(done, open(path, "w", encoding="utf8"), ensure_ascii=False, indent=1)
    print(it["id"], done[-1]["outcome"], done[-1]["seconds"], flush=True)
print(ev.summarize([r["outcome"] for r in done]))
