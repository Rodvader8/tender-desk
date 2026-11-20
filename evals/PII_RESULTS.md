# Personal data redaction: full results

This is the long version of README section 6, moved here so the README stays short. Criteria were set in `PREREGISTRATION_PII.md`, `PREREGISTRATION_PII_V3.md` and `PREREGISTRATION_PII_INDEPENDENT.md` before each run. Result files are in `results/` and checksummed. Where a later amendment changed a rule, the amendment is in the pre-registration and the unamended numbers are kept.

**In short.** Before the model reads a tender, names, phone numbers, emails and street addresses are swapped for placeholders (`[PERSON_1]`). The code puts the real values back in the draft the reviewer sees, and logs only counts. Tests check that no real value reaches the model call, the audit log, the run trace, the logs or the metrics.

| detector | names | phones | emails | addresses | where it runs |
|---|---|---|---|---|---|
| v3 rules (**in the app**) | 87% found | 100% | 100% | 100% | always; no model, instant |
| v3 hybrid (rules + local Privacy Filter model) | 97% found | 100% | 100% | 100% | offline experiment; about 11 s a tender on CPU |

Recall on `pii_test3.jsonl`, 100 invented tenders I wrote, scored once, criteria set in advance. Precision was 100% and clean tenders raised no false alarms. **Read this with care:** the data is invented and written by me, so these numbers show the rules cover the layouts I thought of, not what real tenders would score. The first version (v1) failed its criteria on an earlier set (names 68%, addresses 62% found, 17 false alarms on 16 clean tenders), and those results are kept below. On a rough set of messy, deliberately hostile text that I wrote afterwards, the same rules found only 23% of names and 63 to 75% of other values (details below). It isn't anonymisation: a missed value goes to the model. Australian formats only.

The rest of this section is the detail: policy, method, the three detector rounds with every table, and the limits.

A tender can carry a site contact's name, a mobile number, an email, a home address. The model doesn't need any of it to price a job, and the model provider would otherwise see it. A redaction step now runs before `extract`. What the model reads is the tender with those values swapped for placeholders; the same value always gets the same placeholder inside one tender. Everything downstream that the model writes (job summary, line descriptions) can carry a placeholder, and the code swaps the real value back in when it builds the draft. Reviewer notes typed on a rejection go through the same step before they reach the model.

**Policy.** Personal means a person's name, phone, email or street address. Company names, ABNs and ACNs, `1300`/`1800`/`13 xx xx` numbers and a bare suburb or postcode are business or public details and are not redacted. Quantities, part numbers and the work itself are never touched.

**What gets logged.** Counts per type, in the audit log (`pii_redacted`: `{"person": 3, "phone": 1, ...}`), as a `redact` step in the run trace, and as a Prometheus counter by type. Never a value, and never the placeholder map, which isn't stored anywhere: it's rebuilt from the tender text the database already holds. A title typed with a name in it is redacted in its audit entry too. Tests assert all of this: they read the scripted model's received prompts, every audit row, every run step, the log records and the metrics text, and fail if any seeded name, number, email or address appears.

**Detector v1: rules, no model.** Emails; AU mobiles and landlines with a digit count check (so `ABN 51 824 753 556`, `12,500 m2` and `04/11/2026` aren't flagged); street addresses (number, street name, street type, optional suburb, state, postcode) and PO boxes; names only after a cue (`Attn:`, `Contact:`, `Site contact:`, `Mr`, `Ms`, `Mrs`, `Miss`, `Dr`, `Regards`, `Kind regards`, `Thanks`, `Cheers`) plus later repeats of the same full name.

**How it was measured.** `evals/PREREGISTRATION_PII.md` was committed with the frozen sets before any detector code existed. Both sets are invented and built by `scripts/make_pii_sets.py` from templates, so every labelled span is exact: 30 tuning tenders and 80 test tenders (16 with no personal data at all, only near misses). The test set uses different names and streets from the tuning set, and about two thirds of its contact templates (counting how often they're drawn) never appear in the tuning set. Recall counts a span as found only if every character of it is covered, because half a phone number is still a leak. Precision counts a predicted span as correct if it overlaps a labelled span of the same type. The test set was scored once, with the rules as they were committed, and the result file is checksummed.

Test set, rules v1, pre-registered criteria beside each number:

| type | labelled | recall | needed | precision | needed | met? |
|---|---|---|---|---|---|---|
| email | 29 | **0.931** | 0.95 | 1.000 | 0.95 | recall **missed** |
| phone | 91 | **0.978** | 0.90 | **0.840** | 0.90 | precision **missed** |
| address | 32 | **0.625** | 0.80 | **0.333** | 0.90 | both **missed** |
| person | 114 | **0.684** | 0.60 | 1.000 | 0.80 | met |

False positives on the 16 tenders with no personal data: **17** (limit was 2). 38 of 80 tenders had at least one missed value. So v1 meets 4 of its 8 per-type criteria and misses the other 4 and the false-positive limit; I'm reporting it as failed rather than moving the goalposts. On the tuning set it scored 0.84 recall for names and 1.0 on everything else, which says the tuning set was too easy and the rules were fitted to it.

Where the misses come from (test set, 52 labelled values missed):

| misses | cause |
|---|---|
| 8 | person after `Owner:`, which isn't one of the cues |
| 5 | person after `Prepared by:`, not a cue |
| 8 | person introduced with no cue ("arrange access with Priya Nair, the owner") |
| 7 | a first name on its own ("ring the site foreman Esther") |
| 8 | person in a layout with no cue ("send the quote to ...", or the second name in "Contact A, then B") |
| 8 | "Lot 5 Cormorant Estate, Kenmore" style addresses with no street number and type |
| 4 | address typed in lower case |
| 2 | an 8-digit local number with no `ph`/`mobile` cue |
| 2 | email written out as "name at gmail dot com" |

I predicted all of these before running, in the pre-registration. The test set was built to contain them on purpose, more than a third of the contact templates drawn are hard ones, so these rates describe a deliberately awkward set. They are not an estimate of how often real tenders leak. I haven't measured real tenders and have none.

The false positives are three strings that I planted as near misses and repeated across the set, which makes the precision look worse than three mistakes would: `0245 123 456` (a 10-digit hinge code, indistinguishable from a Sydney landline by digits alone), `12 Boundary Road base layers` and `2 Park Lane Pavers` (number, capitalised word, street type: that's what an address looks like). A rule can't tell these apart from real addresses without knowing the trade vocabulary. The cost of a false positive here is small and visible: the model sees `[ADDRESS_1]` where it would have seen a scope phrase, and the reviewer still sees the original text restored in the draft.

What a miss means: the model sees the value. This reduces what leaves the server; it doesn't guarantee that nothing does.

**Detector v2: OpenAI's open-source Privacy Filter, same test set, same scoring.** Apache 2.0, run locally on CPU through `scripts/score_pii_v2.py` (needs torch and a 2.8 GB download, so it isn't in the app or CI). Its person, phone, email and address labels are mapped to ours; its other labels are ignored. Not tuned or changed in any way. Scored once.

| type | v1 rules recall / precision | v2 Privacy Filter recall / precision |
|---|---|---|
| email | 0.931 / 1.000 | **0.966** / 1.000 |
| phone | **0.978** / 0.840 | 0.868 / **0.888** |
| address | **0.625** / 0.333 | **0.688** / **0.437** |
| person | 0.684 / **1.000** | **0.965** / 0.991 |
| tenders with a miss (of 80) | 38 | **20** |
| false positives on the 16 clean tenders | 17 | **4** |

Neither beats the other everywhere. The model is far better at names (110 of 114 found, including names with no cue word, which v1 can't do by design), and it also catches a few emails and lower-case addresses that v1's rules miss. The rules are better at phone numbers: the model missed 12 of 91, mostly 8-digit local numbers (`5472 6625`) and a few mobiles written with no spaces or a `+61` prefix (`0491575103`, `+61491575843`), and it flagged an ABN, a 1800 number and a drawing number as phones or addresses, which breaks the policy above. Its address precision is poor for the same reason as v1's: `2 Park Lane Pavers`, `12 Boundary Road`, and also scope text like `32 MPa, 300 mm wide` and `6 Lane markers and 2 Road base layers`. It misses the `Lot 5 … Estate` addresses too. By the pre-registered criteria v2 would pass for person and email, and fail phone recall, address recall and address precision.

Cost: about 15 minutes for the 80 tenders on this laptop's CPU, roughly 11 seconds a tender, and a 2.8 GB model held in memory. That is a lot to add in front of a quote request, though it's small next to the wait for a human approval.

What this suggests, not tested: keep the rules for phones, emails and the business-number policy, and add the model for names. Running both and taking the union would likely beat either alone on recall, at the price of more false positives and the latency above. I haven't built or measured that, so the app still runs v1 only.

**Detector v3: fixes for what v1 and v2 got wrong, scored on fresh sets.** `evals/PREREGISTRATION_PII_V3.md` was committed with new sets and criteria before any v3 code. `pii_test3.jsonl` (100 invented tenders, 20 with no personal data) was scored once for each variant. The changes, each aimed at a v1 or v2 miss: a label before a number (`SKU`, `part`, `code`, `invoice`, `ref`) stops it being read as a phone; local 8-digit numbers after a nearby phone cue; more street types, `Unit`, `Lot` and `Estate` forms, lower-case addresses only when a suburb follows, and a bare street rejected when a trade noun or lower-case word follows (`base layers`, `Pavers`); `name at domain dot com`; more name cues (`Owner:`, `Prepared by:`, `Name:`), role words (`(owner)`, `the site supervisor`), verb cues (`ring`, `ask for`, `send the quote to`), and a first name or surname caught on its own once the full name has been seen.

| type (test3) | labelled | v3 rules recall / precision | v3 hybrid recall / precision | needed |
|---|---|---|---|---|
| email | 47 | **1.000** / 1.000 | 1.000 / 1.000 | 0.95 / 0.95 |
| phone | 74 | **1.000** / 1.000 | 1.000 / 1.000 | 0.95 / 0.95 |
| address | 46 | **1.000** / 1.000 | 1.000 / 1.000 | 0.80 / 0.80 |
| person | 116 | **0.871** / 1.000 | **0.974** / 1.000 | 0.75 / 0.90 rules, 0.90 / 0.90 hybrid |
| tenders with a miss (of 100) | | 15 | 3 | |
| false positives on the 20 clean tenders | | 0 | 0 | at most 3 |

The hybrid is the v3 rules plus the Privacy Filter's person spans, with the model's span dropped if it holds a company or filler word, a digit, or overlaps another type. It's an offline experiment (`scripts/score_pii_v3_hybrid.py`); the app runs the v3 rules, and the code has an `extra_detectors` hook if the model is ever added. The model costs about 11 seconds a tender on CPU.

Read these as what they are. The rules match the layouts I imagined. I wrote the new set before the code, and it has new names, streets and near misses, but I wrote it, and it went from "scores 0 to 0.7" on the old sets to "scores 1.0" in one round on the tuning set too. A 1.000 means the rules cover those formats and nothing more. It isn't a real-world rate, and I haven't tested one real tender. The 15 tenders where v3 rules miss a name are all the same two shapes: the second name in "X first, then Y" and a name with no cue, no verb and no role ("Harlan Ng is the contact"). The v1 and v2 numbers above stay as scored.

**A rough stress test, and it scores much worse.** After v3, I asked the assistant to write 16 deliberately messy tenders (`evals/pii_independent_source.txt`): forwarded email chains, texts, a dictated number, initials, nicknames, a cross-street address, an overseas number, codes that look like phone numbers, a name in a greeting. It's **not independent**: the assistant wrote it knowing how the rules work, and tried to break them. Scored once with the v3 rules, no changes afterwards (`results/pii_independent_v3_rules.json`).

| type | labelled | found | predicted | correct |
|---|---|---|---|---|
| person | 13 | 3 (23%) | 8 | 5 |
| phone | 14 | 10 (71%) | 12 | 12 |
| email | 4 | 3 (75%) | 4 | 3 |
| address | 8 | 5 (63%) | 8 | 7 |

One of the 4 tenders with no personal data raised a false alarm. What failed, so you can see the real shape of it:
- **Names are the problem.** Missed: a first name in a text ("hi its steve here"), initials (`J Smith`, `P. VASILEIOU` after `ATTENTION: MR.`), a title with a surname (`Mrs Obradovic` in a sentence), a name after `Re quote -`, a nickname, a bare surname (`Our PM Tran`). The rules need a cue they know; messy real text often has none.
- **Formats the rules don't know:** a spoken number ("oh four one two..."), an overseas number (`+44`), `ext 2` after a number, `katarina.o(at)outlook.com`, `cnr Smith & Jones Streets`, a street with no state or postcode and no comma (`12 Harbour St Wollongong`), a suburb address on `Level 3, ...`.
- **Real false alarms:** `20 Smith Street-style bricks` was read as an address, and `MR` was taken as a name after `ATTENTION:`.
- **My labelling slips, left as scored:** I didn't label `Dave` in a sign-off or `Sandra (accounts)`, so those two are counted as false alarms when they're real names the rules correctly caught; and I included the word `ph` inside one labelled phone span, which counts as a miss. So the true person recall is a little better than 23% and precision a little better than 5 of 8, but not by much.

The honest reading: on text that looks like the formats I designed for, the rules find nearly everything. On messy real-world text they miss most names and a fifth to a third of other values, and the hybrid with the model would help with names but not with the format gaps. If real tenders look like this, v3 is a floor, not a guarantee. A set written by someone who didn't build the detector is still the better evidence.

Limits, plainly:
- Australian formats only. A US phone number or a UK postcode isn't recognised.
- Names are cue-driven (cue words, verbs, roles, or a name already seen). A name with none of those goes through unchanged, and the rules alone missed 13% of names on the new set.
- A code that looks like a phone number and has no label before it (`Hinge set 0245 123 456`) is still flagged.
- Reviewer notes are checked for values already seen in the tender, plus the normal rules; a first name alone in a note isn't caught.
- The MCP agent client (`price_line`) takes one line from whoever calls it and doesn't pass through redaction.
- The draft the reviewer sees, the saved quote and the LangGraph checkpoint hold the real values, in your own database. Redaction is about what the model provider is sent, not about what your own server stores.
- The audit entry for a reviewer decision stores the reviewer's note as typed (existing behaviour).


## Amendment v3.1 (after the stress set)

Fixes for two false alarms and some format gaps found by the messy stress set: `Street-style`, a title after a cue, initials, `ext N` after a phone number, `name(at)domain.com`, `cnr A & B Streets`, `Level N,` prefixes. Re-run afterwards with `results/pii_*_v3_1_rules.json`: dev3 and test3 are identical to v3, the stress set improved to person 4 of 13, phone 11 of 14, email 4 of 4, address 7 of 8, with no false alarm on the clean tenders. The stress set chose the fixes, so those numbers are not a fair test of v3.1. The unamended v3 results stay in `results/pii_*_v3_rules.json`.
