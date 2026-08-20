"""Claude Haiku 4.5 classifier — 5-dim scoring + first_angle + case_match.
Pure stdlib HTTP, no SDK needed.
Reads unclassified events from signal_events, writes to signal_classifications."""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..db import ENV, conn, now_iso

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-haiku-4-5-20251022"

# 10 niches with structured info for the prompt
NICHES_DESC = [
    {"id": 1, "name": "CRM / BPM / Automation", "icp": "B2B SaaS 50-500 emp, US/EU, sales-led"},
    {"id": 2, "name": "HRTech / Recruitment", "icp": "B2B SaaS scaling sales 30-200 emp, US/EU"},
    {"id": 3, "name": "MarTech / Analytics", "icp": "B2B SaaS 50-500 emp, has marketing team"},
    {"id": 4, "name": "AI / Data", "icp": "Tech companies building AI features, 30-300 emp"},
    {"id": 5, "name": "B2B SaaS", "icp": "B2B SaaS 50-500 emp, scaling GTM, US/EU"},
    {"id": 6, "name": "IT Services / Integration", "icp": "Mid-market companies outsourcing dev"},
    {"id": 7, "name": "Cloud / Infrastructure / Security", "icp": "Tech companies with SOC 2 / CISO needs"},
    {"id": 8, "name": "FinTech / Payments", "icp": "Fintech startups 30-300 emp, BaaS/PSP needs"},
    {"id": 9, "name": "EdTech / LMS", "icp": "B2B edtech, corporate learning"},
    {"id": 10, "name": "Marketplace / E-commerce tech", "icp": "Two-sided marketplaces, 30-300 emp"},
]

SYSTEM_PROMPT = """You are a B2B signal classifier for cold outreach at a B2B lead-gen agency.
For each event, output JSON with these fields:
- niche_id: integer 1-10 (or null if no match)
- niche_confidence: 0.0-1.0
- icp_match: 0.0-1.0 (how well the event matches ideal customer profile for outbound lead gen)
- evidence_strength: 0.0-1.0 (concrete numbers, dates, named people?)
- urgency: 0.0-1.0 (how time-sensitive — recent hiring = urgent, old news = low)
- buyer_clarity: 0.0-1.0 (can we identify the decision maker?)
- score: 1-10 (weighted: 0.30 icp + 0.25 evidence + 0.20 urgency + 0.15 buyer + 0.10 freshness)
- exclusion_match: null | "enterprise" | "agency" | "smb" | "b2c"
- first_angle: 1-2 sentence outreach opener (English, conversational, references the event)
- case_match: short name of closest Polza case (we have: Каскад-Металл, КЗСК, 3D-принтер, Хвойный Остров, МагнумСтрой, BPMSoft, Comindware)

Output ONLY valid JSON. No preamble."""

USER_PROMPT_TEMPLATE = """Event to classify:

Source: {source}
Company: {company}
Date: {event_date}
Title: {raw_text}
Evidence: {evidence_snippet}
URL: {evidence_url}

Niches available:
{niches_list}

Return JSON only."""


def call_claude(events: list[dict], model: str = None) -> list[dict]:
    """Call Claude with batch of events, return list of classifications."""
    api_key = ENV.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not in .env")
    model = model or ENV.get("CLAUDE_MODEL", DEFAULT_MODEL)

    niches_text = "\n".join(f"{n['id']}. {n['name']} — {n['icp']}" for n in NICHES_DESC)
    # Batch up to 5 events per call (Haiku can handle, keeps cost down)
    results = []
    for ev in events:
        user_msg = USER_PROMPT_TEMPLATE.format(
            source=ev.get("source", "?"),
            company=ev.get("company_name") or ev.get("company_domain", "?"),
            event_date=ev.get("event_date") or "unknown",
            raw_text=(ev.get("raw_text") or "")[:400],
            evidence_snippet=(ev.get("evidence_snippet") or "")[:300],
            evidence_url=ev.get("evidence_url") or "",
            niches_list=niches_text,
        )
        body = json.dumps({
            "model": model,
            "max_tokens": 800,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_msg}],
        }).encode()
        req = urllib.request.Request(
            ANTHROPIC_URL, data=body, method="POST",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.loads(r.read())
            text = resp["content"][0]["text"]
            # Strip code fences if any
            text = text.strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
            parsed = json.loads(text)
            parsed["event_id"] = ev["event_id"]
            results.append(parsed)
        except Exception as e:
            print(f"  [ERR] event {ev.get('event_id', '?')[:8]}: {e}")
            continue
        time.sleep(0.5)  # rate limit
    return results


import re  # for code-fence stripping above


def fetch_unclassified(limit: int = 50) -> list[dict]:
    with conn() as c:
        rows = c.execute("""
            SELECT e.event_id, e.source, e.company_domain, e.company_name, e.event_date,
                   e.raw_text, e.evidence_url, e.evidence_snippet
            FROM signal_events e
            LEFT JOIN signal_classifications cl ON cl.event_id = e.event_id
            WHERE cl.event_id IS NULL
            ORDER BY e.collected_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def save_classifications(classifications: list[dict], model_version: str) -> int:
    if not classifications:
        return 0
    saved = 0
    with conn() as c:
        for cl in classifications:
            if cl.get("niche_id") is None:
                continue
            try:
                c.execute("""
                    INSERT OR REPLACE INTO signal_classifications
                      (event_id, niche_id, niche_confidence, icp_match, evidence_strength,
                       urgency, buyer_clarity, score, exclusion_match,
                       first_angle, case_match, case_url, model_version, classified_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, CURRENT_TIMESTAMP)
                """, (
                    cl["event_id"],
                    int(cl["niche_id"]),
                    float(cl.get("niche_confidence") or 0),
                    float(cl.get("icp_match") or 0),
                    float(cl.get("evidence_strength") or 0),
                    float(cl.get("urgency") or 0),
                    float(cl.get("buyer_clarity") or 0),
                    float(cl.get("score") or 0),
                    cl.get("exclusion_match"),
                    cl.get("first_angle"),
                    cl.get("case_match"),
                    None,  # case_url
                    model_version,
                ))
                saved += 1
            except Exception as e:
                print(f"  [SKIP] {cl.get('event_id', '?')[:8]}: {e}")
    return saved


def main(batch: int = 20):
    print(f"Classify: fetching up to {batch} unclassified events")
    events = fetch_unclassified(limit=batch)
    if not events:
        print("  no unclassified events")
        return
    print(f"  fetched {len(events)}, calling Claude Haiku 4.5…")
    classifications = call_claude(events)
    saved = save_classifications(classifications, DEFAULT_MODEL)
    print(f"  classified={len(classifications)} saved={saved}")


if __name__ == "__main__":
    main()
