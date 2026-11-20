# Written before any v3 code and before the v3 sets were scored

Why this exists: detector v1 (rules) failed 4 of its 8 per-type criteria and the false-positive limit on `pii_test.jsonl`, and the Privacy Filter (v2) was better at names and worse at phones and at the ABN/1300/1800 policy (`PREREGISTRATION_PII.md`, README section 6). `pii_test.jsonl` has now been looked at twice, so any change tuned against it would be fitting to it. v3 is built against new sets and scored once on a new test set. The v1 and v2 numbers stay in the README unamended.

## What v3 is

Two things, scored separately:

**v3 rules** (this replaces v1 in the app; v1 is kept as `src/tender_desk/evals/redact_v1.py` so its published result still reproduces). Changes, each aimed at a miss or false positive seen in the v1 test results:

- Phones: a negative cue (`part`, `code`, `sku`, `ref`, `item`, `order`, `invoice`, `job`, `quote`, `drawing`, `serial`, `no.`, `#`) just before a digit run stops it being read as a phone number. An 8-digit local number counts when a phone cue (`ph`, `phone`, `tel`, `mob`, `call`, `ring`, `office`, `home`, `after hours`) sits within two words before it.
- Addresses: more street types (Boulevard, Esplanade, Grove, Mews, Parkway, Rise, Retreat, Promenade, Chase, Walk, Row, Highway); street names of one to four words; `Lot N` and `Unit N,` forms; `Lot N Name Estate[, Suburb]`; a lower-case street accepted only when a suburb or state follows. A bare street with no state or postcode is rejected when the next word is lower case or a trade noun (`base layers`, `Pavers`, `Markers`).
- Emails: the written-out form `name at domain dot com`.
- Names: more cues (`Owner:`, `Prepared by:`, `Contact name:`, `Name:`, `Site manager:`, `Supervisor:`, `Signed`, `From:`); a capitalised name followed by a role in brackets or after a comma (`(owner)`, `, the owner`); a verb cue (`ring`, `call`, `ask for`, `speak to`, `meet`, `arrange access with`) before a name, with an optional role word in between; after a full name is found, its first name and surname on their own are caught later in the same tender, unless the word is on a stop list.

**v3 hybrid** (evaluated offline, not wired into the app: it needs torch and a 2.8 GB model). PERSON spans are the union of the v3 rules and the Privacy Filter's `private_person`; EMAIL, PHONE and ADDRESS come from the v3 rules only. A model PERSON span is dropped if it contains a company or filler word, or if it overlaps a rules span of another type. Nothing is tuned for the model; it runs as it did for v2.

The app gets a hook (`extra_detectors`) so a model can be added later. It is off, and covered by a test using a stand-in.

## Sets

Invented data only, spans labelled by construction, built by `scripts/make_pii_sets_v3.py` with fixed seeds. Names, streets and suburbs don't overlap with the earlier sets or with each other.

- `evals/pii_dev3.jsonl`: 40 tenders, for tuning the v3 rules. The v3 hybrid isn't run on it.
- `evals/pii_test3.jsonl`: 100 tenders (20 with no personal data, only near misses). Scored once for the rules and once for the hybrid. About a third of its templates never appear in dev3. It contains new near-miss strings that dev3 doesn't, including some a negative-cue rule should catch and some it shouldn't.

Mobile numbers are in the `0491 57x xxx` fictional block, landlines use exchange `5550`. Scoring is unchanged: recall needs every character of a span covered by a same-type prediction, precision needs overlap with a same-type labelled span.

## Success criteria, on test3

| Type | v3 rules recall / precision at least | v3 hybrid recall / precision at least |
|---|---|---|
| Email | 0.95 / 0.95 | same (rules only) |
| Phone | 0.95 / 0.95 | same (rules only) |
| Address | 0.80 / 0.80 | same (rules only) |
| Person | 0.75 / 0.90 | 0.90 / 0.90 |

and no more than 3 false positives across the 20 tenders with no personal data, and none of them an ABN, ACN, 1300, 1800 or 13 xx xx number.

I expect the rules to miss: names with no cue and no verb and no role word; first names alone before any full name; an address in a layout I haven't thought of; and any 10-digit code starting `02`/`03`/`04` with no negative cue before it. I expect the hybrid to fix most name misses and to add a few false positives on company staff titles and trade terms.

Rules for changing things: v3 rules may change after dev3 results and never after test3. Anything changed after the test3 run goes in an amendment below, with the unamended numbers kept in the README.

## Amendment before the test3 run

Found while writing the unit tests, on dev3 and a stand-in model only: a model PERSON span can land on a number such as an ABN. A model PERSON span containing a digit is now dropped too, as part of the same policy filter. Nothing has been scored on test3 yet.
