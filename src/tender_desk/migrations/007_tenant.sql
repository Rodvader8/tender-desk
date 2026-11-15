-- Which company a tender belongs to. Quotes, deliveries, run steps and the audit log reach it through the tender.
-- Existing rows belong to 'default', which is also the tenant of the single shared token.
ALTER TABLE tenders ADD COLUMN tenant text NOT NULL DEFAULT 'default';
CREATE INDEX ON tenders (tenant);
