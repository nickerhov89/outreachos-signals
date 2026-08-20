-- signal_plays: weekly packaged signal plays per niche
CREATE TABLE IF NOT EXISTS signal_plays (
  play_id TEXT PRIMARY KEY,             -- "crm_cro_change_2026_w34"
  niche_id SMALLINT NOT NULL,
  play_name TEXT,
  trigger_logic TEXT,
  valid_from DATE,
  valid_until DATE,
  accounts_count INT,
  accounts_avg_score NUMERIC(3,1),
  accounts_json JSONB,                  -- 50-100 account objects
  generated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_plays_niche
  ON signal_plays(niche_id, valid_from DESC);

-- signal_play_accounts: m2m for analytics
CREATE TABLE IF NOT EXISTS signal_play_accounts (
  play_id TEXT NOT NULL REFERENCES signal_plays(play_id) ON DELETE CASCADE,
  company_domain TEXT NOT NULL,
  event_id UUID,
  score NUMERIC(3,1),
  first_angle TEXT,
  case_match TEXT,
  PRIMARY KEY (play_id, company_domain)
);
CREATE INDEX IF NOT EXISTS idx_pa_domain
  ON signal_play_accounts(company_domain);
