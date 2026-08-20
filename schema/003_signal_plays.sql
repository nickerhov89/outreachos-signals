-- signal_plays: weekly packaged signal plays per niche
CREATE TABLE IF NOT EXISTS signal_plays (
  play_id TEXT PRIMARY KEY,              -- e.g. "crm_cro_change_2026_w34"
  niche_id INTEGER NOT NULL,
  play_name TEXT,
  trigger_logic TEXT,
  valid_from TEXT,
  valid_until TEXT,
  accounts_count INTEGER,
  accounts_avg_score REAL,
  accounts_json TEXT,                    -- JSON: 50-100 account objects
  generated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);
CREATE INDEX IF NOT EXISTS idx_plays_niche
  ON signal_plays(niche_id, valid_from DESC);

-- signal_play_accounts: m2m for analytics
CREATE TABLE IF NOT EXISTS signal_play_accounts (
  play_id TEXT NOT NULL REFERENCES signal_plays(play_id) ON DELETE CASCADE,
  company_domain TEXT NOT NULL,
  event_id TEXT,
  score REAL,
  first_angle TEXT,
  case_match TEXT,
  PRIMARY KEY (play_id, company_domain)
);
CREATE INDEX IF NOT EXISTS idx_pa_domain
  ON signal_play_accounts(company_domain);
