#!/bin/bash
# Manual run: collect + classify in one go
set -e
cd "$(dirname "$0")/.."
echo "=== ATS (Greenhouse + Lever) ==="
python3 -m outreachos_signals.collectors.ats_greenhouse
python3 -m outreachos_signals.collectors.ats_lever
echo "=== Funding (Google News) ==="
python3 -m outreachos_signals.collectors.funding_news
echo "=== GitHub commits ==="
python3 -m outreachos_signals.collectors.github_commits
echo "=== Apify Threads ==="
python3 -m outreachos_signals.collectors.apify_threads
echo "=== Classify (Claude Haiku) ==="
python3 -m outreachos_signals.pipeline.classify
echo "=== Done ==="
python3 -c "from outreachos_signals.db import count_events; print(f'Total events: {count_events()}')"
