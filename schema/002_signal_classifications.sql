-- signal_classifications: AI-scored events (5-dim + niche + first_angle)
CREATE TABLE IF NOT EXISTS signal_classifications (
  event_id TEXT NOT NULL REFERENCES signal_events(event_id) ON DELETE CASCADE,
  niche_id INTEGER NOT NULL,             -- 1-10
  niche_confidence REAL,
  icp_match REAL,
  evidence_strength REAL,
  urgency REAL,
  buyer_clarity REAL,
  score REAL,
  exclusion_match TEXT,                  -- null | enterprise | agency | smb | b2c
  first_angle TEXT,
  case_match TEXT,
  case_url TEXT,
  model_version TEXT,                    -- e.g. "gemini-2.0-flash-2026-08-20"
  classified_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
  PRIMARY KEY (event_id, niche_id)
);
CREATE INDEX IF NOT EXISTS idx_classif_score
  ON signal_classifications(score DESC, niche_id);
CREATE INDEX IF NOT EXISTS idx_classif_niche
  ON signal_classifications(niche_id, score DESC);
