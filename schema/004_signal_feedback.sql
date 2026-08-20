-- signal_feedback: per-client actions (sent/opened/replied/meeting/won/lost)
CREATE TABLE IF NOT EXISTS signal_feedback (
  feedback_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id UUID,
  client_name TEXT,                     -- human-readable
  play_id TEXT REFERENCES signal_plays(play_id),
  company_domain TEXT NOT NULL,
  event_type TEXT,
  action TEXT NOT NULL,                 -- "sent" | "opened" | "replied" | "meeting" | "won" | "lost" | "bounced"
  action_at TIMESTAMPTZ DEFAULT NOW(),
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_feedback_play
  ON signal_feedback(play_id, action);
CREATE INDEX IF NOT EXISTS idx_feedback_domain
  ON signal_feedback(company_domain, action_at DESC);
