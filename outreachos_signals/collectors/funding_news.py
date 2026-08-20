"""Google News RSS collector for funding/M&A events.
Free, no API key. Parse via stdlib XML + regex."""
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from ..db import insert_event
from .base import http_get, load_niches


def _query_for_niche(niche: dict) -> list[str]:
    """Map niche to funding-related search queries."""
    name = niche["name"].lower()
    if "fintech" in name:
        return ["FinTech funding round Series", "FinTech Series B"]
    if "ai" in name or "data" in name:
        return ["AI startup Series funding", "machine learning startup Series"]
    if "saas" in name:
        return ["B2B SaaS Series funding", "SaaS startup Series A B C"]
    if "crm" in name:
        return ["CRM startup Series funding", "sales tech funding"]
    if "hrtech" in name or "hr" in name:
        return ["HRTech Series funding", "recruiting startup Series"]
    if "martech" in name:
        return ["MarTech Series funding", "marketing startup funding"]
    if "cloud" in name or "security" in name:
        return ["cloud security Series funding", "cybersecurity startup Series"]
    if "edtech" in name:
        return ["EdTech Series funding", "education startup Series"]
    if "marketplace" in name:
        return ["marketplace startup Series funding"]
    if "it services" in name:
        return ["IT services Series funding", "software development firm Series"]
    return [f"{niche['name']} startup funding"]


def _parse_domain_from_url(url: str) -> str:
    m = re.search(r"https?://(?:www\.)?([a-zA-Z0-9.-]+)", url)
    return m.group(1) if m else ""


def _parse_rss(xml_bytes: bytes) -> list[dict]:
    """Parse Google News RSS. Each <item> has title, link, pubDate, source."""
    items = []
    root = ET.fromstring(xml_bytes)
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        source_el = item.find("source")
        source_name = source_el.text if source_el is not None else ""
        items.append({"title": title, "link": link, "pubDate": pub, "source": source_name})
    return items


def _funding_signal(text: str) -> bool:
    """Heuristic: does this look like a funding/M&A event?"""
    t = text.lower()
    keywords = [
        "raises", "raised", "secures", "secured", "closes", "funding round",
        "series a", "series b", "series c", "series d",
        "acquires", "acquired by", "acquisition",
        "ipo", "going public",
        "investment of", "million in funding", "billion in funding",
    ]
    return any(k in t for k in keywords)


def _extract_amount(text: str) -> str | None:
    m = re.search(r"\$\s?(\d+(?:\.\d+)?)\s?(million|billion|M|B)", text, re.I)
    return m.group(0) if m else None


def _extract_company(text: str) -> str | None:
    """Naive: take first capitalized 1-3 word phrase before 'raises' or 'secures'."""
    m = re.search(r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})\s+(?:raises|secures|closes|acquires|has raised)", text)
    return m.group(1) if m else None


def collect(max_per_niche: int = 5) -> dict:
    stats = {"queries": 0, "items": 0, "inserted": 0, "skipped_dup": 0, "errors": 0}
    niches = load_niches()
    for niche in niches:
        for q in _query_for_niche(niche)[:1]:  # 1 query per niche to save time
            stats["queries"] += 1
            url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=en-US&gl=US&ceid=US:en"
            try:
                xml = http_get(url, headers={"User-Agent": "Mozilla/5.0"})
                items = _parse_rss(xml)
            except Exception as e:
                print(f"  [ERR] {q}: {e}")
                stats["errors"] += 1
                continue
            count = 0
            for it in items:
                if count >= max_per_niche:
                    break
                if not _funding_signal(it["title"]):
                    continue
                count += 1
                stats["items"] += 1
                # Pubdate parsing
                event_date = None
                try:
                    # RFC 822: "Tue, 19 Aug 2026 14:30:00 GMT"
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(it["pubDate"])
                    event_date = dt.date().isoformat()
                except Exception:
                    pass
                company = _extract_company(it["title"]) or "Unknown"
                domain = _parse_domain_from_url(it["link"]) or "news.google.com"
                amount = _extract_amount(it["title"])
                ev_id = insert_event(
                    source="funding_news",
                    company_domain=domain,
                    event_type="funding",
                    event_subtype="series" if "series" in it["title"].lower() else ("acquisition" if "acqui" in it["title"].lower() else "investment"),
                    raw_text=f"{company}: {it['title']} [{amount or 'amount n/a'}]",
                    source_event_id=f"gn:{hash(it['link'])}",
                    company_name=company,
                    event_date=event_date,
                    evidence_url=it["link"],
                    evidence_snippet=it["title"],
                    raw_metadata={"niche_id": niche["id"], "amount": amount, "source_news": it["source"], "query": q},
                )
                if ev_id:
                    stats["inserted"] += 1
                else:
                    stats["skipped_dup"] += 1
    return stats


def main():
    print("Google News RSS: 10 niches, funding events")
    s = collect()
    print(f"  queries={s['queries']} items={s['items']} inserted={s['inserted']} dup={s['skipped_dup']} err={s['errors']}")


if __name__ == "__main__":
    main()
