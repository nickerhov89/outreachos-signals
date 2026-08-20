import urllib.request
"""Apify Threads collector.
Actor: search-threads-by-keywords (Apify Store).
Default actor ID: dsRqXOFKRiJxRtskL — override via APIFY_ACTOR_THREADS env."""
import json
import os
import time

from ..db import insert_event
from .base import http_get, http_get_json, load_niches

APIFY_BASE = "https://api.apify.com/v2"
DEFAULT_ACTOR = "dsRqXOFKRiJxRtskL"  # search-threads-by-keywords


def _get_token() -> str:
    return os.environ.get("APIFY_TOKEN") or __import__("outreachos_signals.db", fromlist=["ENV"]).ENV.get("APIFY_TOKEN", "")


def run_actor(actor_id: str, run_input: dict) -> str:
    """Start actor run, return run_id. Polls until done (max 5 min)."""
    token = _get_token()
    if not token:
        raise RuntimeError("APIFY_TOKEN not set in .env")
    url = f"{APIFY_BASE}/acts/{actor_id}/runs?token={token}"
    body = json.dumps(run_input).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())
    return data["data"]["id"]


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
    raise RuntimeError(f"Apify run {run_id} timed out after {max_wait}s")


def get_dataset_items(actor_id: str, run_id: str) -> list[dict]:
    token = _get_token()
    dataset_id = None
    # fetch run to get datasetId
    with urllib.request.urlopen(
        f"{APIFY_BASE}/acts/{actor_id}/runs/{run_id}?token={token}", timeout=30
    ) as r:
        d = json.loads(r.read())
    dataset_id = d["data"]["defaultDatasetId"]
    items: list[dict] = []
    offset = 0
    while True:
        url = f"{APIFY_BASE}/datasets/{dataset_id}/items?token={token}&offset={offset}&limit=100"
        with urllib.request.urlopen(url, timeout=60) as r:
            batch = json.loads(r.read())
        items.extend(batch)
        if len(batch) < 100:
            break
        offset += 100
    return items


def collect(max_per_niche: int = 20) -> dict:
    stats = {"runs": 0, "inserted": 0, "skipped_dup": 0, "errors": 0}
    actor = os.environ.get("APIFY_ACTOR_THREADS") or DEFAULT_ACTOR
    token = _get_token()
    if not token:
        print("  [skip] APIFY_TOKEN not set")
        return stats
    niches = load_niches()

    for niche in niches:
        keywords = niche.get("threads_keywords", [])
        if not keywords:
            continue
        # Run one search per niche with all keywords
        run_input = {
            "keywords": keywords,
            "maxItems": max_per_niche,
            "sort": "newest",
        }
        try:
            run_id = run_actor(actor, run_input)
            stats["runs"] += 1
            result = wait_run(actor, run_id, max_wait=180)
            if result["data"]["status"] != "SUCCEEDED":
                print(f"  [WARN] niche {niche['id']} {niche['name']}: {result['data']['status']}")
                stats["errors"] += 1
                continue
            items = get_dataset_items(actor, run_id)
            for post in items:
                # Post fields vary by actor; map common
                text = post.get("text") or post.get("caption") or post.get("content") or ""
                url = post.get("url") or post.get("postUrl") or ""
                post_id = post.get("id") or post.get("postId") or url
                author = post.get("author") or post.get("user") or {}
                username = author.get("username") if isinstance(author, dict) else str(author)
                # Try to find company domain
                # For MVP: use 'threads.net' as source dedup key (one post → one niche)
                company_domain = post.get("link") and (post["link"].split("/")[2] if "://" in post["link"] else "")
                if not company_domain:
                    company_domain = f"threads:{username}" if username else "threads.net"
                ev_id = insert_event(
                    source="threads",
                    company_domain=company_domain,
                    event_type="pain" if any(w in text.lower() for w in ["frustrated", "looking for", "alternative", "switching from"]) else "trigger",
                    event_subtype="mention",
                    raw_text=text[:500],
                    source_event_id=f"threads:{post_id}",
                    company_name=username,
                    event_date=post.get("timestamp", "")[:10] if post.get("timestamp") else None,
                    evidence_url=url,
                    evidence_snippet=text[:300],
                    raw_metadata={"niche_id": niche["id"], "author": username, "keyword": keywords[0] if keywords else None},
                )
                if ev_id:
                    stats["inserted"] += 1
                else:
                    stats["skipped_dup"] += 1
        except Exception as e:
            print(f"  [ERR] niche {niche['id']}: {e}")
            stats["errors"] += 1
    return stats


def main():
    print("Apify Threads: searching across 10 niches")
    s = collect()
    print(f"  runs={s['runs']} inserted={s['inserted']} dup={s['skipped_dup']} err={s['errors']}")


if __name__ == "__main__":
    main()
