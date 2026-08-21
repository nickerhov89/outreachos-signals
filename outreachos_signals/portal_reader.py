"""Portal reader — read-only access to Polza Portal PostgreSQL.

Connects to: 139.60.162.12:35434, db=postgres, user=nick_ro, password=...
CRITICAL: sslmode=disable (SSL handshake fails auth on this server)

Tables used:
  - companies (7384 rows): name, site, email, phone, employees_range, region
  - company_contacts (4286 rows): full_name, title, role_guess, channel_email, channel_phone, channel_tg_username
  - pdl_companies (19.5M): name, website, industry, size, country, region
  - funded_companies (44k): name, website, total_funding_usd, last_funding_date, investors
  - ats_companies (22 rows): company, domain, ats, slug, job_count, job_titles
  - he_vocab (15 rows): company_types, job_titles, search_queries per vertical

Used in /wizard_discover AFTER LLM gen — for each candidate company:
  - Check if already in Portal `companies` → known LPRs available
  - Cross-check PDL for industry/size/geo enrichment
  - Check `funded_companies` for funding signal
  - Check `ats_companies` for hiring signal (Portal's own ATS cache)
"""
import os
import re
import psycopg2
from typing import List, Dict, Any, Optional
from contextlib import contextmanager


# Connection constants — must match Polza Portal
DB_HOST = "139.60.162.12"
DB_PORT = 35434
DB_NAME = "postgres"
DB_USER = "nick_ro"
DB_PASS = "nick_ro_9Kx4Mp7Qv2Lw"
DB_SSL = "disable"  # CRITICAL

CONN_STR = (
    f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} "
    f"user={DB_USER} password={DB_PASS} sslmode={DB_SSL} connect_timeout=5"
)


@contextmanager
def _portal_conn(timeout_ms: int = 3000):
    conn = psycopg2.connect(CONN_STR)
    try:
        # Cap each query at 3s by default (PDL has 19.5M rows, no index on website)
        with conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {timeout_ms}")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _normalize_domain(domain: str) -> str:
    d = (domain or "").lower().strip()
    d = re.sub(r"^https?://", "", d)
    d = d.split("/")[0]
    if d.startswith("www."):
        d = d[4:]
    return d


# ============================================================
# Companies + contacts (Portal's existing customer base)
# ============================================================

def lookup_company(domain: str) -> Dict[str, Any]:
    """Find company by domain in Portal.companies.
    Returns: {found, company_id, name, site, email, phone, employees_range, source, contacts: [{name, title, role, email, phone, tg}]}
    """
    domain = _normalize_domain(domain)
    if not domain:
        return {"found": False, "contacts": []}
    with _portal_conn() as conn:
        cur = conn.cursor()
        # Match domain by suffix (e.g. acme.com matches site='acme.com' or 'www.acme.com')
        try:
            cur.execute(
                """SELECT id, name, short_name, brand_name, site, email, phone, region, city,
                          employees_range, source, source_confidence
                   FROM companies
                   WHERE site = %s OR site LIKE %s OR site LIKE %s
                   LIMIT 5""",
                (domain, f"%.{domain}", f"www.{domain}%"),
            )
        except Exception:
            return {"found": False, "domain": domain, "contacts": []}
        rows = cur.fetchall()
        if not rows:
            return {"found": False, "domain": domain, "contacts": []}
        # Take first
        (cid, name, short, brand, site, email, phone, region, city,
         emp, source, conf) = rows[0]
        # Find contacts
        cur.execute(
            """SELECT full_name, first_name, last_name, title, role_guess,
                      channel_email, channel_phone, channel_tg_username, score, confidence
               FROM company_contacts
               WHERE company_id = %s
               ORDER BY score DESC NULLS LAST
               LIMIT 20""",
            (cid,),
        )
        contacts = []
        for r in cur.fetchall():
            fn, fn1, ln, title, role, em, ph, tg, sc, conf = r
            if not any([em, ph, tg]):
                continue  # no channels yet
            contacts.append({
                "full_name": fn or f"{fn1 or ''} {ln or ''}".strip(),
                "title": title or role or "",
                "email": em or "",
                "phone": ph or "",
                "tg": tg or "",
                "score": sc or 0,
            })
        return {
            "found": True,
            "company_id": str(cid),
            "name": name or short or brand or domain,
            "site": site or "",
            "email": email or "",
            "phone": phone or "",
            "region": region or city or "",
            "employees_range": emp or "",
            "source": source or "",
            "contacts": contacts,
            "contact_count": len(contacts),
        }


# ============================================================
# PDL companies (19.5M catalog) — for ICP fit
# ============================================================

def pdl_lookup_company(domain: str) -> Dict[str, Any]:
    """Look up company in pdl_companies (19.5M catalog) by website domain.
    Fast: try exact match, then suffix match. 3s timeout.
    """
    domain = _normalize_domain(domain)
    if not domain:
        return {"found": False}
    with _portal_conn(timeout_ms=2000) as conn:
        cur = conn.cursor()
        # 1) Exact host match (uses index if exists, or quick scan)
        try:
            cur.execute(
                """SELECT name, website, industry, size, country, region, locality, founded, linkedin_url
                   FROM pdl_companies
                   WHERE website = %s OR website LIKE %s
                   LIMIT 1""",
                (domain, f"%.{domain}"),
            )
            row = cur.fetchone()
        except Exception:
            row = None
        if not row:
            return {"found": False, "domain": domain}
        nm, web, ind, sz, ctry, rgn, loc, found, li = row
        return {
            "found": True,
            "name": nm or "",
            "website": web or "",
            "industry": ind or "",
            "size": sz or "",
            "country": ctry or "",
            "region": rgn or "",
            "locality": loc or "",
            "founded": found,
            "linkedin_url": li or "",
        }


# ============================================================
# Funded companies — for funding signal
# ============================================================

def funded_lookup(domain: str) -> Dict[str, Any]:
    """Look up company in funded_companies for funding events."""
    domain = _normalize_domain(domain)
    if not domain:
        return {"found": False}
    with _portal_conn() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """SELECT name, total_funding_usd, last_funding_usd, last_funding_type,
                          last_funding_date, num_funding_rounds, investors, country, industry, team_size
                   FROM funded_companies
                   WHERE website = %s OR website LIKE %s
                   ORDER BY last_funding_date DESC NULLS LAST
                   LIMIT 1""",
                (domain, f"%.{domain}"),
            )
        except Exception:
            return {"found": False, "domain": domain}
        row = cur.fetchone()
        if not row:
            return {"found": False, "domain": domain}
        (nm, tot, last, typ, date, rounds, inv, ctry, ind, team) = row
        return {
            "found": True,
            "name": nm or "",
            "total_funding_usd": tot or 0,
            "last_funding_usd": last or 0,
            "last_funding_type": typ or "",
            "last_funding_date": str(date) if date else "",
            "num_rounds": rounds or 0,
            "investors": (inv or "")[:200],
            "country": ctry or "",
            "industry": ind or "",
            "team_size": team or 0,
        }


# ============================================================
# ATS companies (Portal's own ATS scrape cache)
# ============================================================

def ats_lookup(domain: str) -> Dict[str, Any]:
    """Look up company in ats_companies (Portal's own ATS cache)."""
    domain = _normalize_domain(domain)
    if not domain:
        return {"found": False}
    with _portal_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT company, domain, ats, slug, job_count, job_titles, country, latest_posted_at
               FROM ats_companies
               WHERE LOWER(domain) = %s
               LIMIT 1""",
            (domain,),
        )
        row = cur.fetchone()
        if not row:
            return {"found": False}
        nm, dom, ats, slug, cnt, titles, ctry, latest = row
        return {
            "found": True,
            "company": nm or "",
            "ats": ats or "",
            "slug": slug or "",
            "job_count": cnt or 0,
            "job_titles": list(titles or [])[:10],
            "country": ctry or "",
            "latest_posted_at": str(latest) if latest else "",
        }


# ============================================================
# He vocab — get buyer titles for vertical (for LPR matching)
# ============================================================

def vocab_lookup(vertical_keyword: str) -> Dict[str, Any]:
    """Find he_vocab row by vertical keyword in company_types/job_titles.
    Returns buyer titles for LPR scoring.
    """
    kw = (vertical_keyword or "").lower().strip()[:50]
    if not kw:
        return {"found": False}
    with _portal_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, vertical_id, company_types, job_titles, search_queries
               FROM he_vocab
               WHERE company_types::text ILIKE %s OR job_titles::text ILIKE %s
               LIMIT 3""",
            (f"%{kw}%", f"%{kw}%"),
        )
        rows = cur.fetchall()
        if not rows:
            return {"found": False}
        results = []
        for r in rows:
            vid, v_vid, ctypes, jtitles, queries = r
            results.append({
                "vocab_id": str(vid),
                "vertical_id": str(v_vid),
                "buyer_titles": (jtitles.get("buyer") if isinstance(jtitles, dict) else [])[:10],
            })
        return {"found": True, "matches": results}


# ============================================================
# AGGREGATE — full picture per domain (replaces 4 separate calls)
# ============================================================

def portal_enrich(domain: str) -> Dict[str, Any]:
    """Run all Portal lookups for one domain. Single connection, 4 queries.
    Speed: ~1-2s per domain (vs 5s with 4 separate connects).
    """
    domain = _normalize_domain(domain)
    out = {
        "domain": domain,
        "in_portal": {"found": False, "contacts": []},
        "pdl": {"found": False},
        "funded": {"found": False},
        "ats": {"found": False},
    }
    if not domain:
        return out
    try:
        with psycopg2.connect(CONN_STR, connect_timeout=5) as conn:
            cur = conn.cursor()
            cur.execute("SET statement_timeout = '3000'")
            # 1) companies + contacts
            try:
                cur.execute(
                    """SELECT id, name, short_name, site, email, phone, region, city, employees_range, source
                       FROM companies
                       WHERE site = %s OR site LIKE %s OR site LIKE %s
                       LIMIT 5""",
                    (domain, f"%.{domain}", f"www.{domain}%"),
                )
                rows = cur.fetchall()
                if rows:
                    cid, name, short, site, email, phone, region, city, emp, source = rows[0]
                    cur2 = conn.cursor()
                    cur2.execute(
                        """SELECT full_name, first_name, last_name, title, role_guess,
                                  channel_email, channel_phone, channel_tg_username, score
                           FROM company_contacts
                           WHERE company_id = %s AND (channel_email IS NOT NULL OR channel_phone IS NOT NULL OR channel_tg_username IS NOT NULL)
                           ORDER BY score DESC NULLS LAST LIMIT 20""",
                        (cid,),
                    )
                    contacts = []
                    for r in cur2.fetchall():
                        fn, fn1, ln, title, role, em, ph, tg, sc = r
                        contacts.append({
                            "full_name": fn or f"{fn1 or ''} {ln or ''}".strip(),
                            "title": title or role or "",
                            "email": em or "", "phone": ph or "", "tg": tg or "",
                            "score": sc or 0,
                        })
                    out["in_portal"] = {
                        "found": True, "company_id": str(cid),
                        "name": name or short or domain, "site": site or "",
                        "email": email or "", "phone": phone or "",
                        "region": region or city or "", "employees_range": emp or "",
                        "source": source or "", "contacts": contacts,
                        "contact_count": len(contacts),
                    }
            except Exception:
                pass
            # 2) PDL
            try:
                cur.execute(
                    """SELECT name, website, industry, size, country, region, locality
                       FROM pdl_companies
                       WHERE website = %s OR website LIKE %s
                       LIMIT 1""",
                    (domain, f"%.{domain}"),
                )
                row = cur.fetchone()
                if row:
                    nm, web, ind, sz, ctry, rgn, loc = row
                    out["pdl"] = {"found": True, "name": nm or "", "website": web or "",
                                  "industry": ind or "", "size": sz or "", "country": ctry or "",
                                  "region": rgn or "", "locality": loc or ""}
            except Exception:
                pass
            # 3) Funded
            try:
                cur.execute(
                    """SELECT name, total_funding_usd, last_funding_usd, last_funding_type,
                              last_funding_date, num_funding_rounds, investors, country, industry, team_size
                       FROM funded_companies
                       WHERE website = %s OR website LIKE %s
                       ORDER BY last_funding_date DESC NULLS LAST LIMIT 1""",
                    (domain, f"%.{domain}"),
                )
                row = cur.fetchone()
                if row:
                    nm, tot, last, typ, date, rounds, inv, ctry, ind, team = row
                    out["funded"] = {"found": True, "name": nm or "",
                                     "total_funding_usd": tot or 0, "last_funding_usd": last or 0,
                                     "last_funding_type": typ or "",
                                     "last_funding_date": str(date) if date else "",
                                     "num_rounds": rounds or 0,
                                     "investors": (inv or "")[:200],
                                     "country": ctry or "", "industry": ind or "",
                                     "team_size": team or 0}
            except Exception:
                pass
            # 4) ATS
            try:
                cur.execute(
                    """SELECT company, domain, ats, slug, job_count, job_titles, country, latest_posted_at
                       FROM ats_companies
                       WHERE LOWER(domain) = %s LIMIT 1""",
                    (domain,),
                )
                row = cur.fetchone()
                if row:
                    nm, dom, ats, slug, cnt, titles, ctry, latest = row
                    out["ats"] = {"found": True, "company": nm or "", "ats": ats or "",
                                  "slug": slug or "", "job_count": cnt or 0,
                                  "job_titles": list(titles or [])[:10], "country": ctry or "",
                                  "latest_posted_at": str(latest) if latest else ""}
            except Exception:
                pass
    except Exception as e:
        out["error"] = str(e)[:80]
    return out


def boost_reason_from_portal(portal: Dict[str, Any], base_reason: str) -> str:
    """Add Portal-sourced evidence to target reason."""
    parts = [base_reason]
    if portal["in_portal"].get("found"):
        c = portal["in_portal"]
        n_lpr = c.get("contact_count", 0)
        if n_lpr > 0:
            top = c.get("contacts", [{}])[0]
            top_name = top.get("full_name", "?")
            top_title = top.get("title", "?")
            parts.append(f"in Portal: {n_lpr} known LPR (top: {top_name}, {top_title})")
        else:
            parts.append(f"in Portal DB (source={c.get('source', '?')})")
    if portal["funded"].get("found"):
        f = portal["funded"]
        date = f.get("last_funding_date", "")
        typ = f.get("last_funding_type", "")
        amt = f.get("last_funding_usd", 0)
        if amt > 0:
            parts.append(f"FUNDED: {typ} ${amt/1_000_000:.1f}M {date}")
    if portal["ats"].get("found"):
        a = portal["ats"]
        n = a.get("job_count", 0)
        if n > 0:
            parts.append(f"ATS: {n} jobs on {a.get('ats', '?')}")
    if portal["pdl"].get("found"):
        p = portal["pdl"]
        sz = p.get("size", "")
        if sz:
            parts.append(f"PDL: {sz} emp, {p.get('industry', '')[:30]}")
    return " — ".join(parts)


# CLI test
if __name__ == "__main__":
    import sys
    domains = sys.argv[1:] or ["vercel.com", "lemlist.com", "gong.io", "stripe.com"]
    for d in domains:
        print(f"\n=== {d} ===")
        out = portal_enrich(d)
        # Compact view
        ip = out["in_portal"]
        if ip.get("found"):
            print(f"  companies: {ip['name']} (contacts: {ip['contact_count']})")
        else:
            print(f"  companies: NOT in Portal DB")
        p = out["pdl"]
        if p.get("found"):
            print(f"  PDL: {p['industry'][:30]}, {p['size']}, {p['country']}")
        f = out["funded"]
        if f.get("found"):
            print(f"  funded: {f['last_funding_type']} ${f['last_funding_usd']/1_000_000:.1f}M {f['last_funding_date']}")
        a = out["ats"]
        if a.get("found"):
            print(f"  ATS: {a['job_count']} jobs on {a['ats']}")
