"""Apollo.io Leads & Contacts collector.
For each classified event with company_domain, find 1-3 buyer contacts via Apollo.

Strategy:
1. /v1/mixed_people/api_search — find people at company by title pattern
2. /v1/people/match — get personal email by name + company (reveal_personal_emails)
3. /v1/organizations/enrich — company firmographics (optional, for dashboard)

Apollo free tier: 10,000 credits/month. people/search = ~1 credit, people/match = 1 credit, reveal_email = 1 credit.
"""
import json
import os
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT.parent / "data" / "signals.db"  # outreachos_signals.collectors.* → root = outreachos_signals/
ENV_PATH = ROOT.parent / ".env"

APOLLO_BASE = "https://api.apollo.io/v1"
MAX_WORKERS = 2
MIN_SCORE = 0.5
TITLE_PATTERNS = {
    # niche_id -> list of buyer titles to look for
    1: ["VP Sales", "VP Revenue", "CRO", "Head of Sales", "VP RevOps", "Head of Sales Operations"],
    2: ["VP People", "Head of People", "Head of Talent", "Head of Recruiting", "VP HR"],
    3: ["VP Marketing", "Head of Growth", "Director of Marketing", "VP Demand Gen", "Head of Marketing Operations"],
    4: ["VP Engineering", "CTO", "Head of Engineering", "Head of AI", "VP ML", "Head of Data"],
    5: ["VP Product", "Head of Product", "VP Customer Success", "VP Sales", "Head of Growth"],
    6: ["CTO", "VP Engineering", "Head of Platform", "Chief Architect"],
    7: ["CISO", "Head of Security", "VP Infrastructure", "VP DevOps", "Head of IT"],
    8: ["VP Compliance", "Head of Compliance", "VP Risk", "VP Finance", "CFO"],
    9: ["VP Product", "Head of Product", "VP Education", "Director of Learning"],
    10: ["VP Operations", "Head of Trust", "VP Marketplace", "Head of Growth", "VP Product"],
}


def get_api_key() -> str:
    if ENV_PATH.exists():
        for line in open(ENV_PATH):
            line = line.strip()
            if line.startswith("APOLLO_API_KEY="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("APOLLO_API_KEY", "")


def search_people(domain: str, titles: list[str], limit: int = 3) -> list[dict]:
    """Find people at domain matching title patterns."""
    api_key = get_api_key()
    if not api_key:
        return []
    url = f"{APOLLO_BASE}/mixed_people/api_search"
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
    payload = {
        "q_organization_domains": domain,
        "person_titles": titles,
        "person_seniorities": ["vp", "c_suite", "director", "manager"],
        "limit": limit,
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=20)
        if r.status_code == 200:
            data = r.json()
            return data.get("people", [])
    except Exception:
        pass
    return []


def match_person_email(first_name: str, last_name: str, organization_name: str) -> dict | None:
    """Find a person + their personal email via Apollo /v1/people/match."""
    api_key = get_api_key()
    if not api_key:
        return None
    url = f"{APOLLO_BASE}/people/match"
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
    payload = {
        "first_name": first_name,
        "last_name": last_name,
        "organization_name": organization_name,
        "reveal_personal_emails": True,
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=20)
        if r.status_code == 200:
            return r.json().get("person")
    except Exception:
        pass
    return None


def enrich_company(domain: str) -> dict | None:
    """Get company firmographics."""
    api_key = get_api_key()
    if not api_key:
        return None
    url = f"{APOLLO_BASE}/organizations/enrich"
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
    try:
        r = requests.post(url, json={"domain": domain}, headers=headers, timeout=20)
        if r.status_code == 200:
            return r.json().get("organization")
    except Exception:
        pass
    return None


def process_event(event: dict, niche_id: int) -> dict:
    """Full pipeline: search people + match email + enrich company."""
    domain = event.get("company_domain")
    company_name = event.get("company_name", "")
    if not domain:
        return {"domain": None, "contacts": [], "company": None}

    titles = TITLE_PATTERNS.get(niche_id, ["VP Sales", "VP Marketing", "CTO", "VP Engineering"])
    people = search_people(domain, titles, limit=2)
    contacts = []
    for p in people[:2]:
        first = p.get("first_name", "").strip()
        last = p.get("last_name", "").strip()
        org = p.get("organization", {}).get("name", company_name) if p.get("organization") else company_name
        if not first or not last:
            continue
        # try to get email via match
        matched = match_person_email(first, last, org)
        email = ""
        if matched and matched.get("email"):
            email = matched["email"]
        contacts.append({
            "name": f"{first} {last}".strip(),
            "first": first,
            "last": last,
            "title": p.get("title", ""),
            "seniority": p.get("seniority", ""),
            "email": email,
            "linkedin": p.get("linkedin_url", ""),
            "source": "apollo_match",
            "status": "valid" if email else "no_email",
        })
    company = enrich_company(domain)
    return {"domain": domain, "contacts": contacts, "company": company}


def save_enrichment(event_id: str, result: dict):
    """Save Apollo result into signal_classifications.buyer_contacts_json."""
    payload = {
        "contacts": result.get("contacts", []),
        "company": result.get("company", {}),
        "source": "apollo",
    }
    with sqlite3.connect(str(DB_PATH)) as db:
        db.execute("""
            UPDATE signal_classifications
            SET buyer_contacts_json = ?
            WHERE event_id = ?
        """, (json.dumps(payload, ensure_ascii=False), event_id))


def main(limit: int = 20, min_score: float = MIN_SCORE):
    api_key = get_api_key()
    if not api_key:
        print("ERR: APOLLO_API_KEY not set")
        return
    print(f"Apollo collector: limit={limit}, min_score={min_score}")
    print(f"  key: {api_key[:15]}...")

    with sqlite3.connect(str(DB_PATH)) as db:
        rows = db.execute("""
            SELECT cl.event_id, cl.score, cl.niche_id,
                   e.company_name, e.company_domain
            FROM signal_classifications cl
            JOIN signal_events e ON e.event_id = cl.event_id
            WHERE cl.score >= ?
              AND e.company_domain IS NOT NULL
              AND e.company_domain != ''
              AND e.company_domain NOT IN (
                  'greenhouse.io','lever.co','reddit.com','github.com','ycombinator.com',
                  'google.com','news.google.com','twitter.com','facebook.com','linkedin.com'
              )
              AND e.company_domain NOT LIKE 'news.%'
              AND e.company_domain NOT LIKE 'github.com/%'
              AND e.company_name IS NOT NULL
              AND e.company_name != 'Unknown'
              AND (cl.buyer_contacts_json IS NULL
                   OR cl.buyer_contacts_json NOT LIKE '%"source": "apollo"%')
            ORDER BY cl.score DESC
            LIMIT ?
        """, (min_score, limit)).fetchall()

    if not rows:
        print("  nothing to enrich")
        return
    print(f"  {len(rows)} events to process (sequential — Apollo is rate-limited)")

    enriched = 0
    total_contacts = 0
    for i, r in enumerate(rows, 1):
        event_id, score, niche_id, company, domain = r
        print(f"  [{i}/{len(rows)}] {domain} ({company}, niche={niche_id}, score={score:.2f})...", end=" ", flush=True)
        try:
            result = process_event({"company_name": company, "company_domain": domain}, niche_id)
            n_contacts = len(result["contacts"])
            with_email = sum(1 for c in result["contacts"] if c.get("email"))
            save_enrichment(event_id, result)
            enriched += 1
            total_contacts += n_contacts
            print(f"✓ {n_contacts} contacts ({with_email} with email)")
        except Exception as e:
            print(f"ERR: {str(e)[:80]}")

    print(f"\n  enriched: {enriched}/{len(rows)}, total contacts: {total_contacts}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--min-score", type=float, default=MIN_SCORE)
    args = p.parse_args()
    main(args.limit, args.min_score)
