"""Greenhouse Job Board API collector.
Public JSON API: https://boards-api.greenhouse.io/v1/boards/<company>/jobs
No auth, returns all current openings."""
import json
from ..db import insert_event
from .base import http_get_json, load_niches

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{company}/jobs"


def collect(companies: list[str], dry: bool = False) -> dict:
    """Collect jobs for a list of Greenhouse companies. Returns stats."""
    stats = {"checked": 0, "inserted": 0, "skipped_dup": 0, "errors": 0}
    niches = load_niches()
    niche_titles: dict[str, list[int]] = {}  # lowercase title -> list of niche_ids
    for n in niches:
        for t in n["ats_titles"]:
            niche_titles.setdefault(t.lower(), []).append(n["id"])

    for company in companies:
        stats["checked"] += 1
        try:
            data = http_get_json(GREENHOUSE_API.format(company=company))
        except Exception as e:
            print(f"  [ERR] {company}: {e}")
            stats["errors"] += 1
            continue

        for job in data.get("jobs", []):
            title = (job.get("title") or "").strip()
            if not title:
                continue
            url = job.get("absolute_url", "")
            domain = "greenhouse.io"  # source domain for dedup
            content = job.get("content", "")[:500]
            updated = job.get("updated_at", "")[:10]  # ISO date

            # Find matching niches (case-insensitive substring)
            title_l = title.lower()
            matched_niches: list[int] = []
            for needle, ids in niche_titles.items():
                if needle in title_l:
                    matched_niches.extend(ids)
            matched_niches = sorted(set(matched_niches))

            if not matched_niches:
                continue  # not relevant to our 10 niches

            for niche_id in matched_niches:
                ev_id = insert_event(
                    source="greenhouse",
                    company_domain=domain,  # use greenhouse as dedup key
                    event_type="hiring",
                    event_subtype="open_vacancy",
                    raw_text=f"{company}: {title}",
                    source_event_id=f"gh:{company}:{job.get('id', url)}",
                    company_name=company,
                    company_country="US",  # most B2B SaaS; refine later
                    event_date=updated,
                    evidence_url=url,
                    evidence_snippet=content,
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
    companies = cfg.get("ats_greenhouse_companies", [])
    print(f"Greenhouse: {len(companies)} companies")
    s = collect(companies)
    print(f"  checked={s['checked']} inserted={s['inserted']} dup={s['skipped_dup']} err={s['errors']}")


if __name__ == "__main__":
    main()
