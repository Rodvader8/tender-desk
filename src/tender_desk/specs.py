"""Deterministic spec check: never price a line with a different size or grade than the tender asked for.

Pulls typed spec tokens out of the tender line and the chosen item's name. If both carry a token of
the same type and none of the values agree, that is a conflict. Quantities and areas (m2, weeks,
hours, '8 off') are not spec types and are ignored on purpose.

Known gap: item names with a bare number and no unit ('Concrete block 190 laid') carry no typed token,
so a conflicting block size is not caught.
"""

from __future__ import annotations

import re

_UNIT = {
    "mpa": "mpa",
    "meg": "mpa",
    "mm": "mm",
    "mil": "mm",
    "millimetre": "mm",
    "millimetres": "mm",
    "l": "l",
    "litre": "l",
    "litres": "l",
    "liter": "l",
    "liters": "l",
    "um": "um",
    "micron": "um",
    "microns": "um",
}
_LABEL = {
    "mpa": "MPa",
    "mm": "mm",
    "l": "L",
    "um": "micron",
    "n": "N bar",
    "sl": "SL mesh",
    "r": "R-value",
    "ub": "UB section",
    "pfc": "PFC section",
    "dim": "dimensions",
}


def _num(s: str) -> str:
    return str(float(s)).rstrip("0").rstrip(".")


def spec_tokens(text: str) -> list[tuple[str, str]]:
    t = text.lower().replace("×", "x").replace("²", "2")
    out: list[tuple[str, str]] = []
    for m in re.finditer(r"\b(\d{2,3})\s?ub\s?(\d{2,3})\b", t):
        out.append(("ub", f"{m[1]}ub{m[2]}"))
    for m in re.finditer(r"\b(\d{2,3})\s?pfc\b", t):
        out.append(("pfc", m[1]))
    for m in re.finditer(r"\bsl\s?(\d{2,3})\b", t):
        out.append(("sl", m[1]))
    for m in re.finditer(r"\bn\s?(\d{2})\b", t):
        out.append(("n", m[1]))
    for m in re.finditer(r"\br\s?(\d(?:\.\d)?)\b", t):
        out.append(("r", _num(m[1])))
    # dimensions like 140x45 or 150x90x8; skip site dimensions followed by a length unit ("6 x 3 m")
    for m in re.finditer(r"\b(\d+(?:\.\d+)?(?:\s?x\s?\d+(?:\.\d+)?)+)(?!\s?(?:m\b|metre))", t):
        out.append(("dim", "x".join(_num(p) for p in re.split(r"\s?x\s?", m[1]))))
    for m in re.finditer(r"\b(\d+(?:\.\d+)?)\s?(mpa|meg|mm|mil|millimetres?|litres?|liters?|um|microns?|l)\b", t):
        out.append((_UNIT[m[2]], _num(m[1])))
    return out


def spec_conflicts(tender_text: str, item_name: str) -> list[str]:
    s, i = spec_tokens(tender_text), spec_tokens(item_name)
    msgs = []
    for typ in dict.fromkeys(t for t, _ in s):
        have = [v for t, v in i if t == typ]
        want = [v for t, v in s if t == typ]
        if have and not set(want) & set(have):
            msgs.append(f"tender asks {_LABEL[typ]} {', '.join(want)}, price list item is {', '.join(have)}")
    return msgs
