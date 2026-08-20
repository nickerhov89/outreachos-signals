"""Outscraper Leads & Contacts collector.
For each classified event with company_domain, fetch real leads via Outscraper API.
Endpoint: POST /leads-and-contacts with async=false
Auth: X-API-KEY header (BASE64-encoded token!)
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
DB_PATH = ROOT.parent / "data" / "signals.db"
ENV_PATH = ROOT.parent / ".env"

OUTSCRAPER_BASE = "https://api.outscraper.cloud"
MAX_WORKERS = 2  # parallel API calls
MIN_SCORE = 0.5


def get_api_key() -> str:
    """Read OUTSCRAPER_API_KEY from .env (BASE64-encoded)."""
    if ENV_PATH.exists():
        for line in open(ENV_PATH):
            line = line.strip()
            if line.startswith("OUTSCRAPER_API_KEY="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("OUTSCRAPER_API_KEY", "")


def fetch_leads(domain: str, contacts_per_company: int = 3, timeout: int = 60) -> dict:
    """Call Outscraper /leads-and-contacts. Returns parsed dict or {} on error."""
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("OUTSCRAPER_API_KEY not set in .env")
    url = f"{OUTSCRAPER_BASE}/leads-and-contacts"
    params = {
        "query": domain,
        "async": "false",
        "contactsPerCompany": contacts_per_company,
    }
    headers = {"X-API-KEY": api_key}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        return {"error": True, "status_code": r.status_code, "body": r.text[:200]}
    except Exception as e:
        return {"error": True, "exception": str(e)[:200]}


def save_enrichment(event_id: str, out_data: dict) -> int:
    """Save Outscraper result into signal_classifications.buyer_contacts_json.
    Returns number of contacts saved."""
    if not out_data or "data" not in out_data:
        return 0
    items = out_data["data"]
    if not items:
        return 0
    item = items[0] if isinstance(items, list) else list(items.values())[0]
    if isinstance(item, list):
        item = item[0] if item else {}
    if not isinstance(item, dict):
        return 0

    contacts = []
    # 1) real people from contacts[]
    for c in item.get("contacts", []):
        full_name = c.get("full_name", "").strip()
        title = c.get("title", "")
        level = c.get("level", "")
        socials = c.get("socials", {})
        for email_obj in c.get("emails", []):
            email = email_obj.get("value", "").lower() if isinstance(email_obj, dict) else str(email_obj).lower()
            if not email or "@" not in email:
                continue
            # split name
            parts = full_name.split()
            first, last = (parts[0], parts[-1]) if parts else ("", "")
            contacts.append({
                "name": full_name,
                "first": first,
                "last": last,
                "title": title,
                "level": level,
                "email": email,
                "linkedin": socials.get("linkedin", ""),
                "source": "outscraper_leads",
                "status": "valid",  # Outscraper already verified
            })
    # 2) general emails
    for e in item.get("emails", []):
        email = e.get("value", "").lower() if isinstance(e, dict) else str(e).lower()
        if not email or "@" not in email:
            continue
        contacts.append({
            "name": None,
            "email": email,
            "source": "outscraper_general",
            "status": "valid",
        })
    # 3) phones as bonus
    phones = []
    for p in item.get("phones", []):
        if isinstance(p, dict):
            phones.append({"value": p.get("value", ""), "source": p.get("source", "")})
    # 4) socials
    socials = item.get("socials", {})
    # 5) details (firmographics)
    details = item.get("details", {})

    payload = {
        "contacts": contacts,
        "phones": phones,
        "socials": socials,
        "details": details,
        "domain": item.get("domain", ""),
    }

    with sqlite3.connect(str(DB_PATH)) as db:
        db.execute("""
            UPDATE signal_classifications
            SET buyer_contacts_json = ?
            WHERE event_id = ?
        """, (json.dumps(payload, ensure_ascii=False), event_id))
    return len(contacts)


def main(limit: int = 20, min_score: float = MIN_SCORE, contacts_per_company: int = 3):
    api_key = get_api_key()
    if not api_key:
        print("ERR: OUTSCRAPER_API_KEY not set in .env")
        return
    print(f"Outscraper leads collector: limit={limit}, min_score={min_score}, contacts={contacts_per_company}")
    print(f"  API key: {api_key[:30]}...")

    # fetch unenriched events with valid domains
    with sqlite3.connect(str(DB_PATH)) as db:
        rows = db.execute("""
            SELECT cl.event_id, cl.score, e.company_name, e.company_domain
            FROM signal_classifications cl
            JOIN signal_events e ON e.event_id = cl.event_id
            WHERE cl.score >= ?
              AND e.company_domain IS NOT NULL
              AND e.company_domain NOT LIKE 'news.%'
              AND e.company_domain NOT IN ('github.com','reddit.com','greenhouse.io','lever.co','ycombinator.com','google.com')
              AND (cl.buyer_contacts_json IS NULL
                   OR cl.buyer_contacts_json NOT LIKE '%outscraper_leads%')
            ORDER BY cl.score DESC
            LIMIT ?
        """, (min_score, limit)).fetchall()

    if not rows:
        print("  nothing to enrich")
        return
    print(f"  {len(rows)} events to process")

    enriched = 0
    total_contacts = 0
    for i, r in enumerate(rows, 1):
        event_id, score, company, domain = r
        print(f"  [{i}/{len(rows)}] {domain} ({company}, score={score:.2f})...", end=" ", flush=True)
        result = fetch_leads(domain, contacts_per_company=contacts_per_company)
        if result.get("error"):
            print(f"ERR: {result.get('status_code') or result.get('exception', '?')}")
            continue
        n = save_enrichment(event_id, result)
        if n > 0:
            enriched += 1
            total_contacts += n
            print(f"✓ {n} contacts")
        else:
            print("no contacts")

    print(f"\n  enriched: {enriched}/{len(rows)}, total contacts: {total_contacts}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--min-score", type=float, default=MIN_SCORE)
    p.add_argument("--contacts", type=int, default=3)
    args = p.parse_args()
    main(args.limit, args.min_score, args.contacts)
