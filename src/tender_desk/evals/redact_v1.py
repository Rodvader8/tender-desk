"""FROZEN COPY of detector v1, as scored in results/pii_*_v1_rules.json. Do not edit; the app uses redact.py.

Personal-data redaction. The model sees placeholders, the code keeps the map and puts the real values back.

Detector v1 is rules only and tuned for Australian formats. It finds emails, phone numbers, street addresses and names that
follow a cue phrase. Policy: company names, ABNs and ACNs, 1300/1800/13 xx xx numbers and a bare suburb or postcode are business
or public details, not personal data, so they are left alone.

This is not anonymisation. A value the rules miss goes to the model. The map (placeholder to real value) lives only in a
Redactor object in memory: it is never put in a prompt, an audit entry, a run step, a log line or a metric. Callers log `counts`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TYPES = ("PERSON", "PHONE", "EMAIL", "ADDRESS")
_PRIORITY = {"EMAIL": 0, "ADDRESS": 1, "PHONE": 2, "PERSON": 3}


@dataclass(frozen=True)
class Span:
    type: str
    start: int
    end: int


# ---- email ----------------------------------------------------------------------------------------------------------
_EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


def find_emails(text: str) -> list[Span]:
    return [Span("EMAIL", m.start(), m.end()) for m in _EMAIL.finditer(text)]


# ---- phone ----------------------------------------------------------------------------------------------------------
# A candidate starts with 0 or +61 and is followed by 8 or 9 more digits with spaces, dashes, dots or brackets between them.
_PHONE = re.compile(r"(?<![\w+/.-])(?:\+61|\(?0\)?)(?:[ \t.()-]*\d){8,10}(?![\d]|[ \t]?\d)")
_LOCAL8 = re.compile(r"\b(?:ph|phone|tel|telephone|mob|mobile|call|ring|m|p)\b[:.]?[ \t]*(\d{4}[ \t-]?\d{4})(?!\d)", re.I)
_BUSINESS_BEFORE = re.compile(r"(?:ABN|ACN|A\.B\.N\.?)[ \t:#]*$", re.I)


def _national(digits: str, plus61: bool) -> str:
    """Return the number as it would be dialled inside Australia: 0 + area code + 8 digits."""
    return "0" + digits if plus61 else digits


def find_phones(text: str) -> list[Span]:
    out: list[Span] = []
    for m in _PHONE.finditer(text):
        raw = m.group(0)
        plus61 = raw.startswith("+61")
        digits = re.sub(r"\D", "", raw)
        if plus61:
            digits = digits[2:]
            if digits.startswith("0"):  # +61 (0)4...
                digits = digits[1:]
        nat = _national(digits, plus61) if plus61 else digits
        if len(nat) != 10 or nat[:2] not in {"04", "02", "03", "07", "08"}:
            continue
        if _BUSINESS_BEFORE.search(text[max(0, m.start() - 8) : m.start()]):
            continue
        out.append(Span("PHONE", m.start(), m.end()))
    for m in _LOCAL8.finditer(text):
        out.append(Span("PHONE", m.start(1), m.end(1)))
    return out


# ---- address --------------------------------------------------------------------------------------------------------
_STREET_TYPES = (
    "Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Court|Ct|Place|Pl|Lane|Ln|Crescent|Cres|Parade|Pde|Terrace|Tce|Highway|Hwy|"
    "Boulevard|Blvd|Close|Cl|Way|Circuit|Cct"
)
_STATE = r"(?:NSW|VIC|QLD|SA|WA|TAS|NT|ACT)"
_WORD = r"[A-Z][A-Za-z'’-]+"
_ADDRESS = re.compile(
    rf"(?:\bUnit[ \t]+)?\b\d{{1,4}}[A-Za-z]?(?:/\d{{1,4}}[A-Za-z]?)?[ \t]+(?:{_WORD}[ \t]+){{1,3}}(?:{_STREET_TYPES})\b"
    rf"(?:(?:,?[ \t]*\n?[ \t]*|,?[ \t]+)(?:{_WORD}(?:[ \t]+{_WORD}){{0,2}}[ \t,]+)?{_STATE}[ \t]+\d{{4}}\b)?"
)
_POBOX = re.compile(
    rf"\bP\.?O\.?[ \t]+Box[ \t]+\d{{1,6}}(?:,?[ \t]+(?:{_WORD}(?:[ \t]+{_WORD}){{0,2}}[ \t,]+)?{_STATE}[ \t]+\d{{4}}\b)?"
)
# A number, a capitalised word and a street type that is really a plain quantity phrase ("14 Concrete Pump Hire days").
_NOT_STREET_WORDS = {"Hire", "Pump", "Base", "Fees", "Fee", "Markers", "Layers", "Pavers", "Sets", "Days", "Hours", "Weeks"}


def find_addresses(text: str) -> list[Span]:
    out = []
    for m in list(_ADDRESS.finditer(text)) + list(_POBOX.finditer(text)):
        words = set(re.findall(r"[A-Za-z]+", m.group(0)))
        if words & _NOT_STREET_WORDS and not re.search(_STATE, m.group(0)):
            continue
        out.append(Span("ADDRESS", m.start(), m.end()))
    return out


# ---- names ----------------------------------------------------------------------------------------------------------
_NAME_WORD = r"(?:[A-Z][A-Za-z'’-]+|[A-Z][A-Z'’-]+)"
_NAME = rf"{_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{0,2}}"
_CUES = (
    r"(?:Attn|Attention|Site[ \t]+contact|Contact[ \t]+person|Contact|Kind[ \t]+regards|Best[ \t]+regards|Regards|Thanks|Cheers)[ \t]*[:,.]?"
    r"[ \t]*\n?[ \t]*"
)
_TITLES = r"(?:Mr|Mrs|Ms|Miss|Mx|Dr)\.?[ \t]+"
_NAME_CUE = re.compile(rf"(?i:\b(?:{_CUES}))(?P<n1>{_NAME})|\b{_TITLES}(?P<n2>{_NAME})")
_COMPANY_WORDS = {
    "pty",
    "ltd",
    "limited",
    "group",
    "constructions",
    "construction",
    "builders",
    "building",
    "plumbing",
    "electrical",
    "supplies",
    "hardware",
    "concrete",
    "services",
    "company",
    "co",
    "inc",
    "holdings",
    "projects",
    "pumping",
    "roofing",
    "council",
    "office",
    "department",
    "team",
    "us",
    "please",
    "details",
    "person",
    "number",
    "email",
    "phone",
    "on",
    "at",
    "the",
    "for",
    "to",
    "all",
    "any",
    "site",
    "name",
    "info",
    "information",
    "enquiries",
    "reception",
    "admin",
    "manager",
}


def _personal_name(raw: str) -> str | None:
    """A captured name is dropped whole if any word in it is a company or filler word ("Bluegum Constructions Pty Ltd")."""
    words = raw.split()
    if any(w.lower().strip(".,") in _COMPANY_WORDS for w in words):
        return None
    return " ".join(words) or None


def find_names(text: str) -> list[Span]:
    out: list[Span] = []
    names: set[str] = set()
    for m in _NAME_CUE.finditer(text):
        g = "n1" if m.group("n1") is not None else "n2"
        raw = m.group(g)
        name = _personal_name(raw)
        if not name:
            continue
        start = m.start(g)
        out.append(Span("PERSON", start, start + len(name)))
        if " " in name:
            names.add(name.lower())
    for n in names:  # later repeats of a full name found by a cue
        for m in re.finditer(rf"(?<!\w){re.escape(n)}(?!\w)", text, re.I):
            out.append(Span("PERSON", m.start(), m.end()))
    return sorted(set(out), key=lambda s: s.start)


# ---- combine --------------------------------------------------------------------------------------------------------
def detect(text: str) -> list[Span]:
    """All personal-data spans, no overlaps. When two overlap, the earlier-listed type wins, then the longer span."""
    found = find_emails(text) + find_addresses(text) + find_phones(text) + find_names(text)
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

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], str] = {}
        self._real: dict[str, str] = {}  # placeholder -> first spelling seen
        self._n = dict.fromkeys(TYPES, 0)
        self.counts: dict[str, int] = dict.fromkeys(TYPES, 0)  # values found, by type (not distinct values)

    def redact(self, text: str) -> str:
        out, last = [], 0
        for s in detect(text):
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
