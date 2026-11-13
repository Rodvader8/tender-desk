# Written before the agent evaluation code existed

Question: does an agent that can search the price list through MCP, reword its own searches and spec-check its answer do better than the fixed pipeline (retrieve top 4, model picks, code spec-checks) on trade slang, and does it stay safe on near-miss specs?

Set: `evals/holdout3.jsonl`, 27 queries: 15 new slang, 4 plain, 6 near-miss specs not in the catalogue, 2 clearly not in the catalogue. Fresh phrasings, none used before. The agent prompt was edited once (at most three searches, then stop with null) after a manual run showed it searching six times on a near-miss; that prompt is the one tested.

Both sides use the same models (deepseek-v4-flash, claude-haiku-5.5), temperature 0, spend capped per run, run once.

Measured: correct answers (the right sku, or null for the 8 not-in-catalogue queries), wrong picks, false matches on the 8, queries with no answer (step limit), average tool calls, cost per query.

Not claimed in advance: that the agent wins. The pipeline might be cheaper and equal. Any result is reported, including a loss.
