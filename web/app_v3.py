"""OutreachOS Signals — FastAPI web app v3.
Public-facing: landing → input URL → 5 leads.
Admin: /dashboard, /leads, /niche/{id}, /signal/{id}.
Run: uvicorn web.app_v3:app --host 0.0.0.0 --port 8000 --workers 1"""
from __future__ import annotations

import io
import json
import re
import sqlite3
import yaml
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "signals.db"
TEMPLATES_DIR = ROOT / "web" / "templates"
NICHES_PATH = ROOT / "config" / "niches.yaml"
STATIC_DIR = ROOT / "web" / "static"

app = FastAPI(
    title="OutreachOS Signals",
    description="Signal-as-a-Service for B2B outbound. 10 niches, real-time.",
    version="0.3.0",
)

def _age_filter(iso):
    if not iso: return "—"
    try:
        from datetime import datetime, timezone
        if "T" in iso:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(iso, "%Y-%m-%d %H:%M:%S" if " " in iso else "%Y-%m-%d")
        delta = datetime.now(timezone.utc) - (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt)
        d = delta.days
        if d == 0: return "today"
        if d == 1: return "1d"
        if d < 30: return f"{d}d"
        return f"{d // 30}mo"
    except Exception: return "—"

env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    enable_async=False,
)
env.filters["age"] = _age_filter
env.filters["fmt_age"] = _age_filter

# Load niches config once
NICHES_CFG = yaml.safe_load(open(NICHES_PATH)) if NICHES_PATH.exists() else {"niches": []}
NICHES = {n["id"]: n for n in NICHES_CFG.get("niches", [])}


# ============================================================
# DB helpers
# ============================================================
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _fmt_age(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        if "T" in iso:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(iso, "%Y-%m-%d")
        delta = datetime.now(timezone.utc) - dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else datetime.now(timezone.utc) - dt
        days = delta.days
        if days == 0:
            return "today"
        if days == 1:
            return "1d"
        if days < 30:
            return f"{days}d"
        return f"{days // 30}mo"
    except Exception:
        return "—"


def _age_days(iso: str | None) -> int:
    if not iso:
        return 999
    try:
        if "T" in iso:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(iso, "%Y-%m-%d")
        delta = datetime.now(timezone.utc) - (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt)
        return max(0, delta.days)
    except Exception:
        return 999


# ============================================================
# Niche detection
# ============================================================
def _normalize_url(url: str) -> tuple[str, str]:
    """Return (domain, full_url_with_scheme)."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    domain = (parsed.netloc or "").lower().replace("www.", "")
    return domain, url


def _fetch_meta(url: str, timeout: float = 4.0) -> dict:
    """Fetch HTML and extract title + meta description. Graceful fallback."""
    try:
        r = requests.get(url, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }, allow_redirects=True)
        html = r.text[:50000]  # cap
    except Exception:
        return {"title": "", "description": "", "error": "fetch_failed"}
    title = ""
    desc = ""
    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    if m:
        title = m.group(1).strip()
    m = re.search(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']', html, re.I)
    if not m:
        m = re.search(r'<meta\s+content=["\']([^"\']+)["\']\s+name=["\']description["\']', html, re.I)
    if m:
        desc = m.group(1).strip()
    # also og:description
    if not desc:
        m = re.search(r'<meta\s+property=["\']og:description["\']\s+content=["\']([^"\']+)["\']', html, re.I)
        if m:
            desc = m.group(1).strip()
    return {"title": title, "description": desc}


def detect_niche(url: str) -> tuple[int | None, str | None, float, dict]:
    """Return (niche_id, niche_name, confidence 0-1, debug_info)."""
    domain, full_url = _normalize_url(url)
    if not domain:
        return None, None, 0.0, {"error": "no_domain"}

    # fetch HTML for title + desc
    meta = _fetch_meta(full_url)
    text = f"{domain} {meta.get('title','')} {meta.get('description','')}".lower()

    # score each niche
    best = (None, None, 0.0)
    scores = []
    for nid, niche in NICHES.items():
        # domain override: exact match wins
        overrides = set(d.lower() for d in niche.get("domain_overrides", []))
        if domain in overrides:
            return nid, niche["name"], 1.0, {"domain": domain, "override": True}

        # collect all keywords (DO NOT include niche name tokens — too noisy)
        kw = set()
        kw |= set(k.lower() for k in niche.get("keywords", []))
        kw |= set(k.lower() for k in niche.get("ats_titles", []))
        kw |= set(k.lower() for k in niche.get("threads_keywords", []))
        kw |= set(k.lower() for k in niche.get("linkedin_queries", []))

        if not kw:
            continue
        # count hits, weight longer matches more
        hits = 0
        for k in kw:
            if k in text:
                hits += 1 + (len(k) > 8)  # bonus for long specific keywords
        if hits == 0:
            continue
        score = min(1.0, hits / 3.0)  # 3 hits = 100% confidence
        scores.append((nid, niche["name"], score, hits))
        if score > best[2]:
            best = (nid, niche["name"], score)

    debug = {"domain": domain, "title": meta.get("title", ""), "desc": meta.get("description", "")[:200], "scores": scores[:3]}
    if best[0] is not None:
        return best[0], best[1], best[2], debug
    return None, None, 0.0, debug


def fetch_leads_for_niche(niche_id: int | None, limit: int = 5) -> list[dict]:
    """Get top-scored classified events for the niche."""
    with db() as conn:
        if niche_id is None:
            rows = conn.execute("""
                SELECT e.event_id as event_id, e.source, e.event_type, e.company_name,
                       e.company_domain, e.raw_text, e.collected_at, e.evidence_url,
                       c.niche_id, c.score, n.name as niche_name
                FROM signal_events e
                LEFT JOIN signal_classifications c ON c.event_id = e.event_id
                LEFT JOIN niches n ON n.id = c.niche_id
                WHERE c.score IS NOT NULL
                ORDER BY c.score DESC, e.collected_at DESC
                LIMIT ?
            """, (limit,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT e.event_id as event_id, e.source, e.event_type, e.company_name,
                       e.company_domain, e.raw_text, e.collected_at, e.evidence_url,
                       c.niche_id, c.score, n.name as niche_name
                FROM signal_events e
                LEFT JOIN signal_classifications c ON c.event_id = e.event_id
                LEFT JOIN niches n ON n.id = c.niche_id
                WHERE c.niche_id = ? AND c.score IS NOT NULL
                ORDER BY c.score DESC, e.collected_at DESC
                LIMIT ?
            """, (niche_id, limit)).fetchall()

    leads = []
    for r in rows:
        d = dict(r)
        d["age_days"] = _age_days(d.get("collected_at"))
        d["age_label"] = _fmt_age(d.get("collected_at"))
        d["text"] = (d.get("raw_text") or "")[:280]
        d["score"] = float(d.get("score") or 0.0)
        leads.append(d)
    return leads


# ============================================================
# Static (manual — we serve from /static via FastAPI)
# ============================================================
from fastapi.staticfiles import StaticFiles
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ============================================================
# Routes
# ============================================================
@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    tpl = env.get_template("landing.html")
    return tpl.render()


@app.post("/generate", response_class=HTMLResponse)
def generate(request: Request, url: str = Form(...)):
    niche_id, niche_name, conf, debug = detect_niche(url)
    leads = fetch_leads_for_niche(niche_id, limit=5)
    tpl = env.get_template("results.html")
    return tpl.render(
        url=url,
        niche_id=niche_id,
        niche_name=niche_name,
        niche_conf=int(conf * 100),
        leads=leads,
    )


@app.get("/pricing", response_class=HTMLResponse)
def pricing_get(request: Request, submitted: bool = False, email: str = ""):
    tpl = env.get_template("pricing.html")
    return tpl.render(submitted=submitted, email=email)


@app.post("/pricing", response_class=HTMLResponse)
def pricing_post(request: Request, email: str = Form(...)):
    # log the email (later: write to leads_emails table)
    print(f"[LEAD] pricing signup: {email}", flush=True)
    tpl = env.get_template("pricing.html")
    return tpl.render(submitted=True, email=email)


@app.get("/health")
def health():
    return {"status": "ok", "service": "outreachos-signals", "version": "0.3.0"}


# ============================================================
# Admin (existing) — keep for internal use
# ============================================================
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    with db() as conn:
        total = conn.execute("select count(*) from signal_events").fetchone()[0]
        classified = conn.execute("select count(*) from signal_classifications where score is not null").fetchone()[0]
        leads = conn.execute("select count(*) from signal_play_accounts").fetchone()[0]
        # top niches by event count
        niche_rows = conn.execute("""
            select n.id, n.name, count(e.event_id) as cnt,
                   avg(c.score) as avg_score
            from niches n
            left join signal_classifications c on c.niche_id = n.id
            left join signal_events e on e.event_id = c.event_id
            group by n.id
            order by cnt desc
        """).fetchall()
        # source breakdown
        source_rows = conn.execute("""
            select source, count(*) as cnt from signal_events group by source order by 2 desc
        """).fetchall()
    return HTMLResponse(env.get_template("dashboard.html").render(
        total=total, classified=classified, leads=leads,
        niches=[dict(r) for r in niche_rows],
        sources=[dict(r) for r in source_rows],
    ))


@app.get("/leads", response_class=HTMLResponse)
def leads_page(request: Request):
    with db() as conn:
        rows = conn.execute("""
            select pa.play_id, pa.event_id, pa.company_domain, pa.score,
                   pa.first_angle, pa.case_match,
                   e.company_name, e.source, e.raw_text, e.collected_at
            from signal_play_accounts pa
            left join signal_events e on e.event_id = pa.event_id
            order by pa.score desc
            limit 200
        """).fetchall()
    return HTMLResponse(env.get_template("leads.html").render(leads=[dict(r) for r in rows]))


@app.get("/niche/{niche_id}", response_class=HTMLResponse)
def niche_page(request: Request, niche_id: int):
    with db() as conn:
        niche = conn.execute("select * from niches where id = ?", (niche_id,)).fetchone()
        if not niche:
            raise HTTPException(404, "niche not found")
        rows = conn.execute("""
            select e.event_id, e.source, e.event_type, e.company_name, e.raw_text, e.collected_at, e.evidence_url,
                   c.score
            from signal_events e
            left join signal_classifications c on c.event_id = e.event_id
            where c.niche_id = ?
            order by c.score desc, e.collected_at desc
            limit 100
        """, (niche_id,)).fetchall()
    return HTMLResponse(env.get_template("niche.html").render(
        niche=dict(niche), events=[dict(r) for r in rows],
        age_fmt=_fmt_age,
    ))


@app.get("/signal/{event_id}", response_class=HTMLResponse)
def signal_page(request: Request, event_id: str):
    with db() as conn:
        ev = conn.execute("select * from signal_events where id = ?", (event_id,)).fetchone()
        if not ev:
            raise HTTPException(404, "event not found")
        cls = conn.execute("select * from signal_classifications where event_id = ?", (event_id,)).fetchone()
        plays = conn.execute("select * from signal_play_accounts where event_id = ?", (event_id,)).fetchall()
    return HTMLResponse(env.get_template("signal.html").render(
        event=dict(ev), classification=dict(cls) if cls else None,
        plays=[dict(r) for r in plays],
        age_fmt=_fmt_age,
    ))


# ============================================================
# JSON API
# ============================================================
@app.get("/api/signals")
def api_signals(limit: int = 50, min_score: float = 0.0, niche_id: int | None = None):
    with db() as conn:
        q = """
            select e.event_id as event_id, e.source, e.event_type, e.company_name, e.company_domain,
                   e.raw_text, e.collected_at, e.evidence_url,
                   c.niche_id, c.score, n.name as niche_name
            from signal_events e
            left join signal_classifications c on c.event_id = e.event_id
            left join niches n on n.id = c.niche_id
            where c.score >= ?
        """
        params: list[Any] = [min_score]
        if niche_id is not None:
            q += " and c.niche_id = ?"
            params.append(niche_id)
        q += " order by c.score desc, e.collected_at desc limit ?"
        params.append(limit)
        rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/leads")
def api_leads(limit: int = 50):
    with db() as conn:
        rows = conn.execute("""
            select pa.play_id, pa.event_id, pa.company_domain, pa.score,
                   pa.first_angle, pa.case_match,
                   e.company_name, e.source
            from signal_play_accounts pa
            left join signal_events e on e.event_id = pa.event_id
            order by pa.score desc
            limit ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/niches")
def api_niches():
    return NICHES_CFG.get("niches", [])


@app.get("/api/stats")
def api_stats():
    with db() as conn:
        return {
            "events": conn.execute("select count(*) from signal_events").fetchone()[0],
            "classifications": conn.execute("select count(*) from signal_classifications where score is not null").fetchone()[0],
            "leads": conn.execute("select count(*) from signal_play_accounts").fetchone()[0],
        }


@app.get("/api/export.xlsx")
def export_xlsx():
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(500, "openpyxl not installed")
    with db() as conn:
        rows = conn.execute("""
            select e.source, e.event_type, e.company_name, e.raw_text, e.collected_at, e.evidence_url,
                   c.niche_id, c.score, c.first_angle
            from signal_events e
            left join signal_classifications c on c.event_id = e.event_id
            order by c.score desc, e.collected_at desc
            limit 5000
        """).fetchall()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Signals"
    ws.append(["source", "event_type", "company", "text", "collected_at", "url", "niche_id", "score", "angle"])
    for r in rows:
        ws.append([r["source"], r["event_type"], r["company_name"], r["raw_text"][:500] if r["raw_text"] else "",
                   r["collected_at"], r["evidence_url"], r["niche_id"], r["score"], r["first_angle"]])
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return StreamingResponse(bio, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": "attachment; filename=outreachos_signals.xlsx"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
