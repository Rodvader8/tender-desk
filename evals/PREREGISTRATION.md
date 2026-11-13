# Written before any rewrite code was run on holdout2

Problem: trade slang finds the right price item in the top 4 only 73% of the time (held-out set, 11 jargon queries).

Plan: have a cheap model rewrite each tender line into plain standard terms before searching. No per-item glossary and no hand-written slang list, so the fix can only help on slang the model already understands.

Two variants will be compared on the tuning set only: rewrite alone, and rewrite fused with the original query (reciprocal rank fusion).

Success on `evals/holdout2.jsonl` (fresh slang the fix has never seen, plus plain regression checks and near-miss negatives), run once:
- jargon queries: hit@4 clearly above plain vector search, and
- non-jargon queries: no more than one query worse, and
- selection eval: no new false matches on the near-miss negatives.

If it fails these, it is not wired into the workflow and the README says so.

## Added after the tuning-set run, before holdout2 was run

The tuning set has too little slang to separate the strategies: plain vector, rewrite only and rewrite fused all scored 96% hit@4 there.
So holdout2 is run once with all three and every number is reported. Adoption rule, fixed now:
- A variant is adopted only if it meets the three success criteria above.
- If both rewrite variants pass, adopt rewrite only (simpler), unless fused beats it on holdout2 hit@4 by two or more queries.
