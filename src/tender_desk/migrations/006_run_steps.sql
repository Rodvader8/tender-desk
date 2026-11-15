-- One row per workflow step that ran, so a single tender's cost and latency can be read back (and revisions show up as
-- extra rows). The wait for a person is not a step. `error` holds an exception TYPE only, never its message.
CREATE TABLE run_steps (
    id        bigserial PRIMARY KEY,
    tender_id int NOT NULL REFERENCES tenders(id),
    step      text NOT NULL,
    at        timestamptz NOT NULL DEFAULT now(),
    ms        double precision NOT NULL,
    cost_usd  numeric(12,6) NOT NULL DEFAULT 0,
    llm_calls int NOT NULL DEFAULT 0,
    error     text
);
CREATE INDEX ON run_steps (tender_id);
