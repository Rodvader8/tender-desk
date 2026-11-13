"""Prompt-injection defences. A tender is text from a stranger: treat it as data, and tell the reviewer when it looks odd.

Each defence is switchable (see Defenses) so the evaluation can measure what it adds.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Defenses:
    delimit: bool = False          # wrap tender text in <tender> tags and neutralise any tag the attacker writes
    estimate_notice: bool = False  # tell the pricing step that scope lines are untrusted
    bounds: bool = False           # cap what extraction may return (line count, text length, quantity)
    qty_check: bool = False        # flag an extracted quantity that does not appear in the tender text
    detector: bool = False         # flag instruction-like phrases in the tender text


D0 = Defenses()
D1 = Defenses(delimit=True, estimate_notice=True, bounds=True, qty_check=True, detector=True)

_TAGS = re.compile(r"<\s*/?\s*(tender|instructions?|system|assistant|user)\s*>", re.I)


def neutralise(text: str) -> str:
    """Stop the tender text closing our <tender> tag or pretending to be a message role."""
    return _TAGS.sub("[tag removed]", text)


_NUMBER_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve".split())}


def quantity_in_text(qty: float, text: str) -> bool:
    """True if the number appears in the tender (digits or a number word). A quantity of 1 is always allowed:
    'building permit fees' is one item without anyone writing '1'."""
    if abs(qty - 1) < 1e-9:
        return True
    nums = {float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*\.?\d*", text) if n.replace(",", "").replace(".", "").isdigit()}
    nums |= {float(v) for w, v in _NUMBER_WORDS.items() if re.search(rf"\b{w}\b", text, re.I)}
    return any(abs(qty - n) < 1e-9 for n in nums)


# Written from the dev attacks only. Deliberately modest: a determined attacker can rephrase around any list.
_PATTERNS = [
    r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(instructions?|rules|prompts?|system|constraints|schema)\b",
    r"\bsystem\s*(override|prompt|message|update|:)",
    r"\b(print|repeat|reveal|show|output)\b[^.\n]{0,40}\b(system prompt|your (full |entire )?(system )?(prompt|instructions)|everything above)",
    r"\b(pre-?approved|auto-?approve|skip (the )?review|mark (it|this)[^.\n]{0,20}approved)\b",
    r"\bprice_item_id\b|\bcandidate price item|\bchoose the (cheapest|most expensive) candidate|\banswer null\b",
    r"</?\s*(tender|instructions?|system)\s*>|```",
    r"\byou are now\b|\bnew instructions\b",
    r"\bignora\b[^.\n]{0,30}\binstrucciones\b",
]
_LEET = re.compile(r"\b\w*(?:ign[0o]re|pr[e3]v[i1][o0]us|instruct[i1][o0]ns)\w*\b", re.I)


def injection_phrases(text: str) -> list[str]:
    hits = [m.group(0).strip() for p in _PATTERNS for m in re.finditer(p, text, re.I)]
    hits += [m.group(0) for m in _LEET.finditer(text) if any(c.isdigit() for c in m.group(0))]
    return list(dict.fromkeys(h[:60] for h in hits))
