"""GitHub commits collector — tech change signals.
Public API, no auth needed for public repos. Rate limit 60/h unauth, 5000/h with token.
Strategy: track well-known B2B SaaS repos, detect 'migrate', 'integrate', 'switch' in commit msgs."""
import re
import time

from ..db import insert_event
from .base import http_get_json


# Watchlist: well-known B2B SaaS / infra repos (org/repo)
WATCH_REPOS = [
    "vercel/next.js",
    "supabase/supabase",
    "prisma/prisma",
    "langchain-ai/langchain",
    "anthropics/anthropic-sdk-python",
    "openai/openai-python",
    "withastro/astro",
    "remix-run/remix",
    "denoland/deno",
    "cloudflare/workerd",
    "vercel/turborepo",
    "tailwindlabs/tailwindcss",
    "shadcn-ui/ui",
    "calcom/cal.com",
    "formbricks/formbricks",
    "immich-app/immich",
    "n8n-io/n8n",
    "directus/directus",
    "nocodb/nocodb",
    "appwrite/appwrite",
    "triggerdotdev/trigger.dev",
    "pipedreamhq/pipedream",
]

# Tech change keywords (in commit message)
TECH_KEYWORDS = [
    "migrate", "migration", "migrated", "migrating",
    "integrate", "integration", "integrated",
    "switch from", "switching from", "switched from",
    "replace", "replaced", "replacing",
    "drop support", "dropping support",
    "upgrade to", "upgraded to",
    "from hubspot", "from salesforce", "from intercom",
    "to segment", "to mparticle", "to posthog",
    "to pinecone", "to weaviate", "to qdrant",
    "to anthropic", "to openai",
    "to vercel", "to cloudflare",
    "to stripe", "to lemonsqueezy",
]


def _is_relevant(commit_msg: str) -> bool:
    msg_l = commit_msg.lower()
    return any(k in msg_l for k in TECH_KEYWORDS)


def _extract_org_domain(repo_full: str) -> str:
    """Get the GitHub org as a stand-in for company_domain (we dedupe on commit sha, not domain)."""
    return f"github.com/{repo_full.split('/')[0]}"


def collect(repos: list[str] = None, since_days: int = 7) -> dict:
    if repos is None:
        repos = WATCH_REPOS
    stats = {"repos": 0, "commits": 0, "inserted": 0, "skipped_dup": 0, "errors": 0}
    from datetime import datetime, timezone, timedelta
    since = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()

    for repo in repos:
        stats["repos"] += 1
        url = f"https://api.github.com/repos/{repo}/commits?since={since}&per_page=30"
        try:
            commits = http_get_json(url, headers={"Accept": "application/vnd.github+json"})
        except Exception as e:
            print(f"  [ERR] {repo}: {e}")
            stats["errors"] += 1
            continue
        if not isinstance(commits, list):
            continue
        for c in commits:
            stats["commits"] += 1
            msg = c.get("commit", {}).get("message", "").split("\n")[0]  # first line only
            if not _is_relevant(msg):
                continue
            sha = c.get("sha", "")
            url_c = c.get("html_url", "")
            author = c.get("commit", {}).get("author", {}).get("name", "unknown")
            date = c.get("commit", {}).get("author", {}).get("date", "")[:10]
            ev_id = insert_event(
                source="github",
                company_domain=_extract_org_domain(repo),
                event_type="tech_change",
                event_subtype="commit",
                raw_text=f"{repo}: {msg}",
                source_event_id=f"gh:{sha[:12]}",
                company_name=repo,
                event_date=date,
                evidence_url=url_c,
                evidence_snippet=msg,
                raw_metadata={"repo": repo, "author": author, "sha": sha},
            )
            if ev_id:
                stats["inserted"] += 1
            else:
                stats["skipped_dup"] += 1
        time.sleep(1)  # be nice to GitHub
    return stats


def main():
    print(f"GitHub commits: {len(WATCH_REPOS)} repos, last 7 days")
    s = collect()
    print(f"  repos={s['repos']} commits={s['commits']} inserted={s['inserted']} dup={s['skipped_dup']} err={s['errors']}")


if __name__ == "__main__":
    main()
