"""SQLite connection helper + event insertion."""
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> dict:
    env = {}
    p = ROOT / ".env"
    if not p.exists():
        return env
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip("\"'")
    return env


ENV = _load_env()


def db_path() -> Path:
    url = ENV.get("DATABASE_URL", "sqlite:///data/signals.db")
    if not url.startswith("sqlite:///"):
        raise RuntimeError("only sqlite:// URLs supported")
    p = Path(url[len("sqlite:///"):])
    if not p.is_absolute():
        p = (ROOT / p).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def conn():
    c = sqlite3.connect(db_path())
    c.execute("PRAGMA foreign_keys = ON")
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def insert_event(
    source: str,
    company_domain: str,
    event_type: str,
    raw_text: str,
    *,
    source_event_id: str | None = None,
    company_name: str | None = None,
    company_size: str | None = None,
    company_country: str | None = None,
    event_subtype: str | None = None,
    event_date: str | None = None,
    evidence_url: str | None = None,
    evidence_snippet: str | None = None,
    raw_metadata: dict[str, Any] | None = None,
) -> str | None:
    """Insert raw event. Returns event_id, or None on duplicate."""
    if os.environ.get("DRY_RUN") == "1" or ENV.get("DRY_RUN") == "1":
        print(f"[DRY] {source} {event_type} {company_domain}: {raw_text[:80]}")
        return None
    with conn() as c:
        try:
            event_id = new_id()
            c.execute(
                """
                INSERT INTO signal_events
                  (event_id, source, source_event_id, company_domain, company_name,
                   company_size, company_country, event_type, event_subtype, event_date,
                   raw_text, evidence_url, evidence_snippet, raw_metadata, collected_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, CURRENT_TIMESTAMP)
                """,
                (
                    event_id, source, source_event_id, company_domain, company_name,
                    company_size, company_country, event_type, event_subtype, event_date,
                    raw_text, evidence_url, evidence_snippet,
                    json.dumps(raw_metadata or {}, ensure_ascii=False),
                ),
            )
            return event_id
        except sqlite3.IntegrityError:
            return None


def count_events() -> int:
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM signal_events").fetchone()[0]
