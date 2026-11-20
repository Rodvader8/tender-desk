"""Score a PII detector against a labelled set. Usage: python scripts/score_pii.py dev|test|dev3|test3 [--detector v1] [--out results/pii_test_v1_rules.json]

Recall: a labelled span is found only if every non-space, non-punctuation character of it lies inside a predicted span of the
same type. Precision: a predicted span is correct if it overlaps a labelled span of the same type. Prints the misses and the false
positives so they can be read and published.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tender_desk.redact import TYPES
from tender_desk.redact import detect as detect_v3

detect = detect_v3

ROOT = Path(__file__).resolve().parents[1]


def covered(text: str, gold: dict, preds: list) -> bool:
    cover = [p for p in preds if p.type == gold["type"]]
    for i in range(gold["start"], gold["end"]):
        if text[i].isalnum() and not any(p.start <= i < p.end for p in cover):
            return False
    return True


def score(rows: list[dict]) -> dict:
    tp = dict.fromkeys(TYPES, 0)
    gold_n = dict.fromkeys(TYPES, 0)
    found = dict.fromkeys(TYPES, 0)
    pred_n = dict.fromkeys(TYPES, 0)
    misses, fps = [], []
    tenders_with_miss = 0
    neg_fp = 0
    for r in rows:
        preds = detect(r["text"])
        missed_here = False
        for g in r["spans"]:
            gold_n[g["type"]] += 1
            if covered(r["text"], g, preds):
                found[g["type"]] += 1
            else:
                missed_here = True
                misses.append({"id": r["id"], "type": g["type"], "value": g["value"]})
        tenders_with_miss += missed_here
        for p in preds:
            pred_n[p.type] += 1
            if any(g["type"] == p.type and p.start < g["end"] and g["start"] < p.end for g in r["spans"]):
                tp[p.type] += 1
            else:
                fps.append({"id": r["id"], "type": p.type, "value": r["text"][p.start : p.end]})
                if not r["spans"]:
                    neg_fp += 1
    per = {
        t: {
            "labelled": gold_n[t],
            "found": found[t],
            "recall": round(found[t] / gold_n[t], 3) if gold_n[t] else None,
            "predicted": pred_n[t],
            "correct": tp[t],
            "precision": round(tp[t] / pred_n[t], 3) if pred_n[t] else None,
        }
        for t in TYPES
    }
    return {
        "tenders": len(rows),
        "tenders_without_personal_data": sum(not r["spans"] for r in rows),
        "per_type": per,
        "tenders_with_at_least_one_miss": tenders_with_miss,
        "false_positives_on_tenders_without_personal_data": neg_fp,
        "misses": misses,
        "false_positives": fps,
    }


def main() -> None:
    global detect
    if "--detector" in sys.argv and sys.argv[sys.argv.index("--detector") + 1] == "v1":
        from tender_desk.evals.redact_v1 import detect as detect_v1

        detect = detect_v1
    split = sys.argv[1]
    rows = [json.loads(line) for line in (ROOT / "evals" / f"pii_{split}.jsonl").read_text().splitlines()]
    res = score(rows)
    print(json.dumps({k: v for k, v in res.items() if k not in ("misses", "false_positives")}, indent=1))
    print("MISSES")
    for m in res["misses"]:
        print("  ", m)
    print("FALSE POSITIVES")
    for f in res["false_positives"]:
        print("  ", f)
    if "--out" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--out") + 1])
        out.write_text(
            json.dumps({"detector": "v1_rules" if detect is not detect_v3 else "v3_rules", "set": split, **res}, indent=1) + "\n"
        )
        print("wrote", out)


if __name__ == "__main__":
    main()
