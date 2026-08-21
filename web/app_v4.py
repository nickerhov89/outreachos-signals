"""OutreachOS Signals v4 — Freemium flow with email gate.
- / : input form
- POST /generate : detect niche + show 5 companies (NO contacts)
- POST /reveal : user submits email -> get 3 contacts free
- /pricing : paywall
"""
from __future__ import annotations
import time
import urllib.request
import urllib.parse

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
import sys as _sys_wiz
_sys_wiz.path.insert(0, "/home/manager/outreachos-signals")
try:
    from outreachos_signals.on_demand_signals import aggregate_signal, boost_reason, pick_target_title as _pick_target_title
except Exception as _wiz_imp_err:
    aggregate_signal = None
    boost_reason = None
    _pick_target_title = None
import sqlite3
import yaml
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, Form, HTTPException, Header, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "signals.db"
TEMPLATES_DIR = ROOT / "web" / "templates"
NICHES_PATH = ROOT / "config" / "niches.yaml"
STATIC_DIR = ROOT / "web" / "static"

app = FastAPI(title="OutreachOS Signals", version="0.4.0")

env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    enable_async=False,
)

NICHES_CFG = yaml.safe_load(open(NICHES_PATH)) if NICHES_PATH.exists() else {"niches": []}
NICHES = {n["id"]: n for n in NICHES_CFG.get("niches", [])}

# ============================================================
# Antifraud
# ============================================================
DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "yopmail.com",
    "temp-mail.org", "tempmail.com", "throwaway.email", "maildrop.cc",
    "trashmail.com", "fakeinbox.com", "getnada.com", "sharklasers.com",
    "mailnesia.com", "dispostable.com", "mintemail.com", "emailondeck.com",
    "spamgourmet.com", "spambog.com", "spambox.us", "spam4.me", "bccto.me",
    "chammy.info", "devnullmail.com", "letthemeatspam.com", "mailinater.com",
    "mailnull.com", "mbx.cc", "no-spam.ws", "objectmail.com", "proxymail.eu",
    "rcpt.at", "reallymymail.com", "recode.me", "rmqkr.net", "rppkn.com",
    "rtrtr.com", "s0ny.net", "safetymail.info", "sandelf.de", "saynotospams.com",
    "schafmail.de", "schrott-email.de", "secretemail.de", "sendspamhere.com",
    "sharedmailbox.org", "shieldedmail.com", "shieldemail.com", "shitmail.me",
    "shitware.nl", "shmeriously.com", "shortmail.net", "shotmail.ru",
    "showslow.de", "sify.com", "sinnlos-mail.de", "skeefmail.com", "slapsfromyo.com",
    "slaskpost.se", "smashmail.de", "smellfear.com", "snakemail.com", "sneakemail.de",
    "snkmail.com", "sofimail.com", "sofort-mail.de", "solvemail.info", "sogetthis.com",
    "soodonims.com", "spam.la", "spam.su", "spamavert.com", "spambob.com",
    "spambob.net", "spambog.com", "spambog.de", "spambog.net", "spambog.org",
    "spambooger.com", "spambox.info", "spambox.irishspringrealty.com", "spamcero.com",
    "spamcon.org", "spamcorptastic.com", "spamcowboy.com", "spamcowboy.net",
    "spamcowboy.org", "spamday.com", "spamfree.eu", "spamfree24.com", "spamfree24.de",
    "spamfree24.eu", "spamfree24.info", "spamfree24.net", "spamfree24.org",
    "spamgoes.in", "spamherelots.com", "spamhereplease.com", "spamhole.com",
    "spamify.com", "spaminator.de", "spamkill.info", "spaml.com", "spaml.de",
    "spammotel.com", "spamobox.com", "spamoff.de", "spamslicer.com", "spamspot.com",
    "spamthis.co.uk", "spamtroll.net", "speed.1s.fr", "superrito.com", "suremail.info",
    "teewars.org", "teleworm.com", "teleworm.us", "thankyou2010.com", "thc.st",
    "thelimestones.com", "thisisnotmyrealemail.com", "throwam.com", "tilien.com",
    "tittbit.in", "tizi.com", "topranklist.de", "trash2009.com", "trash2010.com",
    "trash2011.com", "trash-amil.com", "trashcanmail.com", "trashdevil.com",
    "trashemail.de", "trashinbox.com", "trashmail.at", "trashmail.io", "trashmail.me",
    "trashmail.net", "trashmail.org", "trashmail.ws", "trashmailer.com", "trashymail.com",
    "trashymail.net", "trbvm.com", "trialmail.de", "trillianpro.com", "twinmail.de",
    "tyldd.com", "uggsrock.com", "umail.net", "upliftnow.com", "uplipht.com",
    "venompen.com", "veryrealemail.com", "vidchart.com", "viralplays.com", "vmpanda.com",
    "vomoto.com", "vpn.st", "vsimcard.com", "vubby.com", "wasteland.rfc822.org",
    "webm4il.info", "webuser.in", "wee.my", "weg-werf-email.de", "wegwerf-email.de",
    "wegwerf-email.net", "wegwerf-email.org", "wegwerf-emails.de", "wegwerfemail.com",
    "wegwerfmail.de", "wegwerfmail.info", "wegwerfmail.net", "wegwerfmail.org",
    "wetrainbayarea.com", "wetrainbayarea.org", "wh4f.org", "whyspam.me", "wilemail.com",
    "wmail.club", "writeme.us", "wuzup.net", "wuzupmail.net", "www.e4ward.com",
    "www.gishpuppy.com", "www.mailinator.com", "wwwnew.eu", "xagloo.com", "xemaps.com",
    "xents.com", "xmaily.com", "xoxy.net", "yapped.net", "yep.it", "yogamaven.com",
    "yopolis.com", "ypmail.webarnament.fr", "yuurok.com", "zehnminutenmail.de",
    "zoemail.com", "spambox.xyz", "tempmailaddress.com", "tempmailbox.com", "tempmail.email",
    "tempmailer.com", "tempemail.com", "tempemail.net", "tempinbox.com", "tempmail.us",
    "tempmailo.com", "tempymail.com", "thankyou2010.com", "tilien.com", "tmailinator.com",
    "toomail.biz", "topranklist.de", "tradermail.info", "tilien.com", "tilien.nl",
    "tzi.me", "upliftnow.com", "venompen.com", "viralplays.com", "vmpanda.com",
    "wegwerf-email.de", "wegwerfemail.com", "wegwerfmail.de", "wegwerfmail.info",
    "wegwerfmail.net", "wegwerfmail.org", "wetrainbayarea.com", "wh4f.org", "whyspam.me",
    "wuzup.net", "yapped.net", "yep.it", "yogamaven.com", "yopolis.com", "ypmail.webarnament.fr",
    "yuurok.com", "zehnminutenmail.de", "zoemail.com", "spamherelots.com", "spamhereplease.com",
}

# Bad domains to exclude from leads (we won't show "Unknown" or ATS sites as leads)
BAD_DOMAINS = {
    "greenhouse.io", "lever.co", "reddit.com", "github.com", "ycombinator.com",
    "google.com", "news.google.com", "news.ycombinator.com", "twitter.com",
    "facebook.com", "linkedin.com", "medium.com", "youtube.com",
    "g2.com", "capterra.com", "trustpilot.com", "glassdoor.com",
    "facebook.com", "instagram.com", "producthunt.com", "crunchbase.com",
    "techcrunch.com", "yahoo.com", "aol.com", "outlook.com", "hotmail.com",
    "duckduckgo.com", "w3.org", "schema.org", "github.io", "wikipedia.org",
}




# ============================================================
# Apollo.io helpers (verified corporate emails, 1 credit/reveal)
# ============================================================
APOLLO_KEY = os.getenv("APOLLO_API_KEY", "")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("CLASSIFIER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")

# LLM fallback chain (in case primary provider is overloaded)
LLM_FALLBACK_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "openrouter/free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-5-lightning:free",
]


def _llm_chat(messages: list, model: str = None, max_tokens: int = 1500, temperature: float = 0.3, timeout: int = 60) -> dict:
    """Call LLM with fallback chain. Returns dict with 'content', 'model', 'error'."""
    models_to_try = [model or OPENROUTER_MODEL] + [m for m in LLM_FALLBACK_MODELS if m != (model or OPENROUTER_MODEL)]
    last_err = None
    for mdl in models_to_try:
        body = json.dumps({
            "model": mdl,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }).encode()
        req = _ur.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
        )
        try:
            with _ur.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            if "choices" in data and data["choices"]:
                return {"content": data["choices"][0]["message"]["content"], "model": mdl}
            last_err = f"{mdl}: no choices ({list(data.keys())[:3]})"
        except Exception as e:
            last_err = f"{mdl}: {type(e).__name__}: {str(e)[:80]}"
            continue
    return {"content": "", "error": last_err or "all_models_failed"}

APOLLO_BASE = "https://api.apollo.io/v1"

# Daily cap: 30 reveals/day = $0.15-1.50 depending on plan
APOLLO_DAILY_CAP = int(os.getenv("APOLLO_DAILY_CAP", "30"))

# C-suite / VP titles for ICP match
APOLLO_BUYER_TITLES = [
    "founder", "co-founder", "ceo", "chief", "head of", "vp", "vice president",
    "director", "cmo", "cfo", "coo", "cro", "chief revenue", "revenue officer",
    "head of marketing", "head of sales", "head of growth", "head of partnerships",
    "vp sales", "vp marketing", "vp growth", "vp engineering",
    "marketing", "growth", "sales", "partnerships", "revenue", "demand gen",
    "business development", "bd", "devrel", "developer relations",
]


def _apollo_used_today() -> int:
    """Count Apollo reveals logged in lead_views today."""
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            row = conn.execute("""
                select count(*) from lead_views
                where user_agent like '%%apollo%%' and created_at > datetime('now', '-1 day')
            """).fetchone()
            return row[0] if row else 0
    except Exception:
        return 0


def _apollo_post(path: str, data: dict) -> dict | None:
    if not APOLLO_KEY:
        return None
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{APOLLO_BASE}{path}",
        data=body,
        headers={"X-Api-Key": APOLLO_KEY, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except Exception as ex:
        print(f"  [APOLLO ERR] {path}: {ex}", flush=True)
        return None


def apollo_top_buyer(domain: str) -> dict | None:
    """Search Apollo for a top buyer at the domain and reveal their email (1 credit)."""
    if not APOLLO_KEY:
        return None
    if _apollo_used_today() >= APOLLO_DAILY_CAP:
        return None
    # 1. search top person
    s = _apollo_post("/mixed_people/api_search", {
        "q_organization_domains": domain,
        "person_titles": [
            "Founder", "Co-Founder", "CEO", "Chief Executive Officer",
            "Chief Revenue Officer", "CRO", "Chief Marketing Officer", "CMO",
            "Chief Financial Officer", "CFO", "Chief Operating Officer", "COO",
            "Head of Sales", "VP Sales", "Head of Marketing", "VP Marketing",
            "Head of Growth", "VP Growth", "Head of Partnerships", "VP Partnerships",
            "Head of Business Development", "VP Business Development",
        ],
        "page": 1, "per_page": 1,
    })
    if not s or not s.get("people"):
        return None
    pid = s["people"][0].get("id")
    if not pid:
        return None
    # 2. reveal (costs 1 credit)
    r = _apollo_post("/people/match", {"id": pid})
    if not r or not r.get("person"):
        return None
    p = r["person"]
    em = p.get("email")
    if not em or "@" not in em:
        return None
    return {
        "name": p.get("name") or "",
        "email": em,
        "email_status": p.get("email_status") or "",
        "title": p.get("title") or "",
        "level": p.get("seniority") or "",
        "linkedin": p.get("linkedin_url") or "",
        "city": p.get("city") or "",
        "functions": p.get("functions") or [],
        "source": "apollo",
    }



def is_valid_email(email: str) -> tuple[bool, str]:
    """Check if email is valid + not disposable. Returns (ok, reason)."""
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return False, "invalid_format"
    if len(email) > 254:
        return False, "too_long"
    local, _, domain = email.partition("@")
    if not local or not domain or "." not in domain:
        return False, "invalid_format"
    if domain in DISPOSABLE_DOMAINS:
        return False, "disposable_email"
    # catch-all role emails (info@, support@, etc.) — not antifraud but warn
    if local in ("info", "support", "admin", "noreply", "no-reply", "postmaster"):
        return False, "role_email"
    return True, "ok"


def get_client_ip(request: Request) -> str:
    """Get real client IP (works behind Caddy/Cloudflare)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"


def antifraud_check(request: Request, email: str) -> tuple[bool, str, dict]:
    """Returns (ok, reason, info). Blocks based on IP/email rate limits."""
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent", "")
    info = {"ip": ip, "ua": ua[:80], "email": email}
    # UA check
    if not ua or len(ua) < 20:
        return False, "no_ua", info
    if "bot" in ua.lower() or "crawler" in ua.lower() or "spider" in ua.lower():
        return False, "bot_ua", info
    # IP rate limit: 10 reveals per day
    with sqlite3.connect(str(DB_PATH)) as db:
        n_ip = db.execute("""
            select count(*) from lead_views
            where ip_address = ? and created_at > datetime('now', '-1 day')
        """, (ip,)).fetchone()[0]
        if n_ip >= 10:
            return False, f"ip_rate_limit_{n_ip}", info
        # email rate limit: 3 reveals per day
        n_em = db.execute("""
            select count(*) from lead_views
            where email = ? and created_at > datetime('now', '-1 day')
        """, (email.lower(),)).fetchone()[0]
        if n_em >= 3:
            return False, f"email_rate_limit_{n_em}", info
    return True, "ok", info


# ============================================================
# DB helpers
# ============================================================
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _age_days(iso: str | None) -> int:
    if not iso:
        return 999
    try:
        if "T" in iso:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(iso, "%Y-%m-%d %H:%M:%S")
        delta = datetime.now(timezone.utc) - (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt)
        return max(0, delta.days)
    except Exception:
        return 999


def _fmt_age(iso: str | None) -> str:
    d = _age_days(iso)
    if d == 0: return "today"
    if d == 1: return "1d"
    if d < 30: return f"{d}d"
    return f"{d // 30}mo"


def _age_filter(iso):
    return _fmt_age(iso)


env.filters["age"] = _age_filter


# ============================================================
# Niche detection
# ============================================================
def _normalize_url(url: str) -> tuple[str, str]:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    domain = (parsed.netloc or "").lower().replace("www.", "")
    return domain, url


def _fetch_meta(url: str, timeout: float = 4.0) -> dict:
    try:
        r = requests.get(url, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }, allow_redirects=True)
        html = r.text[:50000]
    except Exception:
        return {"title": "", "description": ""}
    title = ""
    desc = ""
    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    if m: title = m.group(1).strip()
    m = re.search(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']', html, re.I)
    if not m:
        m = re.search(r'<meta\s+content=["\']([^"\']+)["\']\s+name=["\']description["\']', html, re.I)
    if m: desc = m.group(1).strip()
    if not desc:
        m = re.search(r'<meta\s+property=["\']og:description["\']\s+content=["\']([^"\']+)["\']', html, re.I)
        if m: desc = m.group(1).strip()
    return {"title": title, "description": desc}


def detect_niche(url: str) -> tuple[int | None, str | None, float, dict]:
    domain, full_url = _normalize_url(url)
    if not domain:
        return None, None, 0.0, {"error": "no_domain"}
    meta = _fetch_meta(full_url)
    text = f"{domain} {meta.get('title','')} {meta.get('description','')}".lower()
    best = (None, None, 0.0)
    scores = []
    for nid, niche in NICHES.items():
        overrides = set(d.lower() for d in niche.get("domain_overrides", []))
        if domain in overrides:
            return nid, niche["name"], 1.0, {"domain": domain, "override": True}
        kw = set()
        kw |= set(k.lower() for k in niche.get("keywords", []))
        kw |= set(k.lower() for k in niche.get("ats_titles", []))
        kw |= set(k.lower() for k in niche.get("threads_keywords", []))
        kw |= set(k.lower() for k in niche.get("linkedin_queries", []))
        if not kw:
            continue
        hits = 0
        for k in kw:
            if k in text:
                hits += 1 + (len(k) > 8)
        if hits == 0:
            continue
        score = min(1.0, hits / 3.0)
        scores.append((nid, niche["name"], score, hits))
        if score > best[2]:
            best = (nid, niche["name"], score)
    debug = {"domain": domain, "title": meta.get("title", ""), "desc": meta.get("description", "")[:200], "scores": scores[:3]}
    if best[0] is not None:
        return best[0], best[1], best[2], debug
    return None, None, 0.0, debug


# ============================================================
# Smart lead query (no Unknown / no ATS / no news)
# ============================================================
def fetch_clean_leads(niche_id: int, limit: int = 5) -> list[dict]:
    """Get top-scored leads with REAL domains + real company names."""
    with db() as conn:
        rows = conn.execute("""
            SELECT e.event_id as event_id, e.source, e.event_type, e.company_name,
                   e.company_domain, e.raw_text, e.collected_at, e.evidence_url,
                   c.niche_id, c.score, c.buyer_contacts_json, n.name as niche_name
            FROM signal_events e
            JOIN signal_classifications c ON c.event_id = e.event_id
            LEFT JOIN niches n ON n.id = c.niche_id
            WHERE c.niche_id = ?
              AND c.score IS NOT NULL
              AND e.company_domain IS NOT NULL
              AND e.company_domain != ''
              AND e.company_domain NOT IN (
                  'greenhouse.io','lever.co','reddit.com','github.com','ycombinator.com',
                  'google.com','news.google.com','twitter.com','facebook.com',
                  'linkedin.com','medium.com','youtube.com','g2.com','capterra.com',
                  'trustpilot.com','glassdoor.com','instagram.com','producthunt.com',
                  'crunchbase.com','techcrunch.com','yahoo.com','aol.com','outlook.com',
                  'duckduckgo.com','w3.org','schema.org','github.io','wikipedia.org'
              )
              AND e.company_domain NOT LIKE 'news.%'
              AND e.company_domain NOT LIKE 'github.com/%'
              AND e.company_name IS NOT NULL
              AND e.company_name != 'Unknown'
              AND e.company_name != ''
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
        # parse contacts
        contacts = []
        if d.get("buyer_contacts_json"):
            try:
                payload = json.loads(d["buyer_contacts_json"])
                contacts = payload.get("contacts", [])
            except Exception:
                pass
        d["has_contacts"] = len(contacts) > 0
        d["contact_count"] = len(contacts)
        d["_contacts"] = contacts  # hidden until email gate
        leads.append(d)
    return leads


# ============================================================
# Static
# ============================================================
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ============================================================
# Routes
# ============================================================

# ============================================================
def enrich_user(domain: str) -> dict | None:
    """Apollo /organizations/enrich - returns full firmographics."""
    if not APOLLO_KEY:
        return None
    r = _apollo_post("/organizations/enrich", {})
    # The endpoint is GET, not POST
    url = f"{APOLLO_BASE}/organizations/enrich?domain={domain}"
    try:
        req = urllib.request.Request(url, headers={"X-Api-Key": APOLLO_KEY})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        return data.get("organization") or None
    except Exception as ex:
        print(f"  [APOLLO ORG ERR] {domain}: {ex}", flush=True)
        return None

# Flow B: /analyze + /targets (multi-param ICP + 20 target companies)
# ============================================================
import re as _re
from collections import Counter as _Counter

# Inline target matrix (mirrors /tmp/icp_matrix.py)
TARGET_MATRIX = {
    "sales engagement / conversation intelligence": {
        "kw": ["sales","revenue","outbound","conversation","call","dialer","cadence"],
        "targets": ["outreach.io","salesloft.com","apollo.io","chili-piper.com","drift.com","aircall.io","mixmax.com","yesware.com","calendly.com","lavender.ai","persana.ai","zoominfo.com","lusha.com","cognism.com","gong.io"],
    },
    "crm / bpm / sales ops": {
        "kw": ["crm","sales","customer relationship","pipeline","deal","forecast","bpm"],
        "targets": ["hubspot.com","pipedrive.com","close.com","copper.com","attio.com","folk.app","freshworks.com","zoho.com","bitrix24.com","insightly.com","creatio.com","nimble.com","snov.io","woodpecker.co"],
    },
    "martech / email automation": {
        "kw": ["email","marketing","campaign","automation","sms","push","drip"],
        "targets": ["klaviyo.com","customer.io","iterable.com","braze.com","segment.com","mparticle.com","sendgrid.com","mailgun.com","postmarkapp.com","beehiiv.com","convertkit.com","mailerlite.com","activecampaign.com","drip.com","sendlane.com"],
    },
    "b2b saas / productivity": {
        "kw": ["saas","productivity","collaboration","project","task","notes","wiki"],
        "targets": ["asana.com","monday.com","clickup.com","slack.com","airtable.com","coda.io","aha.io","typeform.com","miro.com","webflow.com","framer.com","cal.com","pitch.com","height.app","todoist.com","linear.app","zapier.com","make.com","n8n.io","fibery.io","trello.com","anytype.io"],
    },
    "design / prototyping": {
        "kw": ["design","prototype","framer","figma","sketch","wireframe","ui","ux","visual"],
        "targets": ["figma.com","sketch.com","invisionapp.com","marvelapp.com","framer.com","webflow.com","principleformac.com","origami.studio","uxpin.com","mockplus.com","balsamiq.com","proto.io","flowmapp.com","mockflow.com","draftium.com","sympli.io","zeplin.io","avocode.com","abstract.com"],
    },
    "cloud / infrastructure": {
        "kw": ["cloud","infrastructure","hosting","devops","kubernetes","serverless","edge"],
        "targets": ["netlify.com","railway.app","render.com","fly.io","planetscale.com","neon.tech","supabase.com","turso.tech","deno.com","upstash.com","bun.sh","vercel.com","northflank.com","koyeb.com"],
    },
    "ai / data / ml": {
        "kw": ["ai","ml","machine learning","data","llm","model","vector","embeddings"],
        "targets": ["scale.com","huggingface.co","replicate.com","pinecone.io","weights.com","anyscale.com","together.ai","fireworks.ai","modal.com","runpod.io","lambda.com","cohere.com","anthropic.com","openai.com","perplexity.ai","groq.com"],
    },
    "it / devops / security": {
        "kw": ["security","siem","observability","monitoring","devops","vulnerability","compliance"],
        "targets": ["datadoghq.com","splunk.com","newrelic.com","dynatrace.com","crowdstrike.com","okta.com","1password.com","snyk.io","wiz.io","sentinelone.com","tenable.com","rapid7.com","sumologic.com","logz.io","grafana.com"],
    },
    "hrtech / people ops": {
        "kw": ["hr","human","payroll","hiring","recruiting","people","benefits"],
        "targets": ["rippling.com","gusto.com","deel.com","remote.com","justworks.com","bamboohr.com","hibob.com","workable.com","lever.co","greenhouse.io","personio.com","factorialhr.com","workday.com","namely.com","lattice.com"],
    },
    "fintech / payments": {
        "kw": ["fintech","payment","banking","card","transaction","invoice","treasury"],
        "targets": ["brex.com","ramp.com","mercury.com","plaid.com","affirm.com","wise.com","checkout.com","bill.com","mollie.com","adyen.com","klarna.com","stripe.com","revolut.com","bunq.com","qonto.com"],
    },
    "edtech / online learning": {
        "kw": ["education","learning","course","student","tutor","lms","training"],
        "targets": ["duolingo.com","brilliant.org","skillshare.com","masterclass.com","coursera.org","udemy.com","pluralsight.com","udacity.com","khanacademy.org","edmodo.com","teachable.com","thinkific.com","circle.so"],
    },
    "marketplace / e-commerce": {
        "kw": ["marketplace","commerce","retail","shop","store","checkout","fulfillment"],
        "targets": ["etsy.com","vinted.com","gumroad.com","fiverr.com","upwork.com","toptal.com","arc.dev","contra.com","lemonsqueezy.com","podia.com","kofi.com","shipbob.com","deliverr.com"],
    },
    "marketplace / freelance / creator": {
        "kw": ["marketplace","freelance","freelancer","gig","creator","talent","contractor","consultant"],
        "targets": ["contra.com","fiverr.com","upwork.com","toptal.com","arc.dev","lemonsqueezy.com","gumroad.com","podia.com","kofi.com","outseta.com","cameo.com","substack.com","revue.com","sellfy.com","payhip.com","memberful.com","ghost.io"],
    },
    "legal / compliance": {
        "kw": ["legal","contract","compliance","e-signature","policy","gdpr"],
        "targets": ["docusign.com","pandadoc.com","hellosign.com","ironcladapp.com","ironclad.io","linkedsign.com","contractworks.com","termly.io","iubenda.com","privy.com"],
    },
    "support / customer success": {
        "kw": ["support","help desk","ticketing","customer success","chatbot","knowledge base"],
        "targets": ["zendesk.com","intercom.com","freshdesk.com","helpscout.com","drift.com","tidio.com","crisp.chat","liveagent.com","gainsight.com","totango.com","vitally.io","planhat.com","churnzero.com"],
    },
    "analytics / product": {
        "kw": ["analytics","product analytics","events","funnel","cohort","dashboard","bi"],
        "targets": ["amplitude.com","mixpanel.com","heap.io","posthog.com","hotjar.com","fullstory.com","logrocket.com","pendo.com","segment.com","snowplow.io","plausible.io","matomo.org"],
    },
    "content / seo / social": {
        "kw": ["content","seo","social","blog","cms","scheduling","analytics"],
        "targets": ["buffer.com","hootsuite.com","later.com","sproutsocial.com","semrush.com","ahrefs.com","moz.com","clearscope.com","surfer.com","frase.io","coschedule.com","planable.io","socialbee.com"],
    },
    "accounting / bookkeeping": {
        "kw": ["accounting","bookkeeping","tax","invoicing","expense","finance ops"],
        "targets": ["xero.com","quickbooks.com","freshbooks.com","waveapps.com","ramp.com","brex.com","mercury.com","pilot.com","bench.co","doola.com","found.com"],
    },
}


def _detect_vertical(text: str) -> tuple[str, float]:
    text = (text or "").lower()
    scores = {}
    for vertical, cfg in TARGET_MATRIX.items():
        s = 0
        for kw in cfg["kw"]:
            if kw in text:
                s += 2
        for word in vertical.replace("/", " ").split():
            if len(word) > 3 and word in text:
                s += 1
        scores[vertical] = s
    if not scores:
        return "b2b saas / productivity", 0.0
    top = max(scores, key=scores.get)
    conf = min(1.0, scores[top] / 10.0)
    return top, conf


def _user_titles(domain: str) -> tuple[list, list]:
    """Get user's employee title keywords (FREE)."""
    data = _apollo_post("/mixed_people/api_search", {
        "q_organization_domains": domain, "page": 1, "per_page": 50,
    })
    if not data or not isinstance(data, dict):
        return [], []
    titles = []
    for p in data.get("people", []):
        t = p.get("title") or ""
        if t:
            titles.append(t.lower())
    words = []
    for t in titles:
        for w in _re.split(r"[\s,/]+", t):
            w = w.strip(".,()-:&")
            if len(w) > 3 and w.isalpha():
                words.append(w)
    return _Counter(words).most_common(20), titles


def _lpr_titles(titles: list) -> list:
    LPR_KW = ["founder","co-founder","ceo","chief","cro","cmo","cfo","coo","cto","cpo","vp ","vice president","head of","director"]
    out = []
    for t in titles:
        if any(k in t for k in LPR_KW):
            out.append(t.title())
    return list(dict.fromkeys(out))[:10]


def _normalize_domain(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace("https://", "").replace("http://", "").replace("www.", "")
    return s.split("/")[0].split("?")[0]


@app.post("/analyze")
def analyze(request: Request, url: str = Form(...)):
    """Multi-param ICP analysis from user URL. Returns JSON with full ICP profile + reasoning."""
    domain = _normalize_domain(url)
    org = enrich_user(domain)
    if not org:
        return JSONResponse({"ok": False, "error": f"Could not enrich {domain}"}, status_code=400)

    kws, titles = _user_titles(domain)
    lprs = _lpr_titles(titles)
    text = " ".join([
        (org.get("industry") or "").lower(),
        " ".join((org.get("keywords") or [])).lower(),
        " ".join([w for w, _ in kws]).lower(),
    ])
    vertical, conf = _detect_vertical(text)
    emp = org.get("estimated_num_employees") or 50
    size_band = [max(10, emp // 5), emp * 5]
    geo = org.get("country") or "United States"

    return JSONResponse({
        "ok": True,
        "user": {
            "domain": domain,
            "name": org.get("name"),
            "industry": org.get("industry"),
            "employees": emp,
            "country": geo,
            "city": org.get("city"),
            "founded": org.get("founded_year"),
            "keywords": (org.get("keywords") or [])[:8],
            "linkedin": org.get("linkedin_url"),
        },
        "icp": {
            "vertical": vertical,
            "confidence": round(conf, 2),
            "size_band": size_band,
            "geo": geo,
            "lpr_titles": lprs,
            "title_keywords": [w for w, _ in kws[:10]],
        },
        "reasoning": [
            f"Industry '{org.get('industry', '?')}' matched vertical '{vertical}' (conf={conf:.0%})",
            f"User has {emp} employees → target size band {size_band[0]}-{size_band[1]}",
            f"User in {geo} → matching geos: {geo}, English-speaking markets",
            f"User employee titles indicate GTM: {', '.join([w for w, _ in kws[:5]])}",
            f"LPR roles at user: {', '.join(lprs[:5]) if lprs else 'too small to detect'}",
        ],
        "sources_used": ["Apollo /organizations/enrich", "Apollo /mixed_people/api_search", "Vertical keyword matrix"],
    })


@app.post("/targets")
def targets(request: Request, url: str = Form(...), n: str = Form(default="20"), vertical: str = Form(default="")):
    """Get 20 target companies matching user's ICP. No contacts yet."""
    domain = _normalize_domain(url)
    # Re-run analysis if no vertical provided
    if not vertical:
        org = enrich_user(domain)
        if not org:
            return JSONResponse({"ok": False, "error": f"Could not enrich {domain}"}, status_code=400)
        kws, _ = _user_titles(domain)
        text = " ".join([
            (org.get("industry") or "").lower(),
            " ".join((org.get("keywords") or [])).lower(),
            " ".join([w for w, _ in kws]).lower(),
        ])
        vertical, _ = _detect_vertical(text)

    n_int = min(50, max(1, int(n) if n.isdigit() else 20))
    cfg = TARGET_MATRIX.get(vertical, {})
    candidates = [c for c in cfg.get("targets", []) if c != domain][:n_int]

    return JSONResponse({
        "ok": True,
        "user_domain": domain,
        "vertical": vertical,
        "count": len(candidates),
        "targets": [{"domain": d, "rank": i+1, "source": "matrix"} for i, d in enumerate(candidates)],
    })





# ============================================================
# Wizard: LLM-inferred ICP + signal-driven discovery (4-step UX)
# ============================================================
import urllib.request as _ur

def _wizard_fetch_homepage(url: str) -> str:
    try:
        req = _ur.Request(url, headers={"User-Agent": "Mozilla/5.0 OutreachOS/0.1"})
        with _ur.urlopen(req, timeout=10) as r:
            html = r.read().decode("utf-8", errors="ignore")[:80000]
        text = re.sub(r"<script.*?</script>", " ", html, flags=re.DOTALL)
        text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text[:4000]
    except Exception:
        return ""


def _wizard_llm_guess_icp(domain: str, homepage_text: str) -> dict:
    if not OPENROUTER_KEY:
        return {"error": "no OPENROUTER_KEY", "domain": domain}
    prompt = f"""You are a B2B sales analyst. Given a company URL and homepage, infer their B2B sales profile.

URL: {domain}

Homepage text:
{homepage_text[:3000]}

Return STRICT JSON only (no markdown, no commentary):
{{
  "company_name": "string",
  "niche": "string (e.g. 'B2B SaaS / CRM')",
  "industry": "string",
  "inferred_product": "one-line what they sell",
  "size_band": [min, max],
  "geo": "string",
  "buyer_titles": ["string"],
  "industry_keywords": ["string"],
  "excluded_industries": ["string"],
  "confidence": 0.0
}}"""
    result = _llm_chat(
        messages=[
            {"role": "system", "content": "You are a B2B sales analyst. Return strict JSON only, no markdown, no commentary."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=1500,
        temperature=0.2,
    )
    if not result.get("content"):
        return {"error": f"llm_failed: {result.get('error', 'unknown')}", "domain": domain}
    text = result["content"]
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text.strip())
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group(0)
    text = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        parsed = json.loads(text)
        parsed["domain"] = domain
        if isinstance(parsed.get("size_band"), list):
            parsed["size_band"] = [int(x) for x in parsed["size_band"]]
        return parsed
    except Exception as e:
        return {"error": f"json_parse_failed: {text[:200]}", "domain": domain}


def _wizard_discover(icp: dict, n: int = 20) -> dict:
    """Fast target generation: LLM only (no Apollo). Apollo runs in /reveal on demand.
    Returns raw 20 targets in 5-10s. Avoids competitors via strict prompt.
    """
    kws = icp.get("industry_keywords", [])
    titles = icp.get("buyer_titles", [])
    industry = icp.get("industry", "")
    geo = icp.get("geo", "")
    size_band = icp.get("size_band", [50, 200])
    if isinstance(size_band, list) and len(size_band) == 2:
        size_min, size_max = int(size_band[0]), int(size_band[1])
    else:
        size_min, size_max = 50, 200
    inferred = icp.get("inferred_product", "")
    company = icp.get("company_name", "?")
    excluded = icp.get("excluded_industries", [])

    if not kws and not titles and not industry:
        return {"icp": icp, "raw_count": 0, "validated_count": 0, "targets": [], "error": "no keywords"}

    prompt = f"""You are a B2B sales strategist finding IDEAL CUSTOMER companies for the user's product.

USER PRODUCT (DO NOT INCLUDE AS A TARGET — these are the SELLER):
- Company: {company}
- Product: {inferred}
- Their industry: {industry}
- Their keywords: {', '.join(kws[:10])}

TASK: Generate {n} ideal CUSTOMER companies (companies that WOULD BUY the user's product to solve their pain).
- These are PROSPECTS, not competitors.
- DO NOT include any company in the same vertical as the seller (e.g. if user sells cold email tool, don't include other cold email tools, sales engagement, email automation, outreach tools).
- DO include companies in ADJACENT verticals that have a sales team needing cold outreach (B2B SaaS, agencies, recruiters, fintech sales teams, IT services, consultants).
- Size: {size_min}-{size_max} employees preferred.
- Geo: {geo} preferred, then English-speaking countries.
- Excluded industries: {', '.join(excluded[:5])}.

For each target provide: domain (no https), name, country, employees (number), industry, target_title (the LPR who would buy).

CRITICAL: Return STRICT JSON only, no markdown, no commentary.
Schema: {{"targets":[{{"domain":"x.com","name":"X","country":"US","employees":100,"industry":"B2B SaaS","target_title":"VP Sales"}}, ...{n} entries]}}"""

    t0 = time.time()
    result = _llm_chat(
        messages=[
            {"role": "system", "content": "You are a B2B sales strategist. Find PROSPECT companies, NOT competitors. Return strict JSON only."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=6000,
        temperature=0.4,
        timeout=90,
    )
    if not result.get("content"):
        return {"error": f"llm_failed: {result.get('error', 'unknown')}", "icp": icp, "targets": [], "raw_count": 0, "validated_count": 0, "elapsed": round(time.time()-t0,1)}
    text = result["content"]

    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text.strip())
    m2 = re.search(r"\{.*\}", text, re.DOTALL)
    if m2:
        text = m2.group(0)
    try:
        parsed = json.loads(re.sub(r",\s*([}\]])", r"\1", text))
    except Exception as e:
        return {"error": f"parse_failed: {e}", "raw_text": text[:300], "icp": icp, "targets": [], "raw_count": 0, "validated_count": 0, "elapsed": round(time.time()-t0,1)}

    # Filter the seller themselves
    seller_domain = (icp.get("domain") or "").lower().replace("https://", "").replace("http://", "").split("/")[0]
    seller_name = (icp.get("company_name") or "").lower()
    user_industry = (icp.get("industry") or "").lower()
    user_kws = [w for w in (kws + [industry]) if w]
    user_kw_set = set()
    for kw in user_kws:
        user_kw_set.update(w.lower() for w in str(kw).split() if len(w) > 3)

    targets = []
    seen_domains = set()
    for t in parsed.get("targets", []):
        dom = (t.get("domain") or "").strip().lower().replace("https://", "").replace("http://", "").split("/")[0]
        if not dom or "." not in dom or dom in seen_domains:
            continue
        if seller_domain and (seller_domain == dom or dom.endswith("." + seller_domain) or seller_domain.endswith("." + dom)):
            continue
        nm = (t.get("name") or "").lower()
        if seller_name and seller_name in nm:
            continue
        # Filter obvious competitors (any target whose industry overlaps user keywords heavily)
        tgt_industry = (t.get("industry") or "").lower()
        tgt_kw_set = set(w for w in tgt_industry.split() if len(w) > 3)
        overlap = len(user_kw_set & tgt_kw_set) / max(len(user_kw_set), 1) if user_kw_set else 0
        if overlap > 0.4:
            continue  # likely competitor
        seen_domains.add(dom)
        try:
            emp = int(t.get("employees") or 0)
        except Exception:
            emp = 0
        targets.append({
            "domain": dom,
            "name": t.get("name") or dom,
            "country": (t.get("country") or "").upper()[:3],
            "employees": emp,
            "industry": t.get("industry") or "",
            "target_title": t.get("target_title") or "VP Sales",
            "reason": f"Adjacent vertical ({t.get('industry', 'B2B')}) — likely needs {inferred or 'your product'}",
            "competitor_score": round(overlap, 2),
        })
        if len(targets) >= n:
            break

    # ===== On-demand signal enrichment (parallel, ~8-12s for 20 companies) =====
    if aggregate_signal and targets:
        with ThreadPoolExecutor(max_workers=5) as ex:
            sigs = list(ex.map(lambda t: (t, aggregate_signal(t["domain"])), targets))
        for tgt, sig in sigs:
            tgt["signal_score"] = sig.get("total_score", 0)
            tgt["primary_signal"] = sig.get("primary_signal", "none")
            if boost_reason:
                tgt["reason"] = boost_reason(sig, tgt["reason"])
            if _pick_target_title:
                tgt["target_title"] = _pick_target_title(sig, tgt.get("target_title", "VP Sales"))
            # Cache hits in DB (fire-and-forget)
            try:
                with sqlite3.connect(str(DB_PATH)) as conn:
                    for src_name, src_info in sig.get("sources", {}).items():
                        if src_info.get("has_signal"):
                            ev_id = f"on_demand_{src_name}_{tgt['domain']}_{int(time.time())}"
                            conn.execute(
                                """INSERT OR IGNORE INTO signal_events
                                   (event_id, source, company_name, company_domain, raw_text, url, event_date, ingested_at)
                                   VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
                                (ev_id, f"on_demand_{src_name}", tgt["name"], tgt["domain"],
                                 json.dumps(src_info)[:500], f"https://{tgt['domain']}"),
                            )
                    conn.commit()
            except Exception:
                pass
        # Sort: companies with strong signals first
        targets.sort(key=lambda t: (t.get("primary_signal") == "none", -t.get("signal_score", 0)))

    return {
        "icp": icp,
        "raw_count": len(parsed.get("targets", [])),
        "validated_count": len(targets),
        "targets": targets,
        "elapsed": round(time.time()-t0, 1),
    }

@app.get("/wizard", response_class=HTMLResponse)
def wizard_page(request: Request):
    return HTMLResponse(env.get_template("wizard.html").render())


@app.post("/api/guess_icp")
async def api_guess_icp(request: Request, url: str = Form(...)):
    norm = _normalize_url(url)
    domain = norm[0] if isinstance(norm, tuple) else norm
    if not domain:
        return JSONResponse({"ok": False, "error": "Invalid URL"}, status_code=400)
    full_url = f"https://{domain}"
    text = _wizard_fetch_homepage(full_url)
    if not text:
        text = _wizard_fetch_homepage(f"http://{domain}")
    icp = _wizard_llm_guess_icp(domain, text)
    if 'error' in icp:
        return JSONResponse({"ok": False, "error": icp["error"]}, status_code=500)
    icp["domain"] = domain
    return JSONResponse({"ok": True, "icp": icp})


@app.post("/api/wizard_discover")
async def api_wizard_discover(request: Request, icp_json: str = Form(...), email: str = Form(default="")):
    """Run discovery with user-edited ICP. Email optional (for logging)."""
    try:
        icp = json.loads(icp_json)
    except Exception:
        return JSONResponse({"ok": False, "error": "bad icp_json"}, status_code=400)
    # log email if provided
    if email and email.strip():
        try:
            with db() as conn:
                conn.execute("""
                    insert into lead_views (email, url_input, niche_id, domains_json,
                                             contacts_revealed, ip_address, user_agent, antifraud_score, paid_status)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (email.lower().strip(), icp.get("domain", ""), None, "[]", 0,
                      request.client.host if request.client else "0.0.0.0",
                      request.headers.get("user-agent", "")[:80], 0.0, "free"))
                conn.commit()
        except Exception:
            pass
    # run discovery
    result = _wizard_discover(icp, n=20)
    return JSONResponse(result)



@app.get("/", response_class=HTMLResponse)
def landing():
    return HTMLResponse(env.get_template("landing.html").render())


@app.post("/generate", response_class=HTMLResponse)
def generate(request: Request, url: str = Form(...)):
    niche_id, niche_name, conf, debug = detect_niche(url)
    leads = fetch_clean_leads(niche_id, limit=5) if niche_id else []
    # If no clean leads in this niche, fall back to top clean leads across all niches
    if not leads:
        with db() as conn:
            rows = conn.execute("""
                SELECT e.event_id as event_id, e.source, e.event_type, e.company_name,
                       e.company_domain, e.raw_text, e.collected_at, e.evidence_url,
                       c.niche_id, c.score, c.buyer_contacts_json, n.name as niche_name
                FROM signal_events e
                JOIN signal_classifications c ON c.event_id = e.event_id
                LEFT JOIN niches n ON n.id = c.niche_id
                WHERE c.score IS NOT NULL
                  AND e.company_domain IS NOT NULL
                  AND e.company_domain != ''
                  AND e.company_domain NOT IN (
                      'greenhouse.io','lever.co','reddit.com','github.com','ycombinator.com',
                      'google.com','news.google.com','twitter.com','facebook.com',
                      'linkedin.com','medium.com','youtube.com','g2.com','capterra.com',
                      'trustpilot.com','glassdoor.com','instagram.com','producthunt.com',
                      'crunchbase.com','techcrunch.com','yahoo.com','aol.com','outlook.com',
                      'duckduckgo.com','w3.org','schema.org','github.io','wikipedia.org'
                  )
                  AND e.company_domain NOT LIKE 'news.%'
                  AND e.company_domain NOT LIKE 'github.com/%'
                  AND e.company_name IS NOT NULL
                  AND e.company_name != 'Unknown'
                ORDER BY c.score DESC, e.collected_at DESC
                LIMIT 5
            """).fetchall()
        for r in rows:
            d = dict(r)
            d["age_days"] = _age_days(d.get("collected_at"))
            d["age_label"] = _fmt_age(d.get("collected_at"))
            d["text"] = (d.get("raw_text") or "")[:280]
            d["score"] = float(d.get("score") or 0.0)
            contacts = []
            if d.get("buyer_contacts_json"):
                try:
                    payload = json.loads(d["buyer_contacts_json"])
                    contacts = payload.get("contacts", [])
                except Exception:
                    pass
            d["has_contacts"] = len(contacts) > 0
            d["contact_count"] = len(contacts)
            d["_contacts"] = contacts
            leads.append(d)
    return HTMLResponse(env.get_template("results.html").render(
        url=url,
        niche_id=niche_id,
        niche_name=niche_name or "Other",
        niche_conf=int(conf * 100),
        leads=leads,
        domains_json=json.dumps([l["company_domain"] for l in leads]),
    ))




# ============================================================
# Outscraper live helpers
# ============================================================
OS_API_KEY = os.getenv("OUTSCRAPER_API_KEY", "")

PERSONAL_DOMAINS = {"gmail.com","hotmail.com","yahoo.com","outlook.com","aol.com","icloud.com","protonmail.com","proton.me","mail.com","live.com","msn.com"}
BUYER_TITLES = [
    "founder","co-founder","co founder","ceo","chief","head of","vp","vice president",
    "director","marketing","growth","sales","partnership","partnerships","revenue",
    "demand generation","demand gen","business development","bd","cmo","cfo","coo",
    "product","engineering manager","devrel","developer relations","developer advocate",
]

def _is_corporate(email: str) -> bool:
    if not email or "@" not in email:
        return False
    dom = email.split("@", 1)[1].lower().strip()
    return dom not in PERSONAL_DOMAINS and not dom.endswith(".edu")

def _is_buyer_title(title: str) -> bool:
    if not title:
        return False
    t = title.lower()
    return any(kw in t for kw in BUYER_TITLES)

def _outscraper_contacts(domain: str, per_company: int = 5) -> list[dict]:
    """Live Outscraper query. Returns up to N best contacts for the domain."""
    if not OS_API_KEY:
        return []
    url = f"https://api.outscraper.cloud/leads-and-contacts?query={domain}&async=false&limit=1&contactsPerCompany={per_company}"
    try:
        req = urllib.request.Request(url, headers={"X-API-KEY": OS_API_KEY})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        items = data.get("data") or []
        if not items:
            return []
        contacts = (items[0] or {}).get("contacts") or []
        out = []
        for c in contacts:
            full = c.get("full_name") or c.get("name") or ""
            if not full:
                continue
            emails_raw = c.get("emails") or []
            email = ""
            for e in emails_raw:
                v = e.get("value") if isinstance(e, dict) else None
                if v and "@" in v:
                    email = v
                    break
            if not email:
                continue
            li_slug = (c.get("socials") or {}).get("linkedin") or ""
            li_url = ""
            if li_slug.startswith("http"):
                li_url = li_slug
            elif li_slug:
                li_url = f"https://www.linkedin.com/in/{li_slug}"
            out.append({
                "name": full,
                "email": email,
                "title": c.get("title") or "",
                "level": c.get("level") or "",
                "linkedin": li_url,
            })
        return out
    except Exception as ex:
        print(f"  [OS-LIVE ERR] {domain}: {ex}", flush=True)
        return []

def _rank_contacts(contacts: list[dict]) -> list[dict]:
    """Prefer corporate + buyer titles. Stable sort."""
    def key(c):
        corp = 1 if _is_corporate(c.get("email", "")) else 0
        buyer = 1 if _is_buyer_title(c.get("title", "")) else 0
        return (corp, buyer)
    return sorted(contacts, key=key, reverse=True)


@app.post("/reveal")
async def reveal(request: Request, email: str = Form(...), domains: str = Form(...), niche_id: str = Form(default=""), max_reveals: str = Form(default="3")):
    """After user submits email, reveal contacts (3 free / 5 paid) from the chosen domains.
    Order: 1) DB cache, 2) Outscraper live, 3) DIY SMTP fallback.
    Per contact: prefer corporate email + buyer title."""
    # 1. email validation
    email_valid, reason = is_valid_email(email); info = {}
    if not email_valid:
        return JSONResponse({"ok": False, "error": reason, "field": "email"}, status_code=400)
    # 2. antifraud
    ok_af, reason_af, info_af = antifraud_check(request, email)
    if not ok_af:
        return JSONResponse({"ok": False, "error": reason_af}, status_code=429)
    # 3. parse domains
    try:
        doms = json.loads(domains)
    except Exception:
        return JSONResponse({"ok": False, "error": "bad_domains"}, status_code=400)
    if not isinstance(doms, list) or not doms:
        return JSONResponse({"ok": False, "error": "no_domains"}, status_code=400)
    # 4. fetch contacts for first 3 domains
    revealed = []
    with db() as conn:
        cap = 5 if str(max_reveals).lower() in ("5", "paid", "true") else 3
        for d in doms[:cap]:
            contact_obj = None
            company_name = None
            cached_contacts = []
            # 4a. DB cache
            row = conn.execute("""
                SELECT e.company_name, e.company_domain, c.buyer_contacts_json
                FROM signal_events e
                JOIN signal_classifications c ON c.event_id = e.event_id
                WHERE e.company_domain = ?
                  AND c.buyer_contacts_json IS NOT NULL
                ORDER BY c.score DESC
                LIMIT 1
            """, (d,)).fetchone()
            if row:
                company_name = row["company_name"]
                try:
                    payload = json.loads(row["buyer_contacts_json"])
                    raw = payload.get("contacts", [])
                    for c in raw:
                        em = c.get("email") or ""
                        if em and "@" in em:
                            cached_contacts.append({
                                "name": c.get("name") or c.get("full_name") or "",
                                "email": em,
                                "title": c.get("title") or "",
                                "level": c.get("level") or "",
                                "linkedin": c.get("linkedin") or "",
                            })
                except Exception:
                    pass
            # 4b. APOLLO LIVE (primary, verified corporate, 1 credit)
            apollo_contact = apollo_top_buyer(d)
            # 4c. Outscraper live (fallback)
            live_contacts = _outscraper_contacts(d, per_company=6)
            # 4d. pick best: prefer verified corporate with buyer title
            all_contacts = cached_contacts + ([apollo_contact] if apollo_contact else []) + live_contacts
            # dedupe by email
            seen_emails = set()
            unique = []
            for c in all_contacts:
                em = c.get("email", "")
                if not em or em in seen_emails:
                    continue
                seen_emails.add(em)
                unique.append(c)
            ranked = _rank_contacts(unique)
            if ranked:
                contact_obj = ranked[0]
                # persist Apollo result to DB so next reveal is free
                if apollo_contact and apollo_contact.get("email"):
                    payload = json.dumps({"contacts": [apollo_contact], "source": "apollo", "fetched_at": time.time()})
                    conn.execute("""
                        UPDATE signal_classifications
                        SET buyer_contacts_json = ?
                        WHERE event_id IN (
                            SELECT event_id FROM signal_events WHERE company_domain = ? ORDER BY collected_at DESC LIMIT 1
                        )
                    """, (payload, d))
                    conn.commit()
            if contact_obj:
                revealed.append({
                    "company": company_name or d,
                    "domain": d,
                    "contact": contact_obj,
                })
    # 5. log the view
    with db() as conn:
        conn.execute("""
            insert into lead_views (email, url_input, niche_id, domains_json,
                                     contacts_revealed, ip_address, user_agent, antifraud_score)
            values (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            email.lower(), info_af.get("ip"), int(niche_id) if niche_id.isdigit() else None,
            json.dumps(doms), len(revealed),
            info_af["ip"], info_af["ua"], 0.1,
        ))
        conn.commit()
    return JSONResponse({"ok": True, "revealed": revealed, "total_in_niche": len(doms)})



@app.get("/pricing", response_class=HTMLResponse)
def pricing_get(submitted: bool = False, email: str = ""):
    return HTMLResponse(env.get_template("pricing.html").render(submitted=submitted, email=email))


@app.post("/pricing", response_class=HTMLResponse)
def pricing_post(request: Request, email: str = Form(...)):
    print(f"[LEAD] pricing signup: {email}", flush=True)
    return HTMLResponse(env.get_template("pricing.html").render(submitted=True, email=email))


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.4.0"}


# ============================================================
# Admin (existing)
# ============================================================
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    with db() as conn:
        total = conn.execute("select count(*) from signal_events").fetchone()[0]
        classified = conn.execute("select count(*) from signal_classifications where score is not null").fetchone()[0]
        enriched = conn.execute("select count(*) from signal_classifications where buyer_contacts_json is not null").fetchone()[0]
        niche_rows = conn.execute("""
            select n.id, n.name, count(e.event_id) as cnt, avg(c.score) as avg_score
            from niches n
            left join signal_classifications c on c.niche_id = n.id
            left join signal_events e on e.event_id = c.event_id
            group by n.id order by cnt desc
        """).fetchall()
        source_rows = conn.execute("select source, count(*) as cnt from signal_events group by source order by 2 desc").fetchall()
        lead_views_today = conn.execute("select count(*) from lead_views where created_at > datetime('now','-1 day')").fetchone()[0]
    return HTMLResponse(env.get_template("dashboard.html").render(
        total=total, classified=classified, leads=enriched,
        niches=[dict(r) for r in niche_rows],
        sources=[dict(r) for r in source_rows],
        lead_views_today=lead_views_today,
    ))


@app.get("/admin/leads", response_class=HTMLResponse)
def admin_leads():
    """Admin: see all email-gated lead views."""
    with db() as conn:
        rows = conn.execute("""
            select id, email, url_input, niche_id, contacts_revealed, ip_address,
                   created_at from lead_views order by created_at desc limit 100
        """).fetchall()
    return HTMLResponse("<h1>Lead views</h1><pre>" +
                        "\n".join(str(dict(r)) for r in rows) + "</pre>")


@app.get("/api/stats")
def api_stats():
    with db() as conn:
        return {
            "events": conn.execute("select count(*) from signal_events").fetchone()[0],
            "classifications": conn.execute("select count(*) from signal_classifications where score is not null").fetchone()[0],
            "leads": conn.execute("select count(*) from signal_classifications where buyer_contacts_json is not null").fetchone()[0],
            "lead_views_24h": conn.execute("select count(*) from lead_views where created_at > datetime('now','-1 day')").fetchone()[0],
        }


@app.get("/api/niches")
def api_niches():
    return NICHES_CFG.get("niches", [])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
