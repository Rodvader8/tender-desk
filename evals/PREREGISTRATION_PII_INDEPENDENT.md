# Written before the independent set exists or is scored

Why: every earlier PII set was written by the same AI assistant that wrote the detectors, so a high score mostly shows the rules cover layouts it imagined. This set is written by Rod alone, in his own style, with no sight of the rules, the README results or the earlier sets. It is built by `scripts/build_pii_independent.py` from a markup file and scored once with the v3 rules (the version in the app) by `scripts/score_pii.py independent`.

Method: 15 to 20 invented tenders or tender emails, at least 4 with no personal data at all, written as a real tender or email would be. Every invented name, number, email and address is marked up as it is written. Nothing is run against the detector until the file is final.

No pass criteria are set, on purpose: with a set this small each type has few spans, so a threshold would be noise. What gets published, whatever the numbers are: recall and precision per type, every miss and every false positive, and a plain statement that the set is small and invented.
