# Written before the redaction code and before either PII set was scored

Problem: a tender is text from a stranger and it can carry personal data: a site contact's name, a mobile number, an email, a home address. The model provider sees whatever is in the prompt. The model doesn't need any of it to price a job.

Plan: a redaction step runs before the extract step. The model only sees placeholders: `[PERSON_1]`, `[PHONE_1]`, `[EMAIL_1]`, `[ADDRESS_1]`. The same value always gets the same placeholder within one tender. The code can rebuild the placeholder map from the stored tender text, uses it to put the real values back into the draft the reviewer sees and into the saved quote, and never writes the map or any value to a prompt, an audit entry, a run step or a metric. Only counts are logged. This follows the repo's rule: the model picks, the code does the rest.

Detector v1 is rules only, no model, tuned for Australian formats:

- emails: the usual address shape;
- phones: AU mobiles (`04xx`, `+61 4xx`) and landlines (`02`, `03`, `07`, `08`, with or without brackets, spaces, dashes or `+61`), checked by digit count so a quantity, a part number or an ABN isn't flagged; an 8-digit local number only when a cue word like `ph` or `mobile` is right before it;
- addresses: number, street name, street type (`Street`, `St`, `Road`, `Rd`, `Avenue` and so on), then an optional suburb, state and 4-digit postcode; also PO boxes;
- names: only after a cue phrase (`Attn:`, `Contact:`, `Site contact:`, `Mr`, `Ms`, `Mrs`, `Miss`, `Dr`, `Regards`, `Kind regards`, `Thanks`, `Cheers`), plus any later repeat of the same full name.

Policy, written before the evidence: company names, ABNs and ACNs, `1300`, `1800` and `13 xx xx` numbers, and a bare suburb or postcode are business or public details, not personal data, and are not redacted. The tender's own scope, quantities and prices are never redacted.

Test sets (invented data only, built by `scripts/make_pii_sets.py` with a fixed seed, spans labelled by construction):

- `evals/pii_dev.jsonl`: 30 tenders. Used to tune the rules.
- `evals/pii_test.jsonl`: 80 tenders. Names, streets and suburbs don't overlap with dev. Scored once, after the rules are frozen. About a fifth of its contact lines use formats that dev never shows (a different cue, a different layout), so it measures whether the rules generalise or just fit dev.
- Both sets include plain tenders with no personal data but with near misses on purpose: ABNs, 1300/1800 numbers, quantities with thousands separators, dates, lot and plan numbers, dimensions, company names after `Contact:`, and street-like phrases.
- Mobile numbers are in the `0491 57x xxx` block, which is the range set aside for fictional use. Landlines use `5550` as the exchange. Names are a generic invented list.

Scoring is per type, per span:

- recall: a labelled span counts as found only if every non-space, non-punctuation character of it sits inside predicted spans of the same type. A half-covered span is a miss, because half a phone number is still a leak;
- precision: a predicted span counts as correct if it overlaps a labelled span of the same type. Anything else is a false positive;
- also reported: tenders with at least one miss, and false positives on the tenders that have no personal data at all.

Success criteria for v1, on the test set:

| Type | Recall at least | Precision at least |
|---|---|---|
| Email | 0.95 | 0.95 |
| Phone | 0.90 | 0.90 |
| Address | 0.80 | 0.90 |
| Person | 0.60 | 0.80 |

and no more than 2 false positives across the tenders that have no personal data.

Misses I expect before running, and will list in the README if they happen:

- names that sit with no cue phrase ("arrange access with Priya Nair, the owner"), and cues outside my list (`Owner:`, `Prepared by:`). Names are the weakest type by design and I expect to miss these;
- a first name used alone after the full name has appeared once;
- an 8-digit local number with no cue word;
- an email written out as "name at domain dot com";
- an address in lower case, or a `Lot 5` style address with no street;
- a 10-digit part or order code that happens to start `04` or `02` will be flagged as a phone number.

Not claimed: this is not anonymisation. A miss means the model sees the value. Formats outside Australian ones are out of scope.

Detector v2 (optional, only if Rod agrees to the download first): OpenAI's open-source Privacy Filter run locally on CPU against the same test set with the same scoring, reported next to v1 whichever wins. It is not part of the v1 criteria above.

Rules for changing things: rules may be changed after looking at dev results and never after looking at test results. If I change anything after the test run, it goes in an amendment below with the reason, and the unamended test numbers stay in the README.
