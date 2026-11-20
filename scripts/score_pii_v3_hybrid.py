"""Score the v3 hybrid: v3 rules plus the Privacy Filter's person spans (see evals/PREREGISTRATION_PII_V3.md).

Not part of the app or CI (needs torch and a 2.8 GB model). Run from a separate environment with the model installed:
  PYTHONPATH=src /path/to/venv/bin/python scripts/score_pii_v3_hybrid.py test3 --out results/pii_test3_v3_hybrid.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import score_pii  # noqa: E402

from tender_desk.redact import Span, detect  # noqa: E402


def main() -> None:
    from opf import OPF

    model = OPF(device="cpu", output_mode="typed")
    cache: dict[str, list[Span]] = {}

    def person_spans(text: str) -> list[Span]:
        if text not in cache:
            cache[text] = [
                Span("PERSON", s.start, s.end) for s in model.redact(text).detected_spans if s.label == "private_person"
            ]
        return cache[text]

    score_pii.detect = lambda text: detect(text, [person_spans])
    split = sys.argv[1]
    rows = [json.loads(line) for line in (score_pii.ROOT / "evals" / f"pii_{split}.jsonl").read_text().splitlines()]
    res = score_pii.score(rows)
    print(json.dumps({k: v for k, v in res.items() if k not in ("misses", "false_positives")}, indent=1))
    if "--out" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--out") + 1])
        out.write_text(json.dumps({"detector": "v3_hybrid", "set": split, **res}, indent=1) + "\n")


if __name__ == "__main__":
    main()
