-- Sending an approved quote to an outside system. One row per quote, so asking twice cannot send twice.
--   pending   we have started and don't yet know the outcome (also what is left behind by a crash mid-send)
--   sent      the other side's own record confirms it holds exactly what was approved
--   unknown   we sent, lost the answer, and could not read back what the other side holds; reconcile settles it
--   conflict  the other side holds something different from what was approved; a person has to look
--   failed    refused, or never arrived after every attempt (confirmed by readback)
CREATE TABLE deliveries (
    id               serial PRIMARY KEY,
    quote_id         int  NOT NULL UNIQUE REFERENCES quotes(id),
    tender_id        int  NOT NULL REFERENCES tenders(id),
    idempotency_key  text NOT NULL UNIQUE,
    state            text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','sent','unknown','conflict','failed')),
    reference        text,
    attempts         int  NOT NULL DEFAULT 0,
    last_error       text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
