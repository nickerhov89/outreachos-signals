"""Lever Postings API collector.
Public JSON API: https://api.lever.co/v0/postings/<company>?mode=json
No auth, returns all current openings."""
from ..db import insert_event
from .base import http_get_json, load_niches

LEVER_API = "https://api.lever.co/v0/postings/{company}?mode=json"


def collect(companies: list[str]) -> dict:
    stats = {"checked": 0, "inserted": 0, "skipped_dup": 0, "errors": 0}
    niches = load_niches()
    niche_titles: dict[str, list[int]] = {}
    for n in niches:
        for t in n["ats_titles"]:
            niche_titles.setdefault(t.lower(), []).append(n["id"])

    for company in companies:
        stats["checked"] += 1
        try:
            data = http_get_json(LEVER_API.format(company=company))
        except Exception as e:
            print(f"  [ERR] {company}: {e}")
            stats["errors"] += 1
            continue

        for job in data if isinstance(data, list) else []:
            title = (job.get("text") or "").strip()
            if not title:
                continue
            url = job.get("hostedUrl", "")
            domain = "lever.co"
            updated = (job.get("createdAt") or 0) // 1000  # ms → s
            from datetime import datetime, timezone
            event_date = datetime.fromtimestamp(updated, tz=timezone.utc).date().isoformat() if updated else None

            title_l = title.lower()
            matched_niches = sorted({nid for needle, ids in niche_titles.items() if needle in title_l for nid in ids})
            if not matched_niches:
                continue

            for niche_id in matched_niches:
                ev_id = insert_event(
                    source="lever",
                    company_domain=domain,
                    event_type="hiring",
                    event_subtype="open_vacancy",
                    raw_text=f"{company}: {title}",
                    source_event_id=f"lever:{company}:{job.get('id', url)}",
                    company_name=company,
                    company_country="US",
                    event_date=event_date,
                    evidence_url=url,
                    evidence_snippet=(job.get("description") or "")[:500],
                    raw_metadata={"company": company, "niche_id": niche_id, "title": title, "job_id": job.get("id")},
                )
                if ev_id:
                    stats["inserted"] += 1
                else:
                    stats["skipped_dup"] += 1
    return stats


def main():
    import yaml
    from pathlib import Path
    cfg = yaml.safe_load(open(Path(__file__).resolve().parent.parent.parent / "config" / "niches.yaml"))
    companies = cfg.get("ats_lever_companies", [])
    print(f"Lever: {len(companies)} companies")
    s = collect(companies)
    print(f"  checked={s['checked']} inserted={s['inserted']} dup={s['skipped_dup']} err={s['errors']}")


if __name__ == "__main__":
    main()
