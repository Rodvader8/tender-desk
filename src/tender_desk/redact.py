"""Personal-data redaction. The model sees placeholders, the code keeps the map and puts the real values back.

Detector v3 is rules only and tuned for Australian formats. It finds emails, phone numbers, street addresses and names. Policy:
company names, ABNs and ACNs, 1300/1800/13 xx xx numbers and a bare suburb or postcode are business or public details, not personal
data, so they are left alone. (v1, as first scored, is frozen in evals/redact_v1.py.)

This is not anonymisation. A value the rules miss goes to the model. The map (placeholder to real value) lives only in a
Redactor object in memory: it is never put in a prompt, an audit entry, a run step, a log line or a metric. Callers log `counts`.

A second detector, for example a local model that finds names, can be added through `extra_detectors`. Only its PERSON spans are
used, and a span that holds a company or filler word is dropped.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

TYPES = ("PERSON", "PHONE", "EMAIL", "ADDRESS")
_PRIORITY = {"EMAIL": 0, "ADDRESS": 1, "PHONE": 2, "PERSON": 3}


@dataclass(frozen=True)
class Span:
    type: str
    start: int
    end: int


Detector = Callable[[str], Sequence[Span]]

# ---- email ----------------------------------------------------------------------------------------------------------
_EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
# "name at domain dot com": people write it this way to dodge scrapers
_EMAIL_AT = re.compile(
    r"(?<![\w.])[A-Za-z0-9._-]+[ \t]+\(?at\)?[ \t]+[A-Za-z0-9-]+(?:[ \t]+(?:dot|\.)[ \t]+[A-Za-z0-9-]+)+(?!\w)", re.I
)


_EMAIL_PAREN = re.compile(r"(?<![\w.])[A-Za-z0-9._-]+[(\[]at[)\]][A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?![\w])", re.I)


def find_emails(text: str) -> list[Span]:
    return [Span("EMAIL", m.start(), m.end()) for rx in (_EMAIL, _EMAIL_AT, _EMAIL_PAREN) for m in rx.finditer(text)]


# ---- phone ----------------------------------------------------------------------------------------------------------
# A candidate starts with 0 or +61 and is followed by 8 to 10 more digits with spaces, dashes, dots or brackets between them.
_PHONE = re.compile(
    r"(?<![\w+/.-])(?P<core>(?:\+61|\(?0\)?)(?:[ \t.()-]*\d){8,10})(?![\d]|[ \t]?\d)(?P<ext>[ \t]*(?:ext\.?|extension|x)[ \t]*\d{1,4}\b)?"
)
_PHONE_CUES = r"(?:ph|phone|tel|telephone|mob|mobile|call|ring|office|home|after[ \t]+hours)"
_LOCAL8 = re.compile(
    rf"(?i:\b{_PHONE_CUES}\b)(?:[ \t:.,-]+[A-Za-z]+){{0,3}}?[ \t:.-]*(?<![\d$])(\d{{4}}[ \t-]?\d{{4}})(?![\d.,]?\d)"
)
# a business number, or a code that only looks like a phone number, just before the digits
_NOT_A_PHONE_BEFORE = re.compile(
    r"(?<![A-Za-z])(?:ABN|ACN|part|code|sku|ref|item|order|invoice|job|quote|drawing|dwg|serial|model|no\.?|#)[ \t.:#-]*(?:no\.?|number)?[ \t.:#-]*$",
    re.I,
)


def find_phones(text: str) -> list[Span]:
    out: list[Span] = []
    for m in _PHONE.finditer(text):
        raw = m.group("core")
        plus61 = raw.startswith("+61")
        digits = re.sub(r"\D", "", raw)
        if plus61:
            digits = digits[2:]
            if digits.startswith("0"):  # +61 (0)4...
                digits = digits[1:]
            digits = "0" + digits
        if len(digits) != 10 or digits[:2] not in {"04", "02", "03", "07", "08"}:
            continue
        if _NOT_A_PHONE_BEFORE.search(text[max(0, m.start() - 16) : m.start()]):
            continue
        out.append(Span("PHONE", m.start(), m.end()))  # the extension, if any, is part of the span
    for m in _LOCAL8.finditer(text):
        if not _NOT_A_PHONE_BEFORE.search(text[max(0, m.start(1) - 16) : m.start(1)]):
            out.append(Span("PHONE", m.start(1), m.end(1)))
    return out


# ---- address --------------------------------------------------------------------------------------------------------
_TYPE_LIST = (
    "Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Court|Ct|Place|Pl|Lane|Ln|Crescent|Cres|Parade|Pde|Terrace|Tce|Highway|Hwy|"
    "Boulevard|Blvd|Close|Cl|Way|Circuit|Cct|Esplanade|Grove|Mews|Parkway|Pkwy|Rise|Retreat|Promenade|Chase|Walk|Row"
)
_STATE = r"(?:NSW|VIC|QLD|SA|WA|TAS|NT|ACT)"
_WORD = r"[A-Z][A-Za-z'’-]+"
_NAME_WORDS = rf"(?:{_WORD}[ \t]+){{1,4}}"
_SUBURB = rf"{_WORD}(?:[ \t]+{_WORD}){{0,2}}"
_TAIL = rf"(?:(?:,?[ \t]*\n?[ \t]*|,?[ \t]+)(?:{_SUBURB}[ \t,]+)?{_STATE}[ \t]+\d{{4}}\b)"
_STREET = (
    rf"(?:\b(?:Level|Suite|Shop|Floor)[ \t]+\d{{1,4}}[A-Za-z]?,[ \t]*|\bUnit[ \t]+\d{{1,4}}[A-Za-z]?,[ \t]*|\bUnit[ \t]+)?(?<![\d-])\b\d{{1,4}}[A-Za-z]?(?:/\d{{1,4}}[A-Za-z]?)?[ \t]+"
    rf"{_NAME_WORDS}(?:{_TYPE_LIST})\b"
)
_LOT = rf"\bLot[ \t]+\d{{1,4}}[ \t]+{_NAME_WORDS}(?:{_TYPE_LIST})\b"
_CORNER = (
    rf"\b(?i:cnr|corner)[ \t.]+(?:(?i:of)[ \t]+)?(?:{_WORD}[ \t]+)+(?:&|(?i:and))[ \t]+(?:{_WORD}[ \t]+)*(?:{_TYPE_LIST})s?\b"
)
_ADDRESS = re.compile(rf"(?:{_STREET}|{_LOT}|{_CORNER}){_TAIL}?")
_ESTATE = re.compile(
    rf"(?:\bLot[ \t]+\d{{1,4}}[ \t]+)?(?:(?<![\d-])\b\d{{1,4}}[ \t]+)?(?:{_WORD}[ \t]+){{1,3}}Estate,[ \t]*{_SUBURB}(?:[ \t]+{_STATE}[ \t]+\d{{4}}\b)?"
)
_TYPE_LC = _TYPE_LIST.lower()
_ADDRESS_LC = re.compile(
    rf"(?<![\d-])\b\d{{1,4}}[ \t]+(?:[a-z'’-]+[ \t]+){{1,2}}(?:{_TYPE_LC})\b,[ \t]*[a-z]+(?:[ \t][a-z]+){{0,2}}(?:[ \t]+{_STATE.lower()}[ \t]+\d{{4}})?"
)
_POBOX = re.compile(rf"\bP\.?O\.?[ \t]+Box[ \t]+\d{{1,6}}(?:,?[ \t]+(?:{_SUBURB}[ \t,]+)?{_STATE}[ \t]+\d{{4}}\b)?")
# words that make "12 Boundary Road base layers" a quantity phrase, not a place
_NOT_STREET_WORDS = {"Hire", "Pump", "Base", "Fees", "Fee", "Markers", "Layers", "Pavers", "Sets", "Days", "Hours", "Weeks"}
_NEXT_OK = {
    "on",
    "in",
    "at",
    "and",
    "or",
    "by",
    "to",
    "for",
    "from",
    "is",
    "with",
    "before",
    "after",
    "where",
    "which",
    "near",
    "then",
}
_NEXT_WORD = re.compile(r"[ \t]+([A-Za-z]+)")


def _looks_like_a_quantity(text: str, m: re.Match) -> bool:
    """A bare street (no state and postcode) followed by a lower-case word that isn't a plain joining word, or a trade noun."""
    if re.search(_STATE + r"[ \t]+\d{4}", m.group(0)):
        return False
    words = set(re.findall(r"[A-Za-z]+", m.group(0)))
    if words & _NOT_STREET_WORDS:
        return True
    if re.match(r"-[A-Za-z]", text[m.end() : m.end() + 2]):  # "Smith Street-style bricks"
        return True
    nxt = _NEXT_WORD.match(text, m.end())
    if not nxt:
        return False
    w = nxt.group(1)
    return (w[0].islower() and w not in _NEXT_OK) or w in _NOT_STREET_WORDS


def find_addresses(text: str) -> list[Span]:
    out = []
    for rx in (_ADDRESS, _ESTATE, _ADDRESS_LC, _POBOX):
        for m in rx.finditer(text):
            if rx is _POBOX or rx is _ESTATE or not _looks_like_a_quantity(text, m):
                out.append(Span("ADDRESS", m.start(), m.end()))
    return out


# ---- names ----------------------------------------------------------------------------------------------------------
_NAME_WORD = r"(?:[A-Z][A-Za-z'’-]+|[A-Z][A-Z'’-]+|[A-Z]\.?(?=[ \t]+[A-Z]))"
_NAME = rf"{_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{0,2}}"
_CUES = (
    r"(?:Attn|Attention|Site[ \t]+contact|Contact[ \t]+person|Contact|Kind[ \t]+regards|Best[ \t]+regards|Regards|Thanks|Cheers|Signed)"
    r"[ \t]*[:,.]?[ \t]*\n?[ \t]*"
)
_COLON_CUES = (
    r"(?:Owner|Prepared[ \t]+by|Contact[ \t]+name|Client[ \t]+contact|Name|Site[ \t]+manager|Project[ \t]+manager|Supervisor|From)"
    r"[ \t]*:[ \t]*"
)
_VERB_CUES = (
    r"(?:ring|call|ask[ \t]+for|speak[ \t]+to|speak[ \t]+with|meet|liaise[ \t]+with|arrange[ \t]+access[ \t]+with|"
    r"(?:send|email|forward|return|submit)[ \t]+(?:the[ \t]+)?(?:quote|tender|response|reply|invoice|documents?)?[ \t]*to)[ \t]+"
    r"(?:(?:the[ \t]+)?(?:owner|foreman|supervisor|client|manager|site[ \t]+supervisor)[ \t]+)?"
)
_ROLES = r"(?:owner|client|site[ \t]+manager|foreman|supervisor|manager|site[ \t]+supervisor)"
_TITLES = r"(?:Mr|Mrs|Ms|Miss|Mx|Dr)\.?[ \t]+"
_NAME_CUE = re.compile(
    rf"(?i:\b(?:{_CUES}))(?:(?i:(?:Mr|Mrs|Ms|Miss|Mx|Dr))\.?[ \t]+)?(?P<n1>{_NAME})"
    rf"|\b{_TITLES}(?P<n2>{_NAME})"
    rf"|(?i:\b{_COLON_CUES})(?P<n3>{_NAME})"
    rf"|(?i:\b{_VERB_CUES})(?P<n4>{_NAME})"
    rf"|(?P<n5>{_NAME})(?=[ \t]*\((?i:the[ \t]+)?{_ROLES}\)|,[ \t]+(?i:the[ \t]+){_ROLES}\b)"
)
_COMPANY_WORDS = {
    "pty", "ltd", "limited", "group", "constructions", "construction", "builders", "building", "plumbing", "electrical",
    "supplies", "hardware", "concrete", "services", "company", "co", "inc", "holdings", "projects", "pumping", "roofing",
    "council", "office", "department", "team", "us", "please", "details", "person", "number", "email", "phone", "on", "at",
    "the", "for", "to", "all", "any", "site", "name", "info", "information", "enquiries", "reception", "admin", "manager",
    "landscapes", "earthworks", "electricians", "plumbers", "drawing", "appendix", "schedule", "section", "clause",
    "attachment", "note", "notes", "sheet", "item", "tender", "quote", "scope", "access", "contact", "attn", "regards",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "ask", "meet", "call", "ring", "speak",
    "liaise", "arrange", "later", "then", "first", "owner", "client", "supervisor", "foreman",
}  # fmt: skip
_LEADING_CUE_WORDS = {
    "contact",
    "attn",
    "ask",
    "meet",
    "call",
    "ring",
    "speak",
    "liaise",
    "arrange",
    "please",
    "regards",
    "later",
    "then",
}


def _personal_name(raw: str, start: int) -> tuple[str, int] | None:
    """Drop cue words that got captured at the front, then drop the whole name if a company or filler word is in it."""
    words = raw.split()
    offset = 0
    while words and words[0].lower().strip(".,") in _LEADING_CUE_WORDS:
        offset = raw.index(words[0], offset) + len(words[0])
        words = words[1:]
    if not words or any(w.lower().strip(".,") in _COMPANY_WORDS for w in words):
        return None
    first = raw.index(words[0], offset)
    return " ".join(raw[first:].split()[: len(words)]), start + first


def find_names(text: str) -> list[Span]:
    out: list[Span] = []
    found: list[str] = []
    for m in _NAME_CUE.finditer(text):
        g = next(k for k in ("n1", "n2", "n3", "n4", "n5") if m.group(k) is not None)
        got = _personal_name(m.group(g), m.start(g))
        if not got:
            continue
        name, start = got
        out.append(Span("PERSON", start, start + len(name)))
        found.append(name)
    seen: set[str] = set()
    for name in found:  # later repeats: the full name, then each part of it on its own
        for part in [name] + [w for w in re.split(r"[ \t]+", name) if len(w) >= 3 and w.lower() not in _COMPANY_WORDS]:
            if part.lower() in seen:
                continue
            seen.add(part.lower())
            for m in re.finditer(rf"(?<![\w'’-]){re.escape(part)}(?![\w'’-])", text, re.I if " " in part else 0):
                if not any(m.start() < o.end and o.start < m.end() for o in out):
                    out.append(Span("PERSON", m.start(), m.end()))
    return sorted(set(out), key=lambda s: s.start)


# ---- combine --------------------------------------------------------------------------------------------------------
def _model_names(text: str, extra: Sequence[Detector]) -> list[Span]:
    out = []
    for d in extra:
        for s in d(text):
            if (
                s.type == "PERSON"
                and not re.search(r"\d", text[s.start : s.end])
                and _personal_name(text[s.start : s.end], s.start)
            ):
                out.append(s)
    return out


def detect(text: str, extra_detectors: Sequence[Detector] = ()) -> list[Span]:
    """All personal-data spans, no overlaps. When two overlap, the earlier-listed type wins, then the longer span."""
    found = find_emails(text) + find_addresses(text) + find_phones(text) + find_names(text) + _model_names(text, extra_detectors)
    found.sort(key=lambda s: (_PRIORITY[s.type], -(s.end - s.start)))
    taken: list[Span] = []
    for s in found:
        if not any(s.start < t.end and t.start < s.end for t in taken):
            taken.append(s)
    return sorted(taken, key=lambda s: s.start)


def _key(kind: str, value: str) -> str:
    """Same value, same placeholder: ignore case, spacing and punctuation that doesn't change who or what it is."""
    if kind == "PHONE":
        digits = re.sub(r"\D", "", value)
        return "0" + digits[2:] if digits.startswith("61") else digits
    if kind == "EMAIL":
        return value.lower()
    return re.sub(r"[\s,]+", " ", value).strip().lower()


_PLACEHOLDER = re.compile(r"\[(PERSON|PHONE|EMAIL|ADDRESS)_(\d+)\]")


class Redactor:
    """One per tender. The same real value always gets the same placeholder."""

    def __init__(self, extra_detectors: Sequence[Detector] = ()) -> None:
        self._extra = tuple(extra_detectors)
        self._by_key: dict[tuple[str, str], str] = {}
        self._real: dict[str, str] = {}  # placeholder -> first spelling seen
        self._n = dict.fromkeys(TYPES, 0)
        self.counts: dict[str, int] = dict.fromkeys(TYPES, 0)  # values found, by type (not distinct values)

    def redact(self, text: str) -> str:
        out, last = [], 0
        for s in detect(text, self._extra):
            value = text[s.start : s.end]
            k = (s.type, _key(s.type, value))
            ph = self._by_key.get(k)
            if ph is None:
                self._n[s.type] += 1
                ph = f"[{s.type}_{self._n[s.type]}]"
                self._by_key[k] = ph
                self._real[ph] = value
            self.counts[s.type] += 1
            out.append(text[last : s.start])
            out.append(ph)
            last = s.end
        out.append(text[last:])
        return "".join(out)

    def redact_note(self, text: str) -> str:
        """For free text a reviewer types after the tender was read. Values already known from the tender are replaced wherever
        they appear, cue or no cue; then the normal detector runs. The tender text itself only goes through `redact`, so what is
        measured in the evaluation is what runs on tenders."""
        for ph, value in sorted(self._real.items(), key=lambda kv: -len(kv[1])):
            text = re.sub(rf"(?<!\w){re.escape(value)}(?!\w)", ph, text, flags=re.I)
        return self.redact(text)

    def restore(self, text: str) -> str:
        """Put real values back. A placeholder this tender never issued is left as it is."""
        return _PLACEHOLDER.sub(lambda m: self._real.get(m.group(0), m.group(0)), text)

    def restore_deep(self, obj):
        """Restore inside every string of a nested dict/list."""
        if isinstance(obj, str):
            return self.restore(obj)
        if isinstance(obj, list):
            return [self.restore_deep(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.restore_deep(v) for k, v in obj.items()}
        return obj

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def __repr__(self) -> str:  # never show values, even by accident in a log line or a traceback
        return f"Redactor(counts={self.counts})"
