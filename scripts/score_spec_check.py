"""Score the spec checker on the frozen pairs. uv run python scripts/score_spec_check.py"""

import json
from pathlib import Path

from tender_desk.specs import spec_conflicts

rows = [json.loads(line) for line in (Path(__file__).parents[1] / "evals" / "spec_pairs.jsonl").read_text().splitlines()]
conf = [r for r in rows if r["expect"] == "conflict"]
ok = [r for r in rows if r["expect"] == "ok"]
missed = [r for r in conf if not spec_conflicts(r["query"], r["item"])]
false = [r for r in ok if spec_conflicts(r["query"], r["item"])]
print(f"conflict pairs caught: {len(conf) - len(missed)}/{len(conf)} ({(len(conf) - len(missed)) / len(conf):.0%})")
print(f"same-spec pairs wrongly flagged: {len(false)}/{len(ok)}")
for r in missed:
    print("  MISSED :", r["id"], repr(r["query"]), "vs", repr(r["item"]))
for r in false:
    print("  FALSE  :", r["id"], repr(r["query"]), "vs", repr(r["item"]), spec_conflicts(r["query"], r["item"]))
