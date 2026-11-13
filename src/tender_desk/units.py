"""Normalise unit spellings so 'm²' and 'm2' match but 'm2' and 'm' still don't."""
import re

_CANON = {
    "m2": "m2", "m²": "m2", "sqm": "m2", "sq m": "m2", "square metre": "m2", "square metres": "m2",
    "m3": "m3", "m³": "m3", "cum": "m3", "cubic metre": "m3", "cubic metres": "m3",
    "m": "m", "lm": "m", "lin m": "m", "lineal metre": "m", "lineal metres": "m", "linear metre": "m", "linear metres": "m", "metre": "m", "metres": "m",
    "hour": "hour", "hours": "hour", "hr": "hour", "hrs": "hour",
    "day": "day", "days": "day", "week": "week", "weeks": "week", "wk": "week",
    "sheet": "sheet", "sheets": "sheet", "length": "length", "lengths": "length",
    "each": "each", "ea": "each", "no": "each", "no.": "each", "item": "each", "items": "each",
    "lump sum": "each", "ls": "each", "allowance": "each", "set": "each", "sets": "each",
}


def normalise_unit(u: str) -> str:
    """'m2', 'm²', 'sqm' and 'm² footprint' all become 'm2'. Extra trailing words are tolerated."""
    words = re.sub(r"[,;()]", " ", u.lower()).split()
    for n in range(len(words), 0, -1):  # longest known prefix wins: 'lump sum' before 'lump'
        if " ".join(words[:n]) in _CANON:
            return _CANON[" ".join(words[:n])]
    return " ".join(words)
