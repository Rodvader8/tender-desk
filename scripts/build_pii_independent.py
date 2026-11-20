"""Turn a hand-written file of tenders with [[TYPE|value]] markup into evals/pii_independent.jsonl.

Tenders are separated by a line of five equals signs. Types: PERSON, PHONE, EMAIL, ADDRESS. Lines starting with # are ignored.
Usage: python scripts/build_pii_independent.py path/to/file.txt
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from make_pii_sets import parse_markup  # noqa: E402


def main() -> None:
    raw = Path(sys.argv[1]).read_text()
    blocks = [b.strip("\n") for b in raw.split("\n=====\n")]
    rows = []
    for b in blocks:
        body = "\n".join(line for line in b.splitlines() if not line.startswith("#")).strip("\n")
        if not body.strip():
            continue
        text, spans = parse_markup(body)
        rows.append({"id": f"i{len(rows) + 1:03d}", "text": text, "spans": spans})
    out = Path(__file__).resolve().parents[1] / "evals" / "pii_independent.jsonl"
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    n = {t: sum(s["type"] == t for r in rows for s in r["spans"]) for t in ("PERSON", "PHONE", "EMAIL", "ADDRESS")}
    print(f"wrote {out.name}: {len(rows)} tenders ({sum(not r['spans'] for r in rows)} with no personal data), spans {n}")


if __name__ == "__main__":
    main()
