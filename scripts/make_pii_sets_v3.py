"""Build the v3 PII evaluation sets (evals/pii_dev3.jsonl, evals/pii_test3.jsonl). All data is invented.

Same idea as make_pii_sets.py: templates with slots, spans labelled by construction, plain text never labelled. New names, streets,
suburbs, layouts and near misses, so the earlier sets (already looked at) are not reused.
Run: python scripts/make_pii_sets_v3.py
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

from make_pii_sets import DOMAINS, TYPES_LONG, TYPES_SHORT, parse_markup, phone_variants

OUT = Path(__file__).resolve().parents[1] / "evals"

FIRST_DEV = ["Tamsin", "Hugo", "Yusuf", "Mei-Ling", "Declan", "Ottilie", "Rafael", "Sunita", "Callum", "Bianca"]
LAST_DEV = [
    "Abernethy",
    "Castellano",
    "Nguyen",
    "O'Connell",
    "Strand",
    "Pereira",
    "Whitaker",
    "Mukherjee",
    "De Souza",
    "Kavanagh",
]
FIRST_TEST = [
    "Jean-Luc",
    "Odette",
    "Kwame",
    "Saoirse",
    "Leilani",
    "Bartek",
    "Wilhelmina",
    "Taj",
    "Greta",
    "Ruben",
    "Nadia",
    "Harlan",
]
LAST_TEST = [
    "Ng",
    "Beaumont",
    "Asante",
    "Fairweather",
    "Ramos",
    "Zielinski",
    "Thorsen",
    "McGregor",
    "Oyelaran",
    "Pellegrini",
    "Hargreaves",
    "Kapoor",
]
STREETS_DEV = ["Mount Pleasant", "Old Northern", "Silverton", "Jacaranda", "Harbour View"]
STREETS_TEST = ["Eucalypt", "Great Western", "Blue Gum", "Pelican", "Heritage Oak", "Dunmore"]
TYPES_NEW = [
    "Boulevard",
    "Esplanade",
    "Grove",
    "Mews",
    "Parkway",
    "Rise",
    "Retreat",
    "Promenade",
    "Chase",
    "Walk",
    "Row",
    "Highway",
]
SUBURBS_DEV = [("Bondi Junction", "NSW", "2022"), ("Carlton", "VIC", "3053"), ("Toowong", "QLD", "4066")]
SUBURBS_TEST = [
    ("Subiaco", "WA", "6008"),
    ("Unley", "SA", "5061"),
    ("Bathurst", "NSW", "2795"),
    ("Brunswick", "VIC", "3056"),
    ("Southport", "QLD", "4215"),
]
COMPANIES = [
    "Silverton Roofing Pty Ltd",
    "Jacaranda Landscapes Pty Ltd",
    "Harbour View Electrical",
    "Eucalypt Earthworks Pty Ltd",
    "Dunmore Concrete Pumping",
]

BODY = [
    "Scope: new carport, 18 m2 slab, 6 posts and a skillion roof.",
    "ABN 28 614 092 337, builder licence 41206C.",
    "Enquiries on 1300 700 412 or 1800 700 413 during business hours.",
    "Tender no. 2026-0877, issued 02/11/2026, due 20/11/2026.",
    "Excavate 340 m3, cart away 410 m3 of spoil, 22 loads.",
    "Lot 9 DP 774201, shire reference DA 2026/1190.",
    "Wiring: 32 power points, 21 LED downlights, 4 ceiling fans.",
    "Allow 6 weeks from approval. Payment 30 days from invoice.",
    "Contact: Silverton Roofing Pty Ltd for roof access.",
    "Contact: Jacaranda Landscapes Pty Ltd, site clean-up crew.",
    "Slab 100 mm thick, 32 MPa, SL82 mesh, 450 m2 total.",
    "Supply 60 pavers, 300 x 300 mm, laid to falls.",
    "Deliver to the compound gate, between 6 and 8 each morning.",
    "Hot water unit 315 L, R3.5 batts to the ceiling, 120 m2.",
    "Retention 5 percent. Variations by written instruction only.",
    "Pressure test at 1200 kPa for 15 minutes.",
]
TEST_BODY = [
    "SKU 0312 884 120, 40 brackets. Part no. 0245 667 310 for the hinges.",
    "Invoice 0418 220 305 settled 14/11/2026.",
    "Install 8 Walk-in robes and 2 Esplanade Lighting poles.",
    "Match the 14 Grove Street style balusters to the old rail.",
    "ABN 61 119 442 780 (GST registered), ACN 119 442 780.",
    "Quote valid 45 days. Drawing 5120-07 rev C, sheet 3 of 11.",
    "Allow 25 Chase Bank style bollards at the entry.",
    "Order 120 m of 90 mm pipe, 48 elbows and 6 Walk Row brackets.",
    "Fire panel test every 6 months, report within 14 days.",
]

SHARED = [
    "Attn: {PERSON}\nPhone: {PHONE}",
    "Contact: {PERSON} on {PHONE}.",
    "Owner: {PERSON}\nMobile {PHONE}",
    "Prepared by: {PERSON}. Questions to {EMAIL}.",
    "Mr {PERSON} will meet you on site. Mobile {PHONE}.",
    "Ms {PERSON}, {EMAIL}",
    "Dr. {PERSON} owns the property at {ADDR}.",
    "Mrs. {PERSON} will be home all week.",
    "Regards,\n{PERSON}\n{PHONE}",
    "Kind regards\n{PERSON}\nSite Manager\n{EMAIL}",
    "Send the quote to {PERSON} ({EMAIL}), phone {PHONE}.",
    "Site is at {ADDR}.",
    "Property: {ADDR}. Access by arrangement, call {PHONE}.",
    "Tender returns to {EMAIL} or post to {ADDR}.",
    "Site contact: {PERSON} ({PHONE})",
    "Contact name: {PERSON}\nTel: {PHONE}\nEmail: {EMAIL}",
    "Ring the owner {PERSON_FIRST} before 8am on {PHONE}.",
    "Arrange access with {PERSON} (owner) before 8am.",
    "Call [[PHONE|{LOCAL8}]] for the gate code.",
    "Ph [[PHONE|{LOCAL8}]] after 4pm.",
    "Unit [[ADDRESS|{UNIT_ADDR}]]",
]
TEST_ONLY = [
    "Ask for {PERSON}, the site supervisor, on {PHONE}.",
    "Speak to {PERSON} first, then {PERSON}. Mobile {PHONE}.",
    "Signed {PERSON}\n{ADDR}",
    "From: {PERSON} <{EMAIL}>",
    "Name: {PERSON}\nOffice [[PHONE|{LOCAL8}]]",
    "Supervisor: {PERSON} ({PHONE})",
    "Lot [[ADDRESS|{LOT_ADDR}]]",
    "Job address: [[ADDRESS|{LOWER_ADDR}]]",
    "Reach the owner at [[EMAIL|{EMAIL_AT}]].",
    "Please phone the office on [[PHONE|{LOCAL8}]] to book the inspection.",
    "Liaise with {PERSON} ({PHONE}). Later, {PERSON_FIRST} will confirm.",
    "Meet {PERSON} at {ADDR} on Monday.",
    "[[PERSON|{PERSON_PLAIN}]] is the contact for access.",
    "Client contact: {PERSON}, {EMAIL}",
]
DEV_ONLY = [
    "Ring the owner {PERSON_FIRST} before 8am on {PHONE}.",
    "Lot [[ADDRESS|{LOT_ADDR}]]",
    "Reach the owner at [[EMAIL|{EMAIL_AT}]].",
]


def extra_phone(rng: random.Random) -> str:
    d = f"0491 57{rng.randint(0, 9)} {rng.randint(100, 999)}".replace(" ", "")
    return rng.choice(
        [
            f"{d[:2]} {d[2:6]} {d[6:]}",
            f"{d[:4]}.{d[4:7]}.{d[7:]}",
            f"+61 (0){d[1:4]} {d[4:7]} {d[7:]}",
            phone_variants(rng),
            phone_variants(rng),
        ]
    )


def build(rng, firsts, lasts, streets, suburbs, templates, body, n_pos, n_neg, prefix):
    rows = []

    def person_plain() -> str:
        return f"{rng.choice(firsts)} {rng.choice(lasts)}"

    def street() -> str:
        return f"{rng.choice(streets)} {rng.choice(TYPES_LONG + TYPES_SHORT + TYPES_NEW)}"

    def addr() -> str:
        number = f"{rng.randint(1, 240)}{rng.choice(['', '', 'A', 'B'])}"
        sub, st, pc = rng.choice(suburbs)
        form = rng.choice(["comma", "plain", "nl", "unit", "lotroad", "pobox", "comma"])
        if form == "comma":
            return f"{number} {street()}, {sub} {st} {pc}"
        if form == "plain":
            return f"{number} {street()} {sub} {st} {pc}"
        if form == "nl":
            return f"{number} {street()}\n{sub} {st} {pc}"
        if form == "unit":
            return f"Unit {rng.randint(1, 30)}, {number} {street()}, {sub} {st} {pc}"
        if form == "lotroad":
            return f"Lot {rng.randint(1, 80)} {street()}, {sub} {st} {pc}"
        return f"PO Box {rng.randint(10, 990)}, {sub} {st} {pc}"

    def email(person: str | None = None) -> str:
        who = (person or person_plain()).lower().replace("'", "").replace("-", "")
        local = rng.choice(
            [who.replace(" ", "."), who.replace(" ", ""), who.split()[0][0] + who.split()[-1], who.replace(" ", "_")]
        )
        return f"{local}@{rng.choice(DOMAINS)}"

    def fill(t: str) -> str:
        def sub(m: re.Match) -> str:
            slot = m.group(1)
            if slot == "PERSON":
                return f"[[PERSON|{person_plain()}]]"
            if slot == "PERSON_FIRST":
                return f"[[PERSON|{rng.choice(firsts)}]]"
            if slot == "PERSON_PLAIN":
                return person_plain()
            if slot == "PHONE":
                return f"[[PHONE|{extra_phone(rng)}]]"
            if slot == "EMAIL":
                return f"[[EMAIL|{email()}]]"
            if slot == "ADDR":
                return f"[[ADDRESS|{addr()}]]"
            if slot == "LOCAL8":
                return f"{rng.randint(5000, 5999)} {rng.randint(1000, 9999)}"
            if slot == "UNIT_ADDR":
                s, st, pc = rng.choice(suburbs)
                return f"{rng.randint(1, 40)}/{rng.randint(1, 99)} {street()}, {s} {st} {pc}"
            if slot == "LOT_ADDR":
                if rng.random() < 0.5:
                    return f"{rng.randint(1, 60)} {rng.choice(streets)} Estate, {rng.choice(suburbs)[0]}"
                s, st, pc = rng.choice(suburbs)
                return f"{rng.randint(1, 60)} {street()}, {s} {st} {pc}"
            if slot == "LOWER_ADDR":
                return f"{rng.randint(1, 99)} {rng.choice(streets).lower()} {rng.choice(['street', 'road', 'drive'])}, {rng.choice(suburbs)[0].lower()}"
            if slot == "EMAIL_AT":
                p = person_plain().lower().replace(" ", ".").replace("'", "").replace("-", "")
                return f"{p} at {rng.choice(DOMAINS).replace('.', ' dot ')}"
            raise KeyError(slot)

        return re.sub(r"\{([A-Z0-9_]+)\}", sub, t)

    for i in range(n_pos + n_neg):
        lines = rng.sample(body, rng.randint(3, 6))
        if i < n_pos:
            for t in rng.sample(templates, rng.randint(1, 3)):
                lines.insert(rng.randint(0, len(lines)), fill(t))
        elif rng.random() < 0.5:
            lines.insert(rng.randint(0, len(lines)), f"Contact: {rng.choice(COMPANIES)}, office hours only.")
        text, spans = parse_markup("\n".join(lines))
        rows.append({"id": f"{prefix}{i + 1:03d}", "text": text, "spans": spans})
    return rows


def main() -> None:
    dev = build(random.Random(20261122), FIRST_DEV, LAST_DEV, STREETS_DEV, SUBURBS_DEV, SHARED + DEV_ONLY, BODY, 32, 8, "e")
    test = build(
        random.Random(20261123),
        FIRST_TEST,
        LAST_TEST,
        STREETS_TEST,
        SUBURBS_TEST,
        SHARED + TEST_ONLY,
        BODY + TEST_BODY,
        80,
        20,
        "u",
    )
    for name, rows in (("pii_dev3", dev), ("pii_test3", test)):
        (OUT / f"{name}.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
        by: dict[str, int] = {}
        for r in rows:
            for s in r["spans"]:
                by[s["type"]] = by.get(s["type"], 0) + 1
        print(name, len(rows), by)


if __name__ == "__main__":
    main()
