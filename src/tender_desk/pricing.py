"""The model's one job in pricing: pick a price item for each scope item from the candidates offered."""
from __future__ import annotations

import json

from .models import Choices

SYSTEM = ("For each scope item choose the best matching candidate price item by id, "
          "or null if none fits. Match the unit. Do not invent ids. Do not calculate prices.")


def build_offer(items: list[dict], candidates: dict) -> list[dict]:
    return [{"item_index": i, "scope_item": it["description"], "qty": it["qty"], "unit": it["unit"],
             "candidates": [{k: c[k] for k in ("id", "name", "unit", "unit_price")} for c in candidates[str(i)]]}
            for i, it in enumerate(items)]


def choose_prices(llm, offer: list[dict], feedback: str = "", purpose: str = "estimate") -> Choices:
    note = f"\nReviewer feedback on the previous draft: {feedback}" if feedback else ""
    return llm.structured([{"role": "system", "content": SYSTEM},
                           {"role": "user", "content": json.dumps(offer) + note}], Choices, purpose=purpose)
