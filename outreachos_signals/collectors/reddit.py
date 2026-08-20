"""Reddit 'looking for X' / 'frustrated with X' pain signal collector.
JSON API, free. Targets r/sales, r/sysadmin, r/machinelearning, r/sysadmin, r/devops, r/b2bsales."""
import json
import time
import urllib.error
import urllib.request
import urllib.parse

from ..db import insert_event


SUBREDDITS = [
    "sales", "sysadmin", "machinelearning", "devops", "b2bsales",
    "dataengineering", "marketing", "productmanagement", "cybersecurity",
    "fintech",
]

# Phrases that indicate buying intent / pain
PAIN_PHRASES = [
    "looking for", "looking to switch", "alternative to", "alternatives to",
    "tired of", "frustrated with", "hate", "anyone using", "recommend",
    "vs ", "comparison", "replacing", "migrating from", "switching from",
]


def _search_reddit(subreddit: str, query: str, limit: int = 25) -> list[dict]:
    """Use Reddit JSON API. Sort by new, last 7d."""
    url = (
        f"https://www.reddit.com/r/{subreddit}/search.json"
        f"?q={urllib.parse.quote(query)}&restrict_sr=1&sort=new&t=week&limit={limit}"
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "outreachos-signals/0.1 (B2B signal finder)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"  [ERR] r/{subreddit}: {e}")
        return []
    return [c["data"] for c in data.get("data", {}).get("children", [])]


def collect() -> dict:
    stats = {"queries": 0, "items": 0, "inserted": 0, "skipped_dup": 0, "errors": 0}
    queries = [
        "looking for CRM", "looking for ATS", "alternative to Salesforce",
        "alternative to HubSpot", "alternative to Outreach", "alternative to Instantly",
        "looking for lead generation", "looking for data platform", "alternative to Snowflake",
        "looking for payment processor", "looking for KYC", "looking for LMS",
        "looking for marketplace platform", "looking for security tool",
    ]
    for sub in SUBREDDITS:
        for q in queries:
            stats["queries"] += 1
            posts = _search_reddit(sub, q, limit=15)
            time.sleep(1)  # Reddit rate limit: 60 req/min unauth
            for p in posts:
                stats["items"] += 1
                title = p.get("title", "")
                selftext = (p.get("selftext") or "")[:500]
                url = "https://reddit.com" + p.get("permalink", "")
                post_id = p.get("id", "")
                author = p.get("author", "")
                # Heuristic: company name in title or selftext
                # Reddit doesn't show company, but often "we" / "our company" hints
                is_buyer = "we" in selftext.lower() or "we" in title.lower() or "our team" in selftext.lower()
                if not is_buyer:
                    continue  # skip random complaints
                # Try to extract company domain
                company = "unknown"
                # Look for "at Company" or "Company Inc" pattern
                import re
                m = re.search(r"\bat\s+([A-Z][\w& ]{1,30}(?:\s+(?:Inc|LLC|Ltd|Co))?)\b", selftext or title)
                if m:
                    company = m.group(1).strip()
                # Check pain phrase
                text_l = (title + " " + selftext).lower()
                if not any(p in text_l for p in PAIN_PHRASES):
                    continue
                ev_id = insert_event(
                    source="reddit",
                    company_domain=f"reddit:{author}" if author else "reddit.com",
                    event_type="pain",
                    event_subtype="looking_for",
                    raw_text=f"[r/{sub}] {title}",
                    source_event_id=f"reddit:{post_id}",
                    company_name=company,
                    evidence_url=url,
                    evidence_snippet=selftext[:300],
                    raw_metadata={"subreddit": sub, "author": author, "score": p.get("score", 0)},
                )
                if ev_id:
                    stats["inserted"] += 1
                else:
                    stats["skipped_dup"] += 1
    return stats


def main():
    print(f"Reddit: {len(SUBREDDITS)} subs, ~{14} queries")
    s = collect()
    print(f"  queries={s['queries']} items={s['items']} inserted={s['inserted']} dup={s['skipped_dup']} err={s['errors']}")


if __name__ == "__main__":
    main()
