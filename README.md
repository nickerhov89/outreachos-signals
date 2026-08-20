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
    cp .env.example .env  &&  # fill in real keys
    bash scripts/migrate.sh
    systemctl --user daemon-reload
    systemctl --user enable --now signal-ats.timer
    systemctl --user list-timers  # see schedule

## Servers
- App root: `manager@144.31.54.166` (this box)
- DB:      `139.60.162.12:35434` (polza-portal.ru, sslmode=disable)
- Web UI:  polza-portal.ru/signals (route in existing Next.js)
