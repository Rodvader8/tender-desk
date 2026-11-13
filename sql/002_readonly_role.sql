-- Least-privilege role for the MCP server. Local development password; change it for any real deployment.
-- It can read the price list and past jobs, and a few non-sensitive columns of tenders and quotes.
-- It cannot read raw tender text or quote drafts, and it cannot write anything.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'tender_ro') THEN
    CREATE ROLE tender_ro LOGIN PASSWORD 'tender_ro';
  END IF;
END $$;

GRANT CONNECT ON DATABASE tender TO tender_ro;
GRANT USAGE ON SCHEMA public TO tender_ro;
GRANT SELECT ON price_items, past_quotes, past_quote_lines TO tender_ro;
GRANT SELECT (id, title, status, created_at) ON tenders TO tender_ro;
GRANT SELECT (tender_id, total, status, decided_at) ON quotes TO tender_ro;

ALTER ROLE tender_ro SET default_transaction_read_only = on;
ALTER ROLE tender_ro SET statement_timeout = '5s';
ALTER ROLE tender_ro SET idle_in_transaction_session_timeout = '10s';
