#!/usr/bin/env python3
"""Apply schema/*.sql to local SQLite DB.
Run from repo root: python3 scripts/migrate.py
Zero external deps (stdlib only).
"""
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"


def load_env(path: Path) -> None:
    """Tiny .env loader — KEY=value lines, # comments, no expansion."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


load_env(ENV_FILE)

db_url = os.environ.get("DATABASE_URL", "sqlite:///data/signals.db")
if not db_url.startswith("sqlite:///"):
    print(f"ERROR: only sqlite:// URLs supported, got: {db_url}", file=sys.stderr)
    sys.exit(1)
db_path = Path(db_url[len("sqlite:///"):])
if not db_path.is_absolute():
    db_path = (ROOT / db_path).resolve()
db_path.parent.mkdir(parents=True, exist_ok=True)

print(f"DB: {db_path}")
conn = sqlite3.connect(db_path)
conn.execute("PRAGMA foreign_keys = ON")
conn.execute("PRAGMA journal_mode = WAL")
conn.execute("PRAGMA synchronous = NORMAL")

for f in sorted((ROOT / "schema").glob("*.sql")):
    print(f">>> {f.name}")
    sql = f.read_text()
    # heredoc-escaped datetime(''now'') → SQLite native
    sql = sql.replace("datetime(''now'')", "CURRENT_TIMESTAMP")
    conn.executescript(sql)

conn.commit()
tables = [r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
indexes = [r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()]
print(f"OK. tables ({len(tables)}): {tables}")
print(f"    indexes ({len(indexes)}): {indexes}")
conn.close()
