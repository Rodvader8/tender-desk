"""Score OpenAI's open-source Privacy Filter (detector v2) on the same frozen PII set, with the same scoring as v1.

Not part of the app or CI: it needs torch and about 2.8 GB of weights. Run it from a separate environment:
  OPF_CHECKPOINT=/path/to/checkpoint /path/to/venv/bin/python scripts/score_pii_v2.py test --out results/pii_test_v2_privacy_filter.json
The model's labels are mapped to ours: private_person -> PERSON, private_phone -> PHONE, private_email -> EMAIL, private_address ->
ADDRESS. Its other labels (url, date, account_number, secret) have no counterpart in our sets and are ignored.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import score_pii  # noqa: E402

LABELS = {"private_person": "PERSON", "private_phone": "PHONE", "private_email": "EMAIL", "private_address": "ADDRESS"}


class Span:
    def __init__(self, type_: str, start: int, end: int) -> None:
        self.type, self.start, self.end = type_, start, end


def main() -> None:
    from opf import OPF

    model = OPF(device="cpu", output_mode="typed")
    cache: dict[str, list[Span]] = {}

    def detect(text: str) -> list[Span]:
        if text not in cache:
            r = model.redact(text)
            out = []
            for s in r.detected_spans:
                if s.label in LABELS:
                    out.append(Span(LABELS[s.label], s.start, s.end))
            cache[text] = out
        return cache[text]

    score_pii.detect = detect
    split = sys.argv[1]
    rows = [json.loads(line) for line in (score_pii.ROOT / "evals" / f"pii_{split}.jsonl").read_text().splitlines()]
    res = score_pii.score(rows)
    print(json.dumps({k: v for k, v in res.items() if k not in ("misses", "false_positives")}, indent=1))
    for m in res["misses"]:
        print("MISS", m)
    for f in res["false_positives"]:
        print("FP", f)
    if "--out" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--out") + 1])
        out.write_text(json.dumps({"detector": "v2_privacy_filter", "set": split, **res}, indent=1) + "\n")


if __name__ == "__main__":
    main()
