"""Play Generator: turn classified events + enriched contacts into actionable plays.

For each classified event with high score:
- Create a signal_play (the recommended action)
- Save the enriched buyer contacts to signal_play_accounts
- Generate a draft outreach message based on the angle
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("data/signals.db")

PLAY_TEMPLATES = {
    "greenhouse": "Saw {company} is hiring {role} — sounds like scaling GTM. We help teams in {niche} cut ramp time with signal-based outbound. Worth a 15-min call?",
    "lever": "{company} is hiring {role} — looks like a push into {niche}. We do signal-based outbound for similar teams. Open to a quick chat?",
    "funding_news": "Congrats on the raise, {company}. Now's the time to fix the #1 thing that kills outbound ROI: targeting. We do signal-based lists for {niche} — 15 min?",
    "github_commits": "Saw {company} just shipped new code — looks like serious momentum. We help {niche} teams turn signals into qualified leads. Worth 15 min?",
    "hackernews": "Caught {company}'s HN post. We help {niche} teams ride this kind of attention into qualified pipeline. Quick chat?",
    "default": "Saw {company} is active in {niche}. We turn signals like this into qualified leads. 15 min?",
}

NICHE_NAMES = {
    1: "CRM/BPM", 2: "HRTech", 3: "MarTech", 4: "AI/Data", 5: "B2B SaaS",
    6: "IT Services", 7: "Cloud/Security", 8: "FinTech", 9: "EdTech", 10: "Marketplace",
}


def main(min_score: float = 0.5, limit: int = 100):
    print(f"Play Generator: events with score >= {min_score}, limit {limit}")
    with sqlite3.connect(str(DB_PATH)) as db:
        rows = db.execute("""
            select cl.event_id, cl.niche_id, cl.score, cl.first_angle, cl.buyer_contacts_json,
                   e.company_name, e.company_domain, e.source, e.raw_text, e.event_type
            from signal_classifications cl
            join signal_events e on e.event_id = cl.event_id
            where cl.score >= ?
            order by cl.score desc
            limit ?
        """, (min_score, limit)).fetchall()

    if not rows:
        print("  nothing to generate")
        return
    print(f"  processing {len(rows)} events...")

    generated = 0
    for r in rows:
        (event_id, niche_id, score, first_angle, contacts_json,
         company_name, company_domain, source, raw_text, event_type) = r

        play_id = f"play_{event_id[:12]}"

        # build outreach message
        template = PLAY_TEMPLATES.get(source, PLAY_TEMPLATES["default"])
        context = first_angle or (raw_text[:80] if raw_text else "recent activity")
        msg = template.format(
            company=company_name or "your team",
            role=(raw_text or "")[:60] if source in ("greenhouse", "lever") else "",
            context=context[:80] if context else "recent activity",
            niche=NICHE_NAMES.get(niche_id, "B2B"),
        )
        msg = msg[:500]

        # extract accounts from contacts
        accounts = []
        if contacts_json:
            try:
                contacts = json.loads(contacts_json)
                for c in contacts:
                    if c.get("status") in ("valid", "catch_all"):
                        accounts.append({
                            "email": c.get("email"),
                            "role": c.get("role"),
                            "name": c.get("name"),
                            "status": c.get("status"),
                        })
            except Exception:
                pass

        avg_score = sum(a.get("score", 0) for a in accounts) / max(len(accounts), 1) if accounts else 0.0

        with sqlite3.connect(str(DB_PATH)) as db:
            db.execute("""
                insert or replace into signal_plays
                (play_id, niche_id, play_name, trigger_logic, valid_from, valid_until,
                 accounts_count, accounts_avg_score, accounts_json, generated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                play_id, niche_id,
                f"{source} → {company_name or 'Unknown'}",
                f"score={score:.2f} {first_angle or ''}",
                datetime.now(timezone.utc).isoformat(),
                None,
                len(accounts),
                avg_score,
                json.dumps({"message": msg, "accounts": accounts}, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
            ))
            # add to signal_play_accounts (linked by company_domain)
            for a in accounts:
                db.execute("""
                    insert or replace into signal_play_accounts
                    (play_id, company_domain, event_id, score, first_angle, case_match)
                    values (?, ?, ?, ?, ?, ?)
                """, (
                    play_id, company_domain or "", event_id, score,
                    f"{a.get('role', '')}: {a.get('email', '')}",
                    a.get("status", ""),
                ))
        generated += 1

    with sqlite3.connect(str(DB_PATH)) as db:
        total_plays = db.execute("select count(*) from signal_plays").fetchone()[0]
        total_accounts = db.execute("select count(*) from signal_play_accounts").fetchone()[0]
    print(f"  generated: {generated}")
    print(f"  total plays: {total_plays}, accounts: {total_accounts}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--min-score", type=float, default=0.5)
    p.add_argument("--limit", type=int, default=100)
    args = p.parse_args()
    main(args.min_score, args.limit)
