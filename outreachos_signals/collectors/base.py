"""Shared utilities for collectors."""
import json
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from ..db import insert_event


def http_get(url: str, headers: dict | None = None, timeout: int = 30, retries: int = 3) -> bytes:
    """GET with retries, no external deps."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "outreachos-signals/0.1", **(headers or {})},
    )
    last_err = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last_err = e
            time.sleep(2 ** i)
    raise RuntimeError(f"GET {url} failed: {last_err}")


def http_get_json(url: str, **kw) -> Any:
    raw = http_get(url, **kw)
    return json.loads(raw)


def domain_from_url(url: str) -> str:
    """Extract clean domain (no www)."""
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def emit(source: str, event_type: str, **kw) -> str | None:
    """Convenience: insert_event with source first."""
    return insert_event(source, event_type=event_type, **kw)


def load_niches() -> list[dict]:
    """Load niche config from config/niches.yaml (stdlib yaml fallback to manual)."""
    import yaml  # type: ignore
    p = __import__("pathlib").Path(__file__).resolve().parent.parent.parent / "config" / "niches.yaml"
    with open(p) as f:
        return yaml.safe_load(f)["niches"]
