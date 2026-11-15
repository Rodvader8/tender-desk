-- The exact draft a person approved, as a SHA-256 of its canonical JSON. Older rows have none.
ALTER TABLE quotes ADD COLUMN draft_digest text;
