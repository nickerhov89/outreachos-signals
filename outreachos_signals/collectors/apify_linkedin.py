"""Apify LinkedIn Profile Changes collector.
Actor options:
  - valig/linkedin-profile-scraper  (~$0.05/lookup)
  - apima/linkedin-profile-scraper  (alternative)
We feed a watchlist of people OR companies; actor returns recent job changes."""
import json
import os
import time
import urllib.error
import urllib.request

from ..db import insert_event
from .base import load_niches

APIFY_BASE = "https://api.apify.com/v2"
# Pick a known LinkedIn profile actor. We'll let user override via env.
DEFAULT_ACTOR = os.environ.get("APIFY_ACTOR_LINKEDIN", "bebity/linkedin-profile-scraper")


def _get_token() -> str:
    from ..db import ENV
    return ENV.get("APIFY_TOKEN", "")


def run_actor(actor_id: str, run_input: dict) -> str:
    token = _get_token()
    if not token:
        raise RuntimeError("APIFY_TOKEN not set")
    url = f"{APIFY_BASE}/acts/{actor_id}/runs?token={token}"
    req = urllib.request.Request(
        url, data=json.dumps(run_input).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())["data"]["id"]


def wait_run(actor_id: str, run_id: str, max_wait: int = 300) -> dict:
    token = _get_token()
    url = f"{APIFY_BASE}/acts/{actor_id}/runs/{run_id}?token={token}"
    start = time.time()
    while time.time() - start < max_wait:
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.loads(r.read())
        status = data["data"]["status"]
        if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            return data
        time.sleep(5)
    raise RuntimeError(f"Apify run {run_id} timed out")


def fetch_items(actor_id: str, run_id: str) -> list[dict]:
    token = _get_token()
    with urllib.request.urlopen(
        f"{APIFY_BASE}/acts/{actor_id}/runs/{run_id}?token={token}", timeout=30
    ) as r:
        ds = json.loads(r.read())["data"]["defaultDatasetId"]
    items: list[dict] = []
    offset = 0
    while True:
        with urllib.request.urlopen(
            f"{APIFY_BASE}/datasets/{ds}/items?token={token}&offset={offset}&limit=100",
            timeout=60,
        ) as r:
            batch = json.loads(r.read())
        items.extend(batch)
        if len(batch) < 100:
            break
        offset += 100
    return items


# Watchlist: roles that indicate buyer at B2B SaaS. User can override via .env WATCH_TITLES.
DEFAULT_WATCH_TITLES = [
    "VP Sales", "VP RevOps", "VP Marketing", "VP Product", "VP Engineering",
    "VP Customer Success", "VP People", "VP Finance", "CFO", "CRO", "CMO",
    "CTO", "CISO", "Head of Sales", "Head of Marketing", "Head of Growth",
    "Head of RevOps", "Head of Product", "Head of Customer Success",
    "Director of Sales", "Director of Marketing", "Director of Engineering",
    "Director of Security", "Director of Finance", "Director of People",
    "Head of Data", "Head of AI", "Head of Platform",
]


def collect() -> dict:
    stats = {"runs": 0, "inserted": 0, "skipped_dup": 0, "errors": 0}
    token = _get_token()
    if not token:
        print("  [skip] APIFY_TOKEN not set")
        return stats
    actor = DEFAULT_ACTOR
    titles = [t.strip() for t in os.environ.get("WATCH_TITLES", "").split(",") if t.strip()] or DEFAULT_WATCH_TITLES
    # Run with title search
    run_input = {
        "searchQuery": " OR ".join(titles[:20]),  # cap at 20 to avoid actor limits
        "maxItems": 100,
        "scrapeRecent": True,  # only recent changes
    }
    try:
        run_id = run_actor(actor, run_input)
        stats["runs"] += 1
        result = wait_run(actor, run_id, max_wait=180)
        if result["data"]["status"] != "SUCCEEDED":
            print(f"  [WARN] {result['data']['status']}")
            stats["errors"] += 1
            return stats
        items = fetch_items(actor, run_id)
        for profile in items:
            # Profile structure varies; map common fields
            name = profile.get("name") or profile.get("fullName") or profile.get("full_name") or ""
            current_title = profile.get("title") or profile.get("headline") or ""
            current_company = profile.get("company") or profile.get("companyName") or profile.get("currentCompany") or ""
            linkedin_url = profile.get("linkedinUrl") or profile.get("url") or profile.get("profileUrl") or ""
            profile_id = profile.get("id") or profile.get("publicIdentifier") or linkedin_url
            # Heuristic: was there a recent title change? Many actors return 'previousPositions' or 'experience'
            previous_titles = profile.get("previousPositions") or profile.get("experience") or []
            recent_change = any(
                "Days" in str(p.get("duration", "")) or "months" in str(p.get("duration", ""))
                for p in (previous_titles if isinstance(previous_titles, list) else [])
            )
            if not current_company:
                continue
            # Use company name as domain placeholder; LinkedIn profile_id is the dedup key
            ev_id = insert_event(
                source="linkedin_change",
                company_domain=current_company.lower().replace(" ", "") + ".com",
                event_type="trigger",
                event_subtype="job_change",
                raw_text=f"{name} ({current_title}) joined {current_company}",
                source_event_id=f"li:{profile_id}",
                company_name=current_company,
                evidence_url=linkedin_url,
                evidence_snippet=f"{name} — {current_title}",
                raw_metadata={"name": name, "title": current_title, "linkedin": linkedin_url, "recent_change": recent_change},
            )
            if ev_id:
                stats["inserted"] += 1
            else:
                stats["skipped_dup"] += 1
    except Exception as e:
        print(f"  [ERR] {e}")
        stats["errors"] += 1
    return stats


def main():
    print("Apify LinkedIn job changes: scanning")
    s = collect()
    print(f"  runs={s['runs']} inserted={s['inserted']} dup={s['skipped_dup']} err={s['errors']}")


if __name__ == "__main__":
    main()
