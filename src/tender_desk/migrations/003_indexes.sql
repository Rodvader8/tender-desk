-- Lookups the API and the audit trail do on every request.
CREATE INDEX IF NOT EXISTS audit_log_tender_id_idx ON audit_log (tender_id, id);
CREATE INDEX IF NOT EXISTS quotes_tender_id_idx ON quotes (tender_id, id DESC);
CREATE INDEX IF NOT EXISTS tenders_status_idx ON tenders (status);
