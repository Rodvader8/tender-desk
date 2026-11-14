import json
from pathlib import Path

from tender_desk.specs import spec_conflicts, spec_tokens

PAIRS = [json.loads(line) for line in (Path(__file__).parents[1] / "evals" / "spec_pairs.jsonl").read_text().splitlines()]
KNOWN_GAP = {"s024"}  # item name has a bare number with no unit, so it carries no typed spec


def test_no_same_spec_pair_is_flagged():
    assert [r["id"] for r in PAIRS if r["expect"] == "ok" and spec_conflicts(r["query"], r["item"])] == []


def test_conflicting_pairs_are_caught_except_the_documented_gap():
    missed = {r["id"] for r in PAIRS if r["expect"] == "conflict" and not spec_conflicts(r["query"], r["item"])}
    assert missed == KNOWN_GAP


def test_spellings_and_site_dimensions():
    assert ("mpa", "25") in spec_tokens("25 meg ready mix") and ("mm", "20") in spec_tokens("20 mil road base")
    assert ("ub", "200ub25") in spec_tokens("200 UB 25 beam") and ("r", "3.5") in spec_tokens("R 3.5 batts")
    assert ("dim", "140x45") in spec_tokens("wall framing 6 x 3 m, 140x45 pine")
    assert not [t for t in spec_tokens("wall framing 6 x 3 m") if t[0] == "dim"]  # site size, not a section
    assert spec_tokens("36 m2 footprint, 3 weeks, 8 off") == []  # quantities are not specs


def test_message_names_both_sides():
    (msg,) = spec_conflicts("N16 bar", "Reinforcing bar N12 12m")
    assert "16" in msg and "12" in msg


def test_three_digit_sl_mesh_is_read():
    """Found by the fresh agent evaluation: 'SL102 reo mesh' was priced as SL82 because only two digits were read."""
    assert ("sl", "102") in spec_tokens("SL102 reo mesh") and ("sl", "82") in spec_tokens("Reinforcing mesh SL82 6m x 2.4m")
    assert spec_conflicts("SL102 reo mesh", "Reinforcing mesh SL82 6m x 2.4m")
    assert not spec_conflicts("SL82 mesh to the slab", "Reinforcing mesh SL82 6m x 2.4m")
