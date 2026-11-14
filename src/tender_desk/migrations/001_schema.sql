CREATE EXTENSION IF NOT EXISTS vector;

-- What we can buy: materials, labour and plant, with a supplier price.
CREATE TABLE price_items (
    id          serial PRIMARY KEY,
    sku         text UNIQUE NOT NULL,
    name        text NOT NULL,
    category    text NOT NULL,
    unit        text NOT NULL,
    unit_price  numeric(12,2) NOT NULL CHECK (unit_price >= 0),
    supplier    text NOT NULL,
    embedding   vector(384)
);

-- Jobs we have priced before, used as comparables and for margin policy.
CREATE TABLE past_quotes (
    id          serial PRIMARY KEY,
    title       text NOT NULL,
    description text NOT NULL,
    total       numeric(14,2) NOT NULL,
    margin_pct  numeric(5,2) NOT NULL,
    quoted_on   date NOT NULL,
    embedding   vector(384)
);

CREATE TABLE past_quote_lines (
    id          serial PRIMARY KEY,
    quote_id    int NOT NULL REFERENCES past_quotes(id) ON DELETE CASCADE,
    price_item_id int NOT NULL REFERENCES price_items(id),
    qty         numeric(12,2) NOT NULL
);

-- The live workflow: every tender, its approved quote, and an audit trail.
CREATE TABLE tenders (
    id          serial PRIMARY KEY,
    title       text NOT NULL,
    raw_text    text NOT NULL,
    status      text NOT NULL DEFAULT 'received',
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE quotes (
    id          serial PRIMARY KEY,
    tender_id   int NOT NULL REFERENCES tenders(id),
    draft       jsonb NOT NULL,
    total       numeric(14,2) NOT NULL,
    status      text NOT NULL CHECK (status IN ('approved','rejected')),
    decided_by  text NOT NULL,
    notes       text NOT NULL DEFAULT '',
    decided_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit_log (
    id          bigserial PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    tender_id   int,
    event       text NOT NULL,
    detail      jsonb NOT NULL DEFAULT '{}'
);

CREATE INDEX ON price_items USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON past_quotes USING hnsw (embedding vector_cosine_ops);
