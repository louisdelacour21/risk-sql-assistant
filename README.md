# risk-sql-assistant

Ask a market-risk database questions in French, get a SQL query you can read, and a number you can check.

A local 4B model (`qwen3.5:4b` through Ollama, no API, no cost) proposes the SQL. It never runs anything itself: every query goes through a SQL guard and a read-only DuckDB connection. The point of the project is the **measurement**: a frozen test set, a result comparator, confidence intervals, and the failures published instead of hidden.

All data is **synthetic** (60 positions, 250 business days, as of 2026-10-30, three books, two desks). These are not real ECB/FRED series.

## How a question is answered

1. **Templates first.** 11 deterministic templates (VaR/ES of a book on a date, P&L by desk, limit usage…) answer the frequent shapes with no model.
2. **Otherwise the model.** The prompt holds the catalogue (5 views, with descriptions) and the 6 verified question→SQL pairs most similar to the question (entities masked). The model answers in JSON `{sql, graphique, hypotheses, refus}`, validated with pydantic. One repair attempt with the exact error, then a declared failure.
3. **SQL guard** (`sqlglot`): one statement, `SELECT`/`UNION`/`WITH` only, no write node, only catalogue views, a function allow-list, columns resolved (invented columns are rejected), `LIMIT 1000` forced.
4. **Read-only executor:** DuckDB with external access disabled, configuration locked, 5 s timeout (a cartesian product is interrupted).

The guard is tested against 40 hostile queries (stacked statements, `COPY`, `read_csv`, `ATTACH`, comment tricks, `pragma`…) and 20 legitimate ones. Tests run without Ollama.

## Results

Two question sets, both written by the author, with the reference SQL checked by running it on the database. Scoring compares result sets (6 significant digits, NULLs as values, column order ignored, row order only when asked). Intervals are Wilson 95 %.

| Run | n | Correct | Wrong without saying so | Declined |
|---|---|---|---|---|
| Test v1, first prompt (frozen, run once) | 70 | 37 (53 %, 41–64 %) | 32 (46 %) | 1 |
| **Test v2, retrieval prompt (frozen, run once)** | 60 | **53 (88 %, 78–94 %)** | 6 (10 %) | 1 |
| Templates alone on test v2 | 60 | 11 (they answer only what they cover) | 0 | 49 |

On test v2, accepting extra columns (the right value plus one more) raises the correct count to 56/60. That relaxation was decided after seeing the errors, so the strict figure is the headline.

Latency on a 16 GB laptop with no GPU: median 42 s, p95 71 s per model question. Templates answer instantly. This is slow; it is a measurement tool, not a product.

### What happened between v1 and v2, honestly

v1 scored 53 %. Reading its failures showed fixable causes: a misleading few-shot example ("P&L par mois") that made the model add a monthly `GROUP BY` everywhere, the wrong view for daily book P&L, missing `GROUP BY`, invented filters. The prompt changed to retrieval few-shot over the 100 verified pairs of dev + v1, and a **new** 60-question set (v2) was written and run once. v1 is now burned for tuning and is reported as the "before" row. The pairs from v1 sit in the few-shot pool, so v2 questions that look like v1 questions benefit from them: v2 is easier than a set written by a stranger.

### Limits you should know

- Both question sets are written by the author. 20 questions written blind by a third party are still missing; the real figure on unseen phrasing is probably lower than 88 %.
- The remaining v2 errors are silent: a plausible query returning a wrong number (a cumulative P&L returned as a plain sum, a delta FX computed from the notional, the first date of the base taken over four views). The guard prevents damage, not wrong answers. Always read the displayed SQL.
- Ambiguous phrasing ("last 30 days": `>` or `>=`?) is scored against one fixed reading.
- 60 questions give wide intervals; do not read 88 % versus 85 % as a difference.
- Out-of-scope questions are only lightly tested (one refusal example in the prompt).

## Run it

```bash
pip install -e ".[dev]"
pytest -q                      # 72 tests, no Ollama needed
streamlit run app.py           # live mode if Ollama is running, replay mode otherwise
```

Live mode needs `ollama pull qwen3.5:4b`. Replay mode (used by the online demo) replays the SQL recorded during the evaluation for the 160 evaluation questions, through the same guard and read-only executor; templates still run live. It cannot answer free-form questions.

Reproduce the numbers offline: `pytest tests/test_router.py` recomputes test v2 (53 correct, 6 wrong) from the recorded SQL. To re-run the model: `python eval/run_llm.py test2` (about 45 min on CPU).

## Layout

`src/risksql/` catalogue, guard, executor, templates, LLM step, router, scoring · `eval/` question sets (v2 sha256 in `TEST2_SHA256`), recorded model runs, scripts · `tests/` · `app.py` Streamlit front end · `data/risk.duckdb` synthetic database (1.6 MB).
