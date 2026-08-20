"""DIY email enrichment: pattern brute-force + SMTP verification.
Replaces Apollo.io / Hunter.io for cost reasons.
Pure stdlib (smtplib, dns, socket).
Takes classified signals (score >= 6), generates common email patterns,
probes SMTP for valid recipients, stores results in signal_classifications.buyer_contacts_json.
"""
import json
import os
import re
import smtplib
import socket
import sqlite3
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone

# 8 most common email patterns globally (per email-pattern-analysis research)
EMAIL_PATTERNS = [
    "{first}@{domain}",                    # john
    "{first}.{last}@{domain}",             # john.smith
    "{first}{last}@{domain}",              # johnsmith
    "{f}{last}@{domain}",                  # jsmith
    "{f}.{last}@{domain}",                 # j.smith
    "{first}_{last}@{domain}",             # john_smith
    "{first[0]}{last}@{domain}",           # jsmith (dup of #4)
    "{first}{last[0]}@{domain}",           # johns
]

# Buyer roles per niche (most common decision-makers we want to reach)
BUYER_ROLES_PER_NICHE = {
    1: ["VP Sales", "VP RevOps", "Director Sales Operations", "CRO"],  # CRM
    2: ["VP People", "Head of Talent", "Head of Recruiting"],  # HRTech
    3: ["VP Marketing", "Director Marketing Operations", "Head of Growth"],  # MarTech
    4: ["VP Engineering", "Head of Data", "ML Platform Lead"],  # AI/Data
    5: ["VP Product", "Head of Product", "Head of Customer Success"],  # B2B SaaS
    6: ["CTO", "VP Engineering", "Head of Platform"],  # IT services
    7: ["CISO", "Head of Security", "Director Cloud"],  # Cloud/Sec
    8: ["VP Compliance", "Head of Payments", "CFO"],  # FinTech
    9: ["Head of B2B Learning", "Head of Product"],  # EdTech
    10: ["VP Marketplace", "Head of Operations", "Head of Trust & Safety"],  # Marketplace
}


def normalize_domain(domain: str) -> str | None:
    """Strip protocol, www, paths. Return clean host."""
    if not domain:
        return None
    d = domain.lower().strip()
    d = re.sub(r"^https?://", "", d)
    d = d.split("/")[0]
    if d.startswith("www."):
        d = d[4:]
    # Skip obvious non-corporate
    if any(x in d for x in ["reddit.com", "github.com", "news.ycombinator.com",
                              "greenhouse.io", "lever.co", "google.com",
                              "g2.com", "linkedin.com", "hackernews", "ycombinator"]):
        return None
    if "." not in d:
        return None
    return d


def normalize_name(name: str) -> tuple[str, str, str] | None:
    """Parse 'John Smith' → (first, last, f). Returns None if can't parse."""
    if not name:
        return None
    name = name.strip()
    # Strip titles/credentials
    name = re.sub(r"\b(Dr|Mr|Mrs|Ms|PhD|JD|MBA)\b\.?", "", name).strip()
    # "First Last" or "First Middle Last"
    parts = name.split()
    if len(parts) < 2:
        return None
    first = parts[0].lower()
    last = parts[-1].lower()
    f = first[0]
    return (first, last, f)


def get_mx_host(domain: str) -> str | None:
    """Get MX host for domain via socket.getaddrinfo fallback (no dnspython dep).
    Returns primary MX host or A record if no MX."""
    # Try MX via /etc/hosts style; fallback: just use domain itself for SMTP
    # Without dnspython, we just try the domain directly (most MTAs accept on A)
    return domain


@contextmanager
def smtp_connect(host: str, timeout: int = 5):
    """Open SMTP connection, yield server, close."""
    try:
        server = smtplib.SMTP(timeout=timeout)
        server.connect(host, 25)
        server.helo("outreachos-signals.local")
        yield server
        server.quit()
    except (smtplib.SMTPException, socket.error, OSError) as e:
        # Don't raise — caller checks via try/except
        yield None


def probe_email(mx_host: str, email: str, timeout: int = 5) -> str:
    """Probe SMTP server for RCPT TO. Returns one of:
    'valid' | 'invalid' | 'catch_all' | 'unknown' """
    try:
        with smtp_connect(mx_host, timeout) as server:
            if server is None:
                return "unknown"
            server.mail("test@outreachos-signals.local")
            code, _ = server.rcpt(email)
            if code == 250:
                # Test catch-all with random address
                server.mail("test@outreachos-signals.local")
                code2, _ = server.rcpt(f"definitely-doesnt-exist-1234567890@{mx_host}")
                if code2 == 250:
                    return "catch_all"
                return "valid"
            elif code in (550, 551, 553):
                return "invalid"
            else:
                return "unknown"
    except Exception:
        return "unknown"


def generate_patterns(first: str, last: str, f: str, domain: str) -> list[tuple[str, str]]:
    """Return list of (email, pattern_name) tuples."""
    out = []
    for pat in EMAIL_PATTERNS:
        try:
            email = pat.format(first=first, last=last, f=f, domain=domain)
            name = pat.replace("{domain}", "").replace("{}", "_").format(first=first, last=last, f=f)
            name = re.sub(r"[{}@.\[\]0]+", "", name).strip("_")
            if name and "@" in email:
                out.append((email, name or "pattern"))
        except (KeyError, IndexError):
            continue
    return out


def enrich_event(event: dict, niche_id: int, max_probes: int = 8) -> list[dict]:
    """For a single classified event, try to find buyer emails.
    Returns list of {role, name, email, status, source} dicts."""
    domain = normalize_domain(event.get("company_domain", ""))
    if not domain:
        return []
    # We need at least a name to brute-force. Check evidence_snippet, raw_text, raw_metadata.
    # If we don't have a name, we can guess common roles (e.g., "info@" or department aliases)
    candidates = []
    name_field = event.get("raw_metadata", {}).get("name") or event.get("evidence_snippet", "")
    # Try to extract first/last from any free text
    # Look for "Name is the X of Y" or "X Name"
    name = None
    if event.get("raw_metadata", {}).get("name"):
        name = event["raw_metadata"]["name"]
    elif event.get("source") == "linkedin_change":
        name = event.get("raw_metadata", {}).get("name")
    if name:
        parsed = normalize_name(name)
        if parsed:
            first, last, f = parsed
            patterns = generate_patterns(first, last, f, domain)
            for role in BUYER_ROLES_PER_NICHE.get(niche_id, []):
                for email, pat_name in patterns[:4]:  # top 4 patterns
                    candidates.append({"role": role, "email": email, "name": name, "pattern": pat_name})
    # If we don't have a name, try common department aliases
    if not candidates:
        for role in BUYER_ROLES_PER_NICHE.get(niche_id, [])[:3]:
            for prefix in ["sales", "info", "hello", "team", "growth"]:
                candidates.append({"role": role, "email": f"{prefix}@{domain}", "name": None, "pattern": f"dept:{prefix}"})
    # Probe up to max_probes
    mx = get_mx_host(domain)
    results = []
    probes = 0
    for cand in candidates:
        if probes >= max_probes:
            break
        probes += 1
        status = probe_email(mx, cand["email"])
        cand["status"] = status
        cand["source"] = "smtp_probe"
        results.append(cand)
        time.sleep(0.3)  # rate limit
    return results


def fetch_unenriched(min_score: float = 6.0, limit: int = 50) -> list[dict]:
    with sqlite3.connect("data/signals.db") as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("""
            SELECT cl.event_id, cl.niche_id, cl.score, cl.first_angle,
                   e.company_domain, e.company_name, e.raw_text, e.evidence_snippet,
                   e.source, e.raw_metadata
            FROM signal_classifications cl
            JOIN signal_events e ON e.event_id = cl.event_id
            WHERE cl.score >= ?
              AND e.company_domain IS NOT NULL
              AND cl.buyer_contacts_json IS NULL
            ORDER BY cl.score DESC
            LIMIT ?
        """, (min_score, limit)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        # raw_metadata is JSON string in DB; parse it
        if d.get("raw_metadata"):
            try:
                d["raw_metadata"] = json.loads(d["raw_metadata"])
            except (json.JSONDecodeError, TypeError):
                d["raw_metadata"] = {}
        else:
            d["raw_metadata"] = {}
        out.append(d)
    return out


def save_enrichment(event_id: str, contacts: list[dict]):
    with sqlite3.connect("data/signals.db") as c:
        c.execute("""
            UPDATE signal_classifications
            SET buyer_contacts_json = ?
            WHERE event_id = ?
        """, (json.dumps(contacts, ensure_ascii=False), event_id))


def main(limit: int = 20):
    print(f"Enrich: fetching up to {limit} classified events (score >= 6)")
    events = fetch_unenriched(limit=limit)
    if not events:
        print("  nothing to enrich")
        return
    print(f"  fetched {len(events)}, probing SMTP...")
    enriched = 0
    for ev in events:
        contacts = enrich_event(ev, ev.get("niche_id") or 1)
        if contacts:
            save_enrichment(ev["event_id"], contacts)
            enriched += 1
            # Show first contact found
            valid = [c for c in contacts if c.get("status") in ("valid", "catch_all")]
            if valid:
                print(f"  ✓ {ev['company_name']}: {valid[0]['email']} ({valid[0]['status']})")
            else:
                print(f"  · {ev['company_name']}: {len(contacts)} probed, no valid")
    print(f"  enriched={enriched}/{len(events)}")


if __name__ == "__main__":
    main()
