"""Tech stack change detector — replaces BuiltWith.
Parses recent hiring/job descriptions for competitor tool mentions.
Patterns: 'experience with X', 'migrating from X', 'knowledge of X'."""
import json
import re
import sqlite3
from datetime import datetime, timezone, timedelta

from ..db import conn, insert_event


# Popular tools to detect in job descriptions
TRACKED_TOOLS = {
    # CRM / Sales
    "Salesforce": "crm", "HubSpot": "crm", "Pipedrive": "crm", "Zoho": "crm",
    "Outreach": "sales_eng", "Salesloft": "sales_eng", "Apollo": "sales_eng",
    "Instantly": "sales_eng", "Smartlead": "sales_eng", "Lemlist": "sales_eng",
    "Clay": "sales_eng", "Reply": "sales_eng", "Lemlist": "sales_eng",
    # Marketing
    "Marketo": "martech", "Pardot": "martech", "Mailchimp": "martech",
    "Iterable": "martech", "Customer.io": "martech", "Braze": "martech",
    "Klaviyo": "martech", "Mixpanel": "analytics", "Amplitude": "analytics",
    "Segment": "analytics", "mParticle": "analytics", "RudderStack": "analytics",
    # Data / AI
    "Snowflake": "data", "Databricks": "data", "BigQuery": "data",
    "Redshift": "data", "Looker": "data", "Tableau": "data",
    "dbt": "data", "Airflow": "data", "Fivetran": "data",
    "Pinecone": "ai", "Weaviate": "ai", "Qdrant": "ai",
    "LangChain": "ai", "LlamaIndex": "ai",
    # HR / Recruiting
    "Greenhouse": "hr", "Lever": "hr", "Workable": "hr", "Ashby": "hr",
    "Gem": "hr", "Eightfold": "hr", "iCIMS": "hr",
    # Dev / Cloud
    "Kubernetes": "devops", "Terraform": "devops", "Ansible": "devops",
    "Jenkins": "devops", "GitLab": "devops", "GitHub Actions": "devops",
    "Vercel": "devops", "Cloudflare": "devops", "Fastly": "devops",
    "Datadog": "observability", "Sentry": "observability", "Datadog": "observability",
    # Payments
    "Stripe": "payments", "Adyen": "payments", "Plaid": "payments",
    "Checkout.com": "payments", "Lemon Squeezy": "payments",
}

# Patterns that indicate switching / evaluating
SWITCH_PATTERNS = [
    r"migrating\s+from\s+([A-Z][\w\.]+)",
    r"switch(?:ing)?\s+from\s+([A-Z][\w\.]+)",
    r"replac(?:ing|ed)\s+([A-Z][\w\.]+)",
    r"experience\s+with\s+([A-Z][\w\.]+)",
    r"knowledge\s+of\s+([A-Z][\w\.]+)",
    r"familiar(?:ity)?\s+with\s+([A-Z][\w\.]+)",
    r"previously\s+used\s+([A-Z][\w\.]+)",
]


def _scan_text(text: str) -> list[dict]:
    """Return list of {tool, action, snippet} matches."""
    if not text:
        return []
    matches = []
    for pattern in SWITCH_PATTERNS:
        for m in re.finditer(pattern, text):
            tool_name = m.group(1).strip()
            # Strip trailing punctuation
            tool_name = tool_name.rstrip(".,;:")
            # Only count if it's a tracked tool
            canonical = next((t for t in TRACKED_TOOLS if t.lower() == tool_name.lower()), None)
            if not canonical:
                # Maybe direct match without exact case
                for t in TRACKED_TOOLS:
                    if tool_name.lower() in t.lower() or t.lower() in tool_name.lower():
                        canonical = t
                        break
            if canonical:
                action = "switch" if any(k in pattern for k in ["migrat", "switch", "replac"]) else "experience"
                # Snippet around match
                start = max(0, m.start() - 30)
                end = min(len(text), m.end() + 30)
                matches.append({
                    "tool": canonical,
                    "category": TRACKED_TOOLS[canonical],
                    "action": action,
                    "snippet": text[start:end],
                })
    return matches


def collect(since_days: int = 30) -> dict:
    stats = {"scanned": 0, "inserted": 0, "skipped_dup": 0, "errors": 0}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
    with conn() as c:
        rows = c.execute("""
            SELECT event_id, company_domain, company_name, raw_text, evidence_snippet
            FROM signal_events
            WHERE event_type = 'hiring' AND collected_at > ?
        """, (cutoff,)).fetchall()
    for r in rows:
        stats["scanned"] += 1
        text = (r["raw_text"] or "") + " " + (r["evidence_snippet"] or "")
        for match in _scan_text(text):
            action_event = "tech_change" if match["action"] == "switch" else "tool_mentioned"
            ev_id = insert_event(
                source="job_text_tech",
                company_domain=r["company_domain"],
                event_type=action_event,
                event_subtype=match["category"],
                raw_text=f"{r['company_name']} mentions {match['tool']} ({match['action']})",
                source_event_id=f"jobtech:{r['event_id'][:8]}:{match['tool']}",
                company_name=r["company_name"],
                evidence_snippet=match["snippet"],
                raw_metadata={"tool": match["tool"], "category": match["category"], "action": match["action"], "source_event": r["event_id"]},
            )
            if ev_id:
                stats["inserted"] += 1
            else:
                stats["skipped_dup"] += 1
    return stats


def main():
    print("Tech stack detector: scanning recent hiring events (last 30d)")
    s = collect()
    print(f"  scanned={s['scanned']} inserted={s['inserted']} dup={s['skipped_dup']}")


if __name__ == "__main__":
    main()
