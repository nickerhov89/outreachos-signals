-- signal_events: raw normalized events from all sources
-- SQLite version (UUID + timestamps generated in Python)
CREATE TABLE IF NOT EXISTS signal_events (
  event_id TEXT PRIMARY KEY,             -- uuid.uuid4() from Python
  source TEXT NOT NULL,                  -- ats | linkedin | funding | threads | reddit | github | sec | builtwith | g2
  source_event_id TEXT,                  -- original ID from source (for dedup)
  company_domain TEXT NOT NULL,
  company_name TEXT,
  company_size TEXT,
  company_country TEXT,
  event_type TEXT NOT NULL,              -- hiring | funding | tech_change | pain | trigger | profile_change | product_launch
  event_subtype TEXT,
  event_date TEXT,                       -- ISO date "2026-08-20"
  raw_text TEXT,
  evidence_url TEXT,
  evidence_snippet TEXT,
  raw_metadata TEXT,                     -- JSON string
  collected_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);
CREATE INDEX IF NOT EXISTS idx_signal_events_company
  ON signal_events(company_domain, event_type, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_signal_events_date
  ON signal_events(event_date DESC);
CREATE INDEX IF NOT EXISTS idx_signal_events_source
  ON signal_events(source, collected_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_signal_events_source_id
  ON signal_events(source, source_event_id) WHERE source_event_id IS NOT NULL;
