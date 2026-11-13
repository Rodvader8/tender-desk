# Written before the spec checker existed

Problem: when the exact size or grade isn't in the catalogue, a model can quietly quote the nearest wrong one (N16 bar priced as N12, 400 L hot water priced as 250 L).

Plan: a deterministic check in code, no model. It pulls typed spec tokens (MPa, mm, litres, N-bar grade, SL mesh, R-value, UB and PFC sections, dimensions like 140x45, microns) out of the tender line and out of the chosen item's name. If the tender line and the item both carry a spec of the same type and the values differ, the pick is rejected and flagged. Numbers that are quantities or areas (m2, m3, weeks, hours, "8 off") are ignored by design.

Test: `evals/spec_pairs.jsonl`, 24 conflict pairs and 38 same-spec pairs written in different spellings ("25 meg", "20 mil", "R 3.5", "200 UB 25"). Scored once.

Success criteria:
- at least 90% of conflict pairs caught,
- at most 1 same-spec pair wrongly flagged,
- re-running the selection eval on `holdout2`: zero false matches on the near-miss negatives for both models, and no more than one fewer correct real query than before.

Known gap I expect before running: item names with a bare number and no unit ("Concrete block 190 laid"). Pair s024 tests it and is expected to be missed. Whatever the result, every miss is listed in the README.
