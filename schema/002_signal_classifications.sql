-- signal_classifications: AI-scored events (5-dim + niche + first_angle)
CREATE TABLE IF NOT EXISTS signal_classifications (
  event_id UUID NOT NULL REFERENCES signal_events(event_id) ON DELETE CASCADE,
  niche_id SMALLINT NOT NULL,            -- 1-10
  niche_confidence NUMERIC(3,2),
  icp_match NUMERIC(3,2),
  evidence_strength NUMERIC(3,2),
  urgency NUMERIC(3,2),
  buyer_clarity NUMERIC(3,2),
  score NUMERIC(3,1),
  exclusion_match TEXT,                 -- null | "enterprise" | "agency" | "smb" | "b2c"
  first_angle TEXT,
  case_match TEXT,
  case_url TEXT,
  model_version TEXT,                   -- e.g. "gemini-2.0-flash-exp-2026-08-20"
  classified_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (event_id, niche_id)
);
CREATE INDEX IF NOT EXISTS idx_classif_score
  ON signal_classifications(score DESC, niche_id);
CREATE INDEX IF NOT EXISTS idx_classif_niche
  ON signal_classifications(niche_id, score DESC);
