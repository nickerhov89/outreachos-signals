# OutreachOS Signals

Signal-as-a-Service for B2B outbound. Finds fresh, verifiable buying signals
in 10 B2B niches, scores them, and packages as actionable plays for cold outreach.

## Status
🚧 MVP — building Week 1 of 2-week plan.
See `docs/signal_finder_top10_2026-08-20.md` for full design.

## Architecture
5-stage pipeline: COLLECT → NORMALIZE → DEDUP → CLASSIFY → PACKAGE
10 niches × 5-15 sources × weekly XLSX + web UI + email digest.

## Layout
- `schema/`   — SQL migrations for `signal_*` tables (PostgreSQL)
- `collectors/` — pull raw events from ATS, Apify, GitHub, Google News
- `pipeline/` — normalize, dedup, classify (Gemini Flash), package
- `delivery/` — XLSX export, email digest, API routes
- `systemd/`  — user-level service+timers (no sudo needed)
- `scripts/`  — migration, setup, run helpers
- `tests/`    — unit + integration
- `docs/`     — design specs, runbooks

## Quick start
    cp .env.example .env         # fill in real API keys
    python3 -m venv .venv && source .venv/bin/activate
    pip install -e .
    python3 scripts/migrate.py   # creates data/signals.db with 4 tables
    systemctl --user daemon-reload
    systemctl --user enable --now signal-ats.timer

## Servers
- App root: `manager@144.31.54.166` (this box) — Signal Finder lives here
- DB:      SQLite at `data/signals.db` on same box (no external DB)
- Web UI:  separate Next.js on `outreachos.pro/signals` (TBD) OR polza-portal.ru reads same SQLite file
- Portal DB: 139.60.162.12:35434 (polza-portal.ru) — we only READ it, never write
