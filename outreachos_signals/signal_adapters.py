"""Per-source adapters: turn ICP into optimized queries for each signal source.

Why adapters matter:
- Generic "{domain} hiring" returns noise
- "Why would ICP company need product" needs source-specific reasoning
- Each source has different query semantics (boolean for HN, board_token for Greenhouse, etc.)

Architecture:
  ICP -> adapter(source) -> QuerySpec(source, params, expected_signals)
  QuerySpec -> executes via on_demand_signals or direct API call
  Result -> reason = adapter.explain(query, result, icp) -> human-readable 'why this matters'
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field


@dataclass
class QuerySpec:
    """Describes what to ask each source, with rationale."""
    source: str
    params: Dict[str, Any]
    rationale: str  # "why this query is the right shape for this source"
    expected_signal: str  # "hiring" | "funding" | "intent" | etc.


@dataclass
class SignalResult:
    """A signal result with structured explanation."""
    source: str
    has_signal: bool
    raw: Dict[str, Any] = field(default_factory=dict)
    why_it_matters: str = ""  # "they're hiring 3 sales reps = growing sales team = need CRM"
    buying_signal_score: int = 0  # 0-10, how strong is the buy signal


# ============================================================
# Source adapters
# ============================================================

def greenhouse_adapter(icp: Dict[str, Any], domain: str) -> QuerySpec:
    """Greenhouse: each company has a board. We need to GUESS the board token from company name.

    Best: also use company_name (LLM-extracted from domain) to search common slug variants.
    """
    company = (icp.get("company_name") or domain.split(".")[0]).lower()
    slugs = _board_candidates(company)
    return QuerySpec(
        source="greenhouse",
        params={"slugs": slugs, "domain": domain, "max_jobs": 100},
        rationale=f"Greenhouse board_token guessed from '{company}'. Tries {len(slugs)} variants.",
        expected_signal="hiring",
    )


def _board_candidates(company: str) -> List[str]:
    base = company.lower().replace(" ", "").replace("-", "")
    return [base, f"{base}-inc", f"{base}inc", f"{base}-labs", f"{base}hq"]


def lever_adapter(icp: Dict[str, Any], domain: str) -> QuerySpec:
    """Lever: similar to Greenhouse. Different board_token site names."""
    company = (icp.get("company_name") or domain.split(".")[0]).lower()
    sites = _board_candidates(company)
    return QuerySpec(
        source="lever",
        params={"sites": sites[:3], "domain": domain},
        rationale=f"Lever site name guessed from '{company}'.",
        expected_signal="hiring",
    )


def hn_adapter(icp: Dict[str, Any], domain: str) -> QuerySpec:
    """HN Algolia: search by ICP keywords + intent.

    Better query: industry keyword + (hiring OR launch OR growing) — finds stories about
    companies in the niche that are actively growing.
    """
    kws = icp.get("industry_keywords", [])[:3]
    geo = icp.get("geo", "")
    geo_kw = "" if "global" in geo.lower() or "world" in geo.lower() else geo
    industry = icp.get("industry", "")
    # Multi-keyword search with intent
    base = " OR ".join(kws) if kws else industry
    intent = "(hiring OR launch OR growing OR 'series' OR 'raises' OR 'closed')"
    query = f"{base} {intent}"
    if geo_kw:
        query += f" {geo_kw}"
    return QuerySpec(
        source="hn",
        params={"query": query, "days": 90, "tags": "story", "limit": 10},
        rationale=f"HN: combines industry keywords '{base}' with growth/intent verbs to find active players.",
        expected_signal="intent",
    )


def github_adapter(icp: Dict[str, Any], domain: str) -> QuerySpec:
    """GitHub org activity: signals tech investment, hiring, growth."""
    company = (icp.get("company_name") or domain.split(".")[0]).lower()
    return QuerySpec(
        source="github",
        params={"org_login": company},
        rationale=f"GitHub org activity: tech investment signal. '{company}' = org login guess.",
        expected_signal="tech",
    )


def funding_adapter(icp: Dict[str, Any], domain: str) -> QuerySpec:
    """Funding news via Google News RSS.

    Better: combine company name with funding/series keywords.
    """
    company = icp.get("company_name") or domain.split(".")[0]
    query = f'"{company}" (funding OR "series" OR raises OR acquisition OR "led by")'
    return QuerySpec(
        source="funding",
        params={"query": query, "limit": 5},
        rationale=f"Google News: company name + funding verbs. Avoids generic noise.",
        expected_signal="funding",
    )


def twitter_adapter(icp: Dict[str, Any], domain: str) -> QuerySpec:
    """Twitter: search for company + intent keywords.

    Better: 2 queries — one with company_name, one with industry + intent.
    """
    company = icp.get("company_name") or domain.split(".")[0]
    kws = icp.get("industry_keywords", [])[:3]
    return QuerySpec(
        source="twitter",
        params={
            "queries": [
                f'"{company}" (hiring OR "looking for" OR "we need")',
                f'"{company}" ("alternative" OR "switching" OR recommend)',
                # Industry-wide search
                f'{" OR ".join(kws)} (hiring sales OR "evaluating" OR "in the market")' if kws else None,
            ],
            "maxTweets": 10,
        },
        rationale=f"Twitter: 3 queries — 2 for '{company}' direct mentions, 1 for industry-wide intent.",
        expected_signal="intent",
    )


def threads_adapter(icp: Dict[str, Any], domain: str) -> QuerySpec:
    """Threads: same as Twitter but different platform."""
    company = icp.get("company_name") or domain.split(".")[0]
    return QuerySpec(
        source="threads",
        params={
            "queries": [
                f'"{company}" (hiring OR "looking for")',
                f'"{company}" ("alternative" OR "switching")',
            ],
            "maxItems": 20,
        },
        rationale=f"Threads: shorter queries (1 intent verb per query).",
        expected_signal="intent",
    )


# ============================================================
# Reason generators — turn signal results into "why this matters for OUR product"
# ============================================================

def explain_why_it_matters(
    icp: Dict[str, Any],
    signals: Dict[str, Any],
    target: Dict[str, Any],
) -> str:
    """Compose a structured reason: WHY this target is a fit and HOW signals confirm it.

    Logic:
    1. Identify strongest signal type (hiring > funding > intent)
    2. Link to ICP dimensions (size, industry, geo)
    3. Articulate specific buying trigger (not generic "likely needs")
    """
    parts = []
    inferred = icp.get("inferred_product") or "your product"
    target_name = target.get("name", "This company")
    target_industry = (target.get("industry") or "").lower() or "their vertical"
    target_emp = target.get("employees", 0) or 0

    # 1. Hiring signal — strongest trigger
    if signals.get("greenhouse", {}).get("has_signal") or signals.get("lever", {}).get("has_signal"):
        jobs = (signals.get("greenhouse", {}).get("jobs", []) +
                signals.get("lever", {}).get("jobs", []))
        sales_jobs = [j for j in jobs if _is_sales_title(j.get("title", ""))]
        if sales_jobs:
            top = sales_jobs[0]
            parts.append(
                f"{target_name} is hiring {len(sales_jobs)}+ sales role(s) "
                f"(e.g. \"{top['title']}\") — sales team scaling = needs {inferred.split()[0]} infra"
            )
        elif jobs:
            parts.append(
                f"{target_name} has {len(jobs)} open roles — likely growing team, "
                f"will need {inferred.split()[0]}"
            )

    # 2. Funding signal — second strongest
    if signals.get("funding", {}).get("has_signal"):
        f = signals["funding"]
        amt = f.get("last_funding_usd", 0)
        if amt > 1_000_000:
            parts.append(
                f"recently raised ${amt/1_000_000:.1f}M {f.get('last_funding_type', '')} "
                f"= has budget for {inferred.split()[0]}"
            )

    # 3. Size-driven — they're at a stage where X is needed
    if 50 <= target_emp <= 500 and not parts:
        parts.append(
            f"{target_emp} employees = post-PMF stage, {inferred.split()[0]} needed for scale"
        )
    elif target_emp > 500 and not parts:
        parts.append(
            f"{target_emp} employees = enterprise scale, {inferred.split()[0]} rollout likely"
        )
    elif target_emp < 50 and not parts:
        parts.append(
            f"{target_emp} employees = small team, may need {inferred.split()[0]} early"
        )

    # 4. Industry + ICP match
    parts.append(
        f"matches ICP vertical ({target_industry[:40]})"
    )

    # 5. Geo fit
    geo = (target.get("country") or "").upper()
    icp_geo = (icp.get("geo") or "").lower()
    if geo and "global" not in icp_geo and icp_geo:
        icp_countries = [g.strip() for g in icp_geo.replace("/", ",").split(",") if len(g.strip()) <= 3]
        if icp_countries and geo not in icp_countries:
            parts.append(
                f"⚠️ geo mismatch (target={geo}, ICP={icp_geo})"
            )

    # 6. Twitter/Threads intent — explicit buying signal
    tw = signals.get("twitter", {})
    th = signals.get("threads", {})
    if tw.get("tweets") or th.get("threads"):
        for src_name, sig in [("Twitter", tw), ("Threads", th)]:
            if sig.get("tweets") or sig.get("threads"):
                items = sig.get("tweets") or sig.get("threads")
                top = items[0].get("text", "")[:80]
                parts.append(f"{src_name} mentions intent: \"{top}\"")
                break

    return " · ".join(parts)


def _is_sales_title(title: str) -> bool:
    t = title.lower()
    kw = ("sales", "growth", "gtm", "revenue", "partnerships", "business development", "bd",
          "marketing", "demand", "outbound", "account exec", "sdr", "bdr",
          "customer success", "csm", "cro")
    return any(k in t for k in kw)


# ============================================================
# Orchestrator
# ============================================================

def build_all_queries(icp: Dict[str, Any], domain: str) -> List[QuerySpec]:
    """Build optimized queries for ALL signal sources for a given ICP+domain."""
    return [
        greenhouse_adapter(icp, domain),
        lever_adapter(icp, domain),
        hn_adapter(icp, domain),
        github_adapter(icp, domain),
        funding_adapter(icp, domain),
        twitter_adapter(icp, domain),
        threads_adapter(icp, domain),
    ]


# CLI test
if __name__ == "__main__":
    icp = {
        "company_name": "lemlist",
        "niche": "B2B SaaS / Sales Engagement",
        "industry": "Software / MarTech",
        "industry_keywords": ["sales engagement", "outbound", "lead generation"],
        "geo": "Global",
    }
    for spec in build_all_queries(icp, "vercel.com"):
        print(f"\n{spec.source}:")
        print(f"  rationale: {spec.rationale}")
        print(f"  params: {spec.params}")
        print(f"  expected: {spec.expected_signal}")
