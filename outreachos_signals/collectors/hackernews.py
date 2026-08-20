"""Hacker News 'Ask HN' / 'Show HN' collector via Algolia API.
Free, no auth. Targets posts about tools we're watching."""
import json
import time
import urllib.parse
import urllib.request

from ..db import insert_event


# Phrases that signal a tool is being built / evaluated / replaced
SIGNAL_PHRASES = [
    "Ask HN: ", "Show HN: ",
    "alternative to", "alternatives to",
    "migrating from", "switching from",
    "replace", "vs ", "comparison",
    "frustrated with", "tired of",
]

# Search queries to monitor per niche
QUERIES = [
    "Ask HN: CRM",
    "Ask HN: ATS",
    "Ask HN: lead generation",
    "Show HN: CRM",
    "Show HN: AI agent",
    "Ask HN: alternative to Salesforce",
    "Ask HN: alternative to HubSpot",
    "Ask HN: data engineering",
    "Show HN: devops",
    "Ask HN: marketplace",
    "Ask HN: LMS",
    "Ask HN: payment processing",
    "Show HN: security",
    "Ask HN: SOC 2",
]


def _search_algolia(query: str, hits_per_page: int = 30) -> list[dict]:
    url = (
        f"http://hn.algolia.com/api/v1/search?query={urllib.parse.quote(query)}"
        f"&tags=story&hitsPerPage={hits_per_page}&numericFilters=created_at_i>{(time.time() - 7*86400)}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "outreachos-signals/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"  [ERR] {query}: {e}")
        return []
    return data.get("hits", [])


def collect() -> dict:
    stats = {"queries": 0, "items": 0, "inserted": 0, "skipped_dup": 0, "errors": 0}
    for q in QUERIES:
        stats["queries"] += 1
        hits = _search_algolia(q, hits_per_page=20)
        for hit in hits:
            stats["items"] += 1
            title = hit.get("title") or ""
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            story_id = hit.get("objectID", "")
            author = hit.get("author", "")
            # Skip pure link posts, focus on text posts
            text = hit.get("story_text") or ""
            ev_type = "trigger" if "Show HN" in title else "pain"
            ev_subtype = "show_hn" if "Show HN" in title else "ask_hn"
            ev_id = insert_event(
                source="hackernews",
                company_domain=f"hn:{author}" if author else "news.ycombinator.com",
                event_type=ev_type,
                event_subtype=ev_subtype,
                raw_text=f"[HN] {title}",
                source_event_id=f"hn:{story_id}",
                company_name=author,
                evidence_url=url,
                evidence_snippet=text[:300] if text else title,
                raw_metadata={"author": author, "points": hit.get("points", 0), "comments": hit.get("num_comments", 0)},
            )
            if ev_id:
                stats["inserted"] += 1
            else:
                stats["skipped_dup"] += 1
        time.sleep(0.3)
    return stats


def main():
    print(f"Hacker News: {len(QUERIES)} queries, last 7 days")
    s = collect()
    print(f"  queries={s['queries']} items={s['items']} inserted={s['inserted']} dup={s['skipped_dup']} err={s['errors']}")


if __name__ == "__main__":
    main()
