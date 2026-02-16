-- Audit hardening: identity and decision-step clarity.
-- Run once against decision_engine. Append-only: no DROP/truncate.

-- Identity: every action attributable to one actor, one session, one system
ALTER TABLE custody_events ADD COLUMN IF NOT EXISTS actor_id TEXT;
ALTER TABLE custody_events ADD COLUMN IF NOT EXISTS session_id TEXT;
ALTER TABLE custody_events ADD COLUMN IF NOT EXISTS source_system TEXT;

-- Decision step clarity: system suggestion, options, human choice, timestamp
ALTER TABLE custody_events ADD COLUMN IF NOT EXISTS system_suggestion TEXT;
ALTER TABLE custody_events ADD COLUMN IF NOT EXISTS options_presented TEXT;
ALTER TABLE custody_events ADD COLUMN IF NOT EXISTS human_selection TEXT;
ALTER TABLE custody_events ADD COLUMN IF NOT EXISTS decision_timestamp TIMESTAMPTZ;
