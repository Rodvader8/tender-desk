"""Seed the database with INVENTED data. No real business, supplier or client is represented.

Deterministic: the same seed always produces the same rows, so evaluation numbers are repeatable.
Run: uv run python scripts/seed.py
"""

import random
from datetime import date, timedelta

from tender_desk.db import connect
from tender_desk.embed import embed

rng = random.Random(42)

# (category, name, unit, base price AUD)
CATALOGUE = [
    ("concrete", "Concrete 25MPa ready-mix", "m3", 285),
    ("concrete", "Concrete 32MPa ready-mix", "m3", 305),
    ("concrete", "Reinforcing mesh SL82 6m x 2.4m", "sheet", 62),
    ("concrete", "Reinforcing bar N12 12m", "length", 38),
    ("concrete", "Formwork hire per lineal metre", "m", 14),
    ("concrete", "Vapour barrier membrane 200um", "m2", 3.4),
    ("concrete", "Concrete pump hire per half day", "each", 780),
    ("concrete", "Concrete slab finishing labour", "m2", 24),
    ("earthworks", "Excavator hire 8t with operator", "hour", 145),
    ("earthworks", "Site cut and level", "m2", 18),
    ("earthworks", "Compacted road base 20mm", "m3", 62),
    ("earthworks", "Soil removal to tip", "m3", 58),
    ("earthworks", "Tipper truck hire", "hour", 128),
    ("earthworks", "Sediment fencing", "m", 9.5),
    ("steel", "Structural steel beam 200UB25", "m", 118),
    ("steel", "Structural steel column 150PFC", "m", 96),
    ("steel", "Steel lintel 150x90x8 angle", "m", 41),
    ("steel", "Base plate and fixings set", "each", 87),
    ("steel", "Steel erection labour", "hour", 98),
    ("steel", "Shop drawings and certification", "each", 640),
    ("timber", "Treated pine framing 90x45 MGP10", "m", 7.6),
    ("timber", "Treated pine framing 140x45 MGP10", "m", 11.8),
    ("timber", "LVL beam 240x45", "m", 38),
    ("timber", "Roof truss supply and install", "m2", 62),
    ("timber", "Plywood structural floor 19mm", "m2", 48),
    ("timber", "Hardwood decking 86x19", "m", 14.5),
    ("timber", "Carpenter labour", "hour", 92),
    ("timber", "Wall frame prefabricated", "m2", 71),
    ("roofing", "Colorbond roof sheeting supply and fix", "m2", 69),
    ("roofing", "Roof insulation R3.5 batts", "m2", 22),
    ("roofing", "Gutter and downpipe set", "m", 36),
    ("roofing", "Sarking foil", "m2", 4.8),
    ("roofing", "Roof plumber labour", "hour", 105),
    ("roofing", "Ridge capping", "m", 19),
    ("masonry", "Common brick laid", "each", 2.35),
    ("masonry", "Concrete block 190 laid", "each", 5.9),
    ("masonry", "Brick tie and damp course set", "m", 8.2),
    ("masonry", "Bricklayer labour", "hour", 89),
    ("masonry", "Render and finish", "m2", 52),
    ("masonry", "Retaining wall block system", "m2", 168),
    ("plumbing", "Copper pipe 20mm", "m", 24),
    ("plumbing", "PVC stormwater pipe 100mm", "m", 12.5),
    ("plumbing", "Hot water system 250L electric", "each", 1480),
    ("plumbing", "Floor waste and fixtures set", "each", 365),
    ("plumbing", "Plumber labour", "hour", 108),
    ("plumbing", "Sewer connection and inspection", "each", 1850),
    ("electrical", "Cable TPS 2.5mm", "m", 3.1),
    ("electrical", "Switchboard 12 circuit", "each", 780),
    ("electrical", "Downlight LED supply and install", "each", 74),
    ("electrical", "Power point double supply and install", "each", 88),
    ("electrical", "Electrician labour", "hour", 112),
    ("electrical", "Smoke alarm interconnected", "each", 96),
    ("finishes", "Plasterboard 10mm fix and set", "m2", 43),
    ("finishes", "Internal paint two coats", "m2", 19),
    ("finishes", "Floor tiles supply and lay", "m2", 112),
    ("finishes", "Waterproofing membrane wet area", "m2", 58),
    ("finishes", "Painter labour", "hour", 79),
    ("finishes", "Kitchen cabinetry standard", "m", 1250),
    ("plant", "Scaffold hire per week", "week", 620),
    ("plant", "Site toilet hire per week", "week", 65),
    ("plant", "Skip bin 6m3", "each", 430),
    ("plant", "Crane truck hire", "hour", 185),
    ("preliminaries", "Site supervisor", "day", 780),
    ("preliminaries", "Building permit and fees", "each", 2650),
    ("preliminaries", "Insurance and compliance allowance", "each", 1180),
    ("preliminaries", "Survey and set out", "each", 1450),
]
SUPPLIERS = ["Northgate Supply", "Harbour Building Products", "Ridgeline Trade", "Summit Materials", "Coastline Hire"]

# Job templates: title, description, [(category, share of lines)]
JOBS = [
    (
        "Rear extension",
        "Single storey rear extension with slab on ground, timber frame, colorbond roof, plasterboard and paint",
        ["concrete", "timber", "roofing", "finishes", "electrical", "plumbing"],
    ),
    (
        "Garage and carport",
        "Detached double garage with concrete slab, block walls and steel roller door frame",
        ["concrete", "masonry", "steel", "roofing", "electrical"],
    ),
    (
        "Retaining wall and drainage",
        "Concrete block retaining wall with stormwater drainage and compacted base",
        ["earthworks", "masonry", "concrete", "plumbing"],
    ),
    (
        "Warehouse fit-out",
        "Light industrial warehouse fit-out with steel mezzanine, switchboard upgrade and lighting",
        ["steel", "electrical", "finishes", "plant"],
    ),
    (
        "Second storey addition",
        "Second storey addition over existing dwelling with LVL floor beams, new stair and wet areas",
        ["timber", "steel", "roofing", "finishes", "plumbing", "electrical"],
    ),
    (
        "Site preparation",
        "Cut and level for a commercial pad with sediment control and road base",
        ["earthworks", "plant", "preliminaries"],
    ),
    (
        "Granny flat",
        "Self-contained secondary dwelling with kitchenette, bathroom and covered deck",
        ["concrete", "timber", "roofing", "finishes", "plumbing", "electrical", "preliminaries"],
    ),
    (
        "Commercial kitchen refit",
        "Strip out and refit of a commercial kitchen with waterproofing, tiling and services",
        ["plumbing", "electrical", "finishes", "plant"],
    ),
]


def main() -> None:
    conn = connect()
    with conn.transaction():
        conn.execute("TRUNCATE past_quote_lines, past_quotes, price_items RESTART IDENTITY CASCADE")
        names = [f"{c} {n}" for c, n, _, _ in CATALOGUE]
        vecs = embed(names)
        ids = {}
        for i, ((cat, name, unit, base), vec) in enumerate(zip(CATALOGUE, vecs, strict=True), start=1):
            price = round(base * rng.uniform(0.93, 1.08), 2)
            row = conn.execute(
                "INSERT INTO price_items (sku, name, category, unit, unit_price, supplier, embedding) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (f"SKU{i:04d}", name, cat, unit, price, rng.choice(SUPPLIERS), vec),
            ).fetchone()
            ids[(cat, name)] = (row[0], price)
        by_cat: dict[str, list] = {}
        for (cat, _name), v in ids.items():
            by_cat.setdefault(cat, []).append(v)

        descs = []
        quotes = []
        for n in range(30):
            title, desc, cats = JOBS[n % len(JOBS)]
            size = rng.choice([0.6, 0.8, 1.0, 1.3, 1.7])
            lines = []
            for cat in cats:
                for pid, price in rng.sample(by_cat[cat], k=min(len(by_cat[cat]), rng.randint(2, 4))):
                    lines.append((pid, round(rng.uniform(3, 60) * size, 2), price))
            cost = sum(q * p for _, q, p in lines)
            margin = round(rng.uniform(12, 24), 2)
            total = round(cost * (1 + margin / 100), 2)
            quotes.append(
                (
                    f"{title} #{n + 1}",
                    f"{desc}. Scale {size}x.",
                    total,
                    margin,
                    date(2025, 1, 1) + timedelta(days=rng.randint(0, 600)),
                    lines,
                )
            )
            descs.append(f"{title}. {desc}")
        for q, vec in zip(quotes, embed(descs), strict=True):
            qid = conn.execute(
                "INSERT INTO past_quotes (title, description, total, margin_pct, quoted_on, embedding) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                (*q[:5], vec),
            ).fetchone()[0]
            for pid, qty, _ in q[5]:
                conn.execute("INSERT INTO past_quote_lines (quote_id, price_item_id, qty) VALUES (%s,%s,%s)", (qid, pid, qty))
    n_items = conn.execute("SELECT count(*) FROM price_items").fetchone()[0]
    n_q = conn.execute("SELECT count(*) FROM past_quotes").fetchone()[0]
    n_l = conn.execute("SELECT count(*) FROM past_quote_lines").fetchone()[0]
    print(f"seeded {n_items} price items, {n_q} past quotes, {n_l} quote lines")


if __name__ == "__main__":
    main()
