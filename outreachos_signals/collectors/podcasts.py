"""Podcast guest appearances collector.
Scrapes podcast episode lists via RSS (free) for the show notes.
Detects 'X is the founder/CEO of Y' → trigger event.
Targets: SaaStr, Indie Hackers, My First Million, Sales Gravy, SaaSBoomi."""
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from ..db import insert_event

# Top B2B/SaaS podcasts (RSS feeds — free)
PODCASTS = [
    ("SaaStr", "https://feeds.simplecast.com/3d_yellow_podcasts"),
    ("IndieHackers", "https://feeds.simplecast.com/dHoohVNH"),
    ("MyFirstMillion", "https://feeds.megaphone.fm/mfm"),
    ("SalesGravy", "https://salesgravy.libsyn.com/rss"),
    ("SaaSBoomi", "https://feeds.transistor.fm/saas-boomi-podcast"),
]


def _parse_rss(xml_bytes: bytes) -> list[dict]:
    items = []
    root = ET.fromstring(xml_bytes)
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        items.append({"title": title, "link": link, "desc": desc, "pubDate": pub})
    return items


def _extract_guest(text: str) -> tuple[str, str, str] | None:
    """Try to extract (guest_name, role, company) from episode title.
    Patterns: 'X, founder of Y' / 'X from Y' / 'X of Y'."""
    # Common patterns
    patterns = [
        r"^(?:with\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}),?\s+(?:CEO|founder|co-founder|cofounder|head of|VP)\s+(?:of|at)\s+([A-Z][\w& ]{1,40})",
        r"^(?:with\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}),?\s+(?:founder|co-founder|cofounder)\s+of\s+([A-Z][\w& ]{1,40})",
        r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s*\(([^)]+)\)",  # "Name (Company)"
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            name = m.group(1).strip()
            rest = m.group(2).strip() if len(m.groups()) > 1 else ""
            # Try to split "CEO of Company" → role=CEO, company=Company
            role_m = re.match(r"(CEO|founder|co-founder|cofounder|head of|VP)\s+of\s+(.+)", rest, re.I)
            if role_m:
                return (name, role_m.group(1), role_m.group(2).strip())
            return (name, "founder", rest)
    return None


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "outreachos-signals/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def collect(max_episodes: int = 10) -> dict:
    stats = {"podcasts": 0, "episodes": 0, "inserted": 0, "skipped_dup": 0, "errors": 0}
    for name, feed_url in PODCASTS:
        stats["podcasts"] += 1
        try:
            xml = _http_get(feed_url)
            items = _parse_rss(xml)
        except Exception as e:
            print(f"  [ERR] {name}: {e}")
            stats["errors"] += 1
            continue
        count = 0
        for ep in items:
            if count >= max_episodes:
                break
            count += 1
            stats["episodes"] += 1
            guest = _extract_guest(ep["title"])
            if not guest:
                continue
            name_g, role, company = guest
            if not company or len(company) < 2:
                continue
            # Build pseudo-domain
            domain = re.sub(r"[^a-z0-9]+", "", company.lower()) + ".com"
            ev_id = insert_event(
                source="podcast",
                company_domain=domain,
                event_type="trigger",
                event_subtype="podcast_appearance",
                raw_text=f"{name_g} ({role} of {company}) on {name} podcast",
                source_event_id=f"pod:{name}:{hash(ep['link'])}",
                company_name=company,
                evidence_url=ep["link"],
                evidence_snippet=ep["title"],
                raw_metadata={"podcast": name, "guest": name_g, "role": role},
            )
            if ev_id:
                stats["inserted"] += 1
            else:
                stats["skipped_dup"] += 1
        time.sleep(1)
    return stats


def main():
    print(f"Podcasts: {len(PODCASTS)} feeds, last 10 episodes each")
    s = collect()
    print(f"  podcasts={s['podcasts']} episodes={s['episodes']} inserted={s['inserted']} dup={s['skipped_dup']} err={s['errors']}")


if __name__ == "__main__":
    main()
