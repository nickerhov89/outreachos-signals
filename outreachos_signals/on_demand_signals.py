"""On-demand signal enrichment per company domain.

Used in /wizard_discover AFTER LLM generates 20 candidate companies.
Each function returns:
  {"has_signal": bool, "signal_type": str, "title": str, "url": str, "score": float}

No DB prefill — pure on-demand HTTP calls to free APIs:
  - Greenhouse: boards-api.greenhouse.io (free, no auth)
  - Lever: api.lever.co (free, no auth)
  - HackerNews Algolia: hn.algolia.com (free)
  - GitHub: api.github.com (free, rate-limited but ok for on-demand)
  - Google News RSS: news.google.com (free)

Caching: results cached in signal_events with source='on_demand_<api>'.
"""
import urllib.request
import urllib.parse
import json
import re
import time
from typing import List, Dict, Any

UA = "Mozilla/5.0 OutreachOS/0.2 (on-demand signals)"


def _http(url: str, timeout: int = 8) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ============================================================
# Greenhouse direct API — FREE
# https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs
# ============================================================

def _board_candidates(domain: str) -> List[str]:
    """Generate possible Greenhouse board tokens from a domain.
    Examples:
        vercel.com -> ['vercel', 'vercel-inc', 'vercellabs']
        checkr.com -> ['checkr']
        try common variants."""
    base = domain.split('.')[0].lower()
    return [
        base,
        f"{base}-inc",
        f"{base}inc",
        f"{base}-labs",
        f"{base}labs",
        f"{base}-hq",
    ]


def greenhouse_signal(domain: str) -> Dict[str, Any]:
    """Check if domain has Greenhouse board with open jobs.
    Returns {has_signal, count, jobs:[{title, dept, url}], score}"""
    for token in _board_candidates(domain)[:4]:
        try:
            url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=false"
            data = json.loads(_http(url, timeout=5))
            jobs = data.get("jobs", [])
            if not jobs:
                continue
            # Pick the most LPR-relevant jobs
            sales_jobs = [j for j in jobs if _is_sales_title(j.get("title", ""))]
            top_jobs = (sales_jobs + jobs)[:5]
            return {
                "has_signal": True,
                "count": len(jobs),
                "jobs": [{"title": j.get("title", ""), "dept": (j.get("departments") or [{}])[0].get("name", ""),
                          "url": j.get("absolute_url", "")} for j in top_jobs],
                "score": min(1.0, len(jobs) / 10.0),
                "board_token": token,
            }
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            return {"has_signal": False, "score": 0, "error": f"{e.code}"}
        except Exception as e:
            return {"has_signal": False, "score": 0, "error": str(e)[:50]}
    return {"has_signal": False, "score": 0, "jobs": []}


# ============================================================
# Lever direct API — FREE
# https://api.lever.co/v0/postings/{site}?mode=json
# ============================================================

def lever_signal(domain: str) -> Dict[str, Any]:
    for token in _board_candidates(domain)[:3]:
        try:
            url = f"https://api.lever.co/v0/postings/{token}?mode=json"
            data = json.loads(_http(url, timeout=5))
            if not isinstance(data, list) or not data:
                continue
            sales_jobs = [j for j in data if _is_sales_title(j.get("text", ""))]
            top_jobs = (sales_jobs + data)[:5]
            return {
                "has_signal": True,
                "count": len(data),
                "jobs": [{"title": j.get("text", ""), "dept": (j.get("categories") or {}).get("team", ""),
                          "url": j.get("hostedUrl", "")} for j in top_jobs],
                "score": min(1.0, len(data) / 10.0),
                "site": token,
            }
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            return {"has_signal": False, "score": 0}
        except Exception:
            return {"has_signal": False, "score": 0}
    return {"has_signal": False, "score": 0, "jobs": []}


# ============================================================
# HackerNews Algolia — FREE
# ============================================================

def hn_signal(domain: str) -> Dict[str, Any]:
    """Search HN for company mentions in last 90 days."""
    try:
        # search for domain and company name
        q = urllib.parse.quote(f"\"{domain}\"")
        url = f"http://hn.algolia.com/api/v1/search?query={q}&tags=story&numericFilters=created_at_i>{int(time.time())-90*86400}&hitsPerPage=5"
        data = json.loads(_http(url, timeout=5))
        hits = data.get("hits", [])
        if not hits:
            return {"has_signal": False, "score": 0, "count": 0}
        return {
            "has_signal": True,
            "count": len(hits),
            "stories": [{"title": h.get("title", ""), "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                         "points": h.get("points", 0)} for h in hits[:3]],
            "score": min(1.0, len(hits) / 5.0),
        }
    except Exception:
        return {"has_signal": False, "score": 0, "count": 0}


# ============================================================
# GitHub org — FREE, soft rate limit
# ============================================================

def github_signal(domain: str) -> Dict[str, Any]:
    """Look for GitHub org matching the company domain."""
    base = domain.split('.')[0].lower()
    try:
        url = f"https://api.github.com/orgs/{base}"
        data = json.loads(_http(url, timeout=5))
        public_repos = data.get("public_repos", 0)
        return {
            "has_signal": public_repos > 0,
            "public_repos": public_repos,
            "score": min(1.0, public_repos / 30.0),
            "org_url": data.get("html_url", ""),
        }
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"has_signal": False, "score": 0}
        return {"has_signal": False, "score": 0, "error": str(e.code)}
    except Exception:
        return {"has_signal": False, "score": 0}


# ============================================================
# Google News RSS — funding/announcements
# ============================================================

def funding_signal(domain: str) -> Dict[str, Any]:
    try:
        q = urllib.parse.quote(f'"{domain}" (funding OR raises OR "series" OR acquisition)')
        url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
        body = _http(url, timeout=5).decode("utf-8", errors="ignore")
        items = re.findall(r"<item>.*?<title>(.*?)</title>.*?<pubDate>(.*?)</pubDate>", body, re.DOTALL)
        if not items:
            return {"has_signal": False, "score": 0, "count": 0}
        return {
            "has_signal": True,
            "count": len(items),
            "news": [{"title": _clean_cdata(t), "date": d} for t, d in items[:3]],
            "score": min(1.0, len(items) / 3.0),
        }
    except Exception:
        return {"has_signal": False, "score": 0}


def _clean_cdata(text: str) -> str:
    return re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text).strip()


# ============================================================
# Helpers
# ============================================================

SALES_TITLE_KW = (
    "sales", "growth", "gtm", "revenue", "partnerships", "business development", "bd",
    "marketing", "demand gen", "demand generation", "outbound", "account executive",
    "customer success", "cs ", "csm", "cro",
)


def _is_sales_title(title: str) -> bool:
    t = (title or "").lower()
    return any(kw in t for kw in SALES_TITLE_KW)


def aggregate_signal(domain: str, fast: bool = True) -> Dict[str, Any]:
    """Run all signal sources for one domain. Returns aggregated result.

    fast=True: parallel-ish (sequential but with short timeouts, ~5s total).
    Returns:
        {
          domain, total_score, sources: {greenhouse:..., lever:..., hn:..., github:..., funding:...},
          primary_signal: 'hiring'|'news'|'hn'|'github'|'none',
          reason: human-readable boost reason
        }
    """
    sources = {}
    sources["greenhouse"] = greenhouse_signal(domain)
    sources["lever"] = lever_signal(domain)
    sources["hn"] = hn_signal(domain)
    sources["github"] = github_signal(domain)
    sources["funding"] = funding_signal(domain)

    # Pick primary signal — hiring > funding > hn > github
    primary = "none"
    if sources["greenhouse"].get("has_signal") or sources["lever"].get("has_signal"):
        primary = "hiring"
    elif sources["funding"].get("has_signal"):
        primary = "news"
    elif sources["hn"].get("has_signal"):
        primary = "hn"
    elif sources["github"].get("has_signal"):
        primary = "github"

    total_score = sum(s.get("score", 0) for s in sources.values())
    return {
        "domain": domain,
        "primary_signal": primary,
        "total_score": round(total_score, 2),
        "sources": sources,
    }


def boost_reason(signal: Dict[str, Any], base_reason: str) -> str:
    """Add signal evidence to target reason."""
    primary = signal.get("primary_signal", "none")
    sources = signal.get("sources", {})
    if primary == "hiring":
        gh = sources.get("greenhouse", {})
        lv = sources.get("lever", {})
        n = gh.get("count", 0) + lv.get("count", 0)
        sales_jobs = []
        for j in (gh.get("jobs", []) + lv.get("jobs", []))[:3]:
            if _is_sales_title(j.get("title", "")):
                sales_jobs.append(j["title"])
        if sales_jobs:
            return f"{base_reason} — HIRING NOW ({n} jobs, incl. {sales_jobs[0]})"
        return f"{base_reason} — HIRING NOW ({n} open jobs)"
    if primary == "news":
        news = sources.get("funding", {}).get("news", [])
        if news:
            return f"{base_reason} — {news[0]['title'][:80]}"
    if primary == "hn":
        stories = sources.get("hn", {}).get("stories", [])
        if stories:
            return f"{base_reason} — Trending on HN: {stories[0]['title'][:60]}"
    if primary == "github":
        repos = sources.get("github", {}).get("public_repos", 0)
        if repos:
            return f"{base_reason} — Active OSS ({repos} public repos)"
    return base_reason


def pick_target_title(signal: Dict[str, Any], default: str = "VP Sales") -> str:
    """Pick the most relevant LPR based on actual open jobs."""
    sources = signal.get("sources", {})
    jobs = []
    for j in sources.get("greenhouse", {}).get("jobs", []) + sources.get("lever", {}).get("jobs", []):
        t = j.get("title", "")
        if _is_sales_title(t):
            jobs.append(t)
    if not jobs:
        return default
    # Map job titles to LPR
    job_str = " ".join(jobs).lower()
    if "head of sales" in job_str or "vp sales" in job_str or "vp, sales" in job_str:
        return "VP Sales"
    if "cro" in job_str or "chief revenue" in job_str:
        return "CRO"
    if "head of growth" in job_str or "vp growth" in job_str:
        return "VP Growth"
    if "head of marketing" in job_str or "vp marketing" in job_str or "cmo" in job_str:
        return "VP Marketing"
    if "partnerships" in job_str:
        return "Head of Partnerships"
    if "revenue operations" in job_str or "revops" in job_str:
        return "VP RevOps"
    if "head of demand" in job_str or "demand gen" in job_str:
        return "VP Demand Gen"
    if "head of gtm" in job_str:
        return "Head of GTM"
    if "head of customer success" in job_str or "vp customer success" in job_str:
        return "VP Customer Success"
    if "head of business development" in job_str or "vp bd" in job_str:
        return "VP BD"
    return jobs[0][:40]  # first sales job title


# CLI test
if __name__ == "__main__":
    import sys
    domain = sys.argv[1] if len(sys.argv) > 1 else "vercel.com"
    t0 = time.time()
    sig = aggregate_signal(domain)
    print(json.dumps(sig, indent=2)[:1500])
    print(f"\n[{time.time()-t0:.1f}s]")
