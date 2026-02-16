-- Base schema for Decision Engine.
-- Run first, before 001_audit_hardening.sql. Creates the three tables
-- the app expects (custody_chains, custody_events, ingestion_events);
-- no identity or decision-step columns yet. Uses IF NOT EXISTS.

-- Chains: one row per custody chain (e.g. one per ingested file or extension session).
CREATE TABLE IF NOT EXISTS custody_chains (
    chain_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    root_file_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at_utc TIMESTAMPTZ DEFAULT now()
);

-- Ingestion log: one row per file ingest, links to a chain.
CREATE TABLE IF NOT EXISTS ingestion_events (
    id SERIAL PRIMARY KEY,
    filename TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    row_count INTEGER,
    custody_chain_id UUID NOT NULL REFERENCES custody_chains(chain_id)
);

-- Events: append-only log of TRANSMITTED, RECEIVED, AI_DECISION_TURN, etc.
CREATE TABLE IF NOT EXISTS custody_events (
    event_id SERIAL PRIMARY KEY,
    chain_id UUID NOT NULL REFERENCES custody_chains(chain_id),
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    payload_hash TEXT,
    previous_event_hash TEXT,
    event_hash TEXT,
    occurred_at_utc TIMESTAMPTZ NOT NULL
);
