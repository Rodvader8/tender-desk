"""Build the two PII evaluation sets (evals/pii_dev.jsonl, evals/pii_test.jsonl) from hand-written templates.

Everything is invented. Spans are labelled by construction: a template writes {PERSON}, {PHONE}, {EMAIL}, {ADDR} or an
explicit markup like [[PERSON|Priya Nair]], and the builder records exactly where each value landed. Plain text is never labelled,
so every near miss in it counts against precision if a detector flags it.

Run: python scripts/make_pii_sets.py   (fixed seed; the output is frozen once the checksums are written)
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "evals"

FIRST_DEV = ["Priya", "Tom", "Hamid", "Linh", "Deb", "James", "Maria", "Craig", "Aisha", "Wayne", "Bronwyn", "Sione"]
LAST_DEV = [
    "Nair",
    "O'Brien",
    "Karimi",
    "Tran",
    "Kowalski",
    "McAllister",
    "Lopez",
    "Fitzgerald",
    "Rahman",
    "Hollis",
    "Pettigrew",
    "Tuilagi",
]
FIRST_TEST = [
    "Natasha",
    "Dimitri",
    "Ping",
    "Gareth",
    "Fatima",
    "Rohan",
    "Kerry-Anne",
    "Mick",
    "Esther",
    "Anil",
    "Joanne",
    "Lachlan",
    "Ines",
    "Bruce",
]
LAST_TEST = [
    "Vasquez",
    "Papadopoulos",
    "Zhou",
    "Whitlock",
    "Haddad",
    "Mehta",
    "Brennan",
    "Szabo",
    "Okafor",
    "Banerjee",
    "Doyle",
    "Ferraro",
    "Lindqvist",
    "Marsh",
]

STREETS_DEV = ["Wattle", "Banksia", "Kestrel", "Marlborough", "Hargrave", "Cobalt", "Tallowood"]
STREETS_TEST = ["Ironbark", "Lyndhurst", "Cormorant", "Fenwick", "Galloway", "Sandpiper", "Westbourne", "Rosella"]
TYPES_LONG = ["Street", "Road", "Avenue", "Drive", "Court", "Place", "Lane", "Crescent", "Parade", "Terrace"]
TYPES_SHORT = ["St", "Rd", "Ave", "Dr", "Ct", "Pl", "Ln", "Cres", "Pde", "Tce"]
SUBURBS_DEV = [
    ("Parramatta", "NSW", "2150"),
    ("Box Hill", "VIC", "3128"),
    ("Manly", "NSW", "2095"),
    ("Indooroopilly", "QLD", "4068"),
]
SUBURBS_TEST = [
    ("Fremantle", "WA", "6160"),
    ("Glenelg", "SA", "5045"),
    ("Kellyville Ridge", "NSW", "2155"),
    ("Hawthorn", "VIC", "3122"),
    ("Kenmore", "QLD", "4069"),
]
DOMAINS = ["gmail.com", "outlook.com", "bigpond.com", "iinet.net.au", "harbour-works.example", "greenfield-homes.example"]
COMPANIES = [
    "Bluegum Constructions Pty Ltd",
    "Ironbark Plumbing Pty Ltd",
    "Corella Hardware",
    "Harbour Works Group",
    "Tallow Electrical Pty Ltd",
]

# Plain lines with no personal data. Several are deliberate near misses for the detector.
BODY = [
    "Scope: rear extension, 10 m3 of 25MPa concrete, 40 hours of carpenter labour.",
    "Supply and fix 120 x 45 mm treated pine studs, 240 lengths at 2.4 m.",
    "Our ABN is 51 824 753 556 and the licence number is 328814C.",
    "Questions about this tender: call our office on 1300 555 019 or 1800 555 020.",
    "Reference number 20261104, lodged 04/11/2026, closing 18/12/2026.",
    "Allow 12,500 m2 of site clearing and 3,200 m of trenching.",
    "Lot 4 DP 123456, council reference DA/2026/0417.",
    "Electrical: 24 power points, 18 downlights and 6 exhaust fans, 0.5 mm clearance to the eaves.",
    "Order 14 Concrete Pump Hire days and 2 Court Fees, both quoted separately.",
    "Allow 8 weeks from approval. Payment 14 days from invoice.",
    "Contact: Bluegum Constructions Pty Ltd for access to the compound.",
    "Contact: Ironbark Plumbing Pty Ltd, licensed plumber on site.",
    "Price the 3 bed 2 bath layout, about 215 m2 under roof.",
    "Delivery between 7 and 9 on weekdays. Colorbond roofing, 450 m2.",
    "Hydrant test at 1500 kPa, 20 minutes hold.",
    "Install 6 Lane markers and 2 Road base layers, as per drawing 4471-22.",
    "Footings to engineer's detail, 32 MPa, 300 mm wide.",
    "Retention 5 percent. Variations only by written instruction.",
]

# Near misses that appear in the test set only.
TEST_BODY = [
    "Quote ref QT-2026-0042, valid 30 days. Tender 2026/118.",
    "Reuse the 2 Park Lane Pavers from the old path.",
    "ABN 61 234 567 890, GST registered.",
    "Hinge set code 0245 123 456, 40 sets.",
    "Concrete mix: water to cement ratio 0.40, slump 80 mm, 7 day strength 20 MPa.",
    "Add 12 Boundary Road base layers to the access track.",
    "Phone-in concrete orders close at 3pm the day before.",
    "Council fee $1,250.00, paid 14/11/2026, receipt 88413207.",
]

# Contact templates shared by dev and test.
SHARED = [
    "Attn: {PERSON}\nPhone: {PHONE}",
    "Contact: {PERSON} on {PHONE}.",
    "Please email {EMAIL} with any questions.",
    "Site is at {ADDR}.",
    "Regards,\n{PERSON}\n{PHONE}",
    "Kind regards\n{PERSON}\nProject Manager\n{EMAIL}",
    "Mr {PERSON} will meet you on site. Mobile {PHONE}.",
    "Ms {PERSON}, {EMAIL}",
    "Mrs {PERSON} is the owner and lives at {ADDR}.",
    "Send the quote to {PERSON} ({EMAIL}), phone {PHONE}.",
    "ATTN: {PERSON:upper}\n{ADDR}",
    "Property: {ADDR}. Access by arrangement, call {PHONE}.",
    "Tender returns to {EMAIL} or post to {ADDR}.",
    "Contact {PERSON}, then {PERSON}. Phone {PHONE}, or {PHONE}.",
    "Site contact: {PERSON} ({PHONE})",
]
# Hard cases or layouts that appear in the test set only, to measure generalisation.
TEST_ONLY = [
    "Thanks {PERSON} for the walk-through, I'll call you on {PHONE}.",
    "Cheers,\n{PERSON}\nm: {PHONE}",
    "Contact person: {PERSON}\nMob {PHONE}\nEmail {EMAIL}",
    "Dr {PERSON} (the client) is on {PHONE}.",
    "Arrange access with [[PERSON|{PERSON_PLAIN}]], the owner, before 8am.",
    "Owner: [[PERSON|{PERSON_PLAIN}]]\nPhone: {PHONE}",
    "Prepared by: [[PERSON|{PERSON_PLAIN}]]. Questions on {EMAIL}.",
    "Ring the site foreman [[PERSON|{FIRST_ONLY}]] on {PHONE}.",
    "Mail to {ADDR}\nAttn: {PERSON}",
    "Ph [[PHONE|{LOCAL8}]] after 4pm.",
    "Call [[PHONE|{LOCAL8}]] (no area code needed).",
    "Reach the owner on [[PHONE|{LOCAL8_BARE}]] or [[EMAIL|{EMAIL_AT}]].",
    "Lot 5 [[ADDRESS|{LOT_ADDR}]]",
    "Job address: [[ADDRESS|{LOWER_ADDR}]]",
]
# Dev has two hard cases too, so the dev numbers aren't flattering either.
DEV_ONLY = [
    "Owner: [[PERSON|{PERSON_PLAIN}]]\nPhone: {PHONE}",
    "Ph [[PHONE|{LOCAL8}]] after 4pm.",
]


def phone_variants(rng: random.Random) -> str:
    mob = f"0491 57{rng.randint(0, 9)} {rng.randint(100, 999)}"
    d = mob.replace(" ", "")
    land_area = rng.choice(["02", "03", "07", "08"])
    l8 = f"5550 {rng.randint(1000, 9999)}"
    land = {
        "a": f"({land_area}) {l8}",
        "b": f"{land_area} {l8}",
        "c": f"{land_area}-{l8.replace(' ', '-')}",
        "d": f"{land_area} {l8.replace(' ', '')}",
        "e": f"+61 {land_area[1]} {l8}",
        "f": f"{land_area}{l8.replace(' ', '')}",
    }
    mobs = [mob, d, f"{d[:4]}-{d[4:7]}-{d[7:]}", f"+61 {d[1:4]} {d[4:7]} {d[7:]}", f"+61{d[1:]}", f"{d[:4]} {d[4:]}"]
    return rng.choice(mobs + list(land.values()))


def build(
    rng: random.Random, firsts, lasts, streets, suburbs, templates, body, n_pos: int, n_neg: int, prefix: str
) -> list[dict]:
    rows = []

    def name_plain() -> str:
        return f"{rng.choice(firsts)} {rng.choice(lasts)}"

    def addr_plain() -> str:
        number = f"{rng.randint(1, 199)}{rng.choice(['', '', '', 'A'])}"
        if rng.random() < 0.2:
            number = f"{rng.randint(1, 12)}/{rng.randint(1, 99)}"
        street = f"{rng.choice(streets)} {rng.choice(TYPES_LONG + TYPES_SHORT)}"
        sub, st, pc = rng.choice(suburbs)
        form = rng.choice(["comma", "plain", "nopost", "nl", "unit", "pobox"])
        if form == "comma":
            return f"{number} {street}, {sub} {st} {pc}"
        if form == "plain":
            return f"{number} {street} {sub} {st} {pc}"
        if form == "nopost":
            return f"{number} {street}"
        if form == "nl":
            return f"{number} {street}\n{sub} {st} {pc}"
        if form == "unit":
            return f"Unit {number} {street}, {sub} {st} {pc}".replace("Unit 1/", "Unit 1 ")
        return f"PO Box {rng.randint(10, 999)}, {sub} {st} {pc}"

    def email_plain(person: str | None = None) -> str:
        who = (person or name_plain()).lower().replace("'", "")
        local = rng.choice(
            [
                who.replace(" ", "."),
                who.replace(" ", ""),
                who.split()[0][0] + who.split()[1],
                who.replace(" ", "_") + rng.choice(["", "+tenders"]),
            ]
        )
        e = f"{local}@{rng.choice(DOMAINS)}"
        return e.upper() if rng.random() < 0.08 else e

    def fill(template: str) -> str:
        def sub(m: re.Match) -> str:
            slot, mod = m.group(1), m.group(2)
            if slot == "PERSON":
                v = name_plain()
                return f"[[PERSON|{v.upper() if mod == 'upper' else v}]]"
            if slot == "PERSON_PLAIN":
                return name_plain()
            if slot == "FIRST_ONLY":
                return rng.choice(firsts)
            if slot == "PHONE":
                return f"[[PHONE|{phone_variants(rng)}]]"
            if slot == "EMAIL":
                return f"[[EMAIL|{email_plain()}]]"
            if slot == "ADDR":
                return f"[[ADDRESS|{addr_plain()}]]"
            if slot == "LOCAL8":
                return f"{rng.randint(5000, 5999)} {rng.randint(1000, 9999)}"
            if slot == "LOCAL8_BARE":
                return f"{rng.randint(5000, 5999)}{rng.randint(1000, 9999)}"
            if slot == "EMAIL_AT":
                p = name_plain().lower().replace(" ", ".")
                return f"{p} at {rng.choice(DOMAINS).replace('.', ' dot ')}"
            if slot == "LOT_ADDR":
                return f"{rng.choice(streets)} Estate, {rng.choice(suburbs)[0]}"
            if slot == "LOWER_ADDR":
                return f"{rng.randint(1, 99)} {rng.choice(streets).lower()} {rng.choice(['street', 'road', 'drive'])}, {rng.choice(suburbs)[0].lower()}"
            raise KeyError(slot)

        out = re.sub(r"\{([A-Z0-9_]+)(?::(\w+))?\}", sub, template)
        return out

    for i in range(n_pos + n_neg):
        positive = i < n_pos
        lines = rng.sample(body, rng.randint(3, 6))
        if positive:
            for t in rng.sample(templates, rng.randint(1, 3)):
                lines.insert(rng.randint(0, len(lines)), fill(t))
        else:
            if rng.random() < 0.5:
                lines.insert(rng.randint(0, len(lines)), f"Contact: {rng.choice(COMPANIES)}, office hours only.")
        raw = "\n".join(lines)
        text, spans = parse_markup(raw)
        rows.append({"id": f"{prefix}{i + 1:03d}", "text": text, "spans": spans})
    return rows


MARK = re.compile(r"\[\[(PERSON|PHONE|EMAIL|ADDRESS)\|(.*?)\]\]", re.S)


def parse_markup(raw: str) -> tuple[str, list[dict]]:
    out, spans, last, pos = [], [], 0, 0
    for m in MARK.finditer(raw):
        out.append(raw[last : m.start()])
        pos += m.start() - last
        value = m.group(2)
        spans.append({"type": m.group(1), "start": pos, "end": pos + len(value), "value": value})
        out.append(value)
        pos += len(value)
        last = m.end()
    out.append(raw[last:])
    text = "".join(out)
    assert all(text[s["start"] : s["end"]] == s["value"] for s in spans)
    return text, spans


def main() -> None:
    dev = build(random.Random(20261120), FIRST_DEV, LAST_DEV, STREETS_DEV, SUBURBS_DEV, SHARED + DEV_ONLY, BODY, 24, 6, "d")
    test = build(
        random.Random(20261121),
        FIRST_TEST,
        LAST_TEST,
        STREETS_TEST,
        SUBURBS_TEST,
        SHARED + TEST_ONLY + TEST_ONLY,
        BODY + TEST_BODY + TEST_BODY,
        64,
        16,
        "t",
    )
    for name, rows in (("pii_dev", dev), ("pii_test", test)):
        (OUT / f"{name}.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
        by = {}
        for r in rows:
            for s in r["spans"]:
                by[s["type"]] = by.get(s["type"], 0) + 1
        print(name, len(rows), "tenders", by)


if __name__ == "__main__":
    main()
