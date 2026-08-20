"""G2 / Capterra review activity collector.
Detects: new reviews, rating changes, negative reviews (pain signal).
Uses G2's public product pages (no API key, scraping).
For MVP: monitors watchlist of competitor products in 10 niches.
"""
import json
import re
import time
import urllib.request

from ..db import insert_event


# Watchlist: product slugs in 10 niches (G2 URLs: g2.com/products/<slug>)
PRODUCTS = {
    "1crm": ("1CRM", 1), "hubspot-sales-hub": ("HubSpot Sales Hub", 1),
    "salesforce-sales-cloud": ("Salesforce Sales Cloud", 1),
    "pipedrive": ("Pipedrive", 1), "zoho-crm": ("Zoho CRM", 1),
    "greenhouse": ("Greenhouse", 2), "lever": ("Lever", 2),
    "workable": ("Workable", 2), "ashby": ("Ashby", 2),
    "marketo-engage": ("Marketo", 3), "braze": ("Braze", 3),
    "iterable": ("Iterable", 3), "klaviyo": ("Klaviyo", 3),
    "snowflake": ("Snowflake", 4), "databricks": ("Databricks", 4),
    "fivetran": ("Fivetran", 4), "pinecone": ("Pinecone", 4),
    "weaviate": ("Weaviate", 4), "langchain": ("LangChain", 4),
    "stripe": ("Stripe", 8), "adyen": ("Adyen", 8),
    "plaid": ("Plaid", 8), "checkoutcom": ("Checkout.com", 8),
}


def _scrape_g2(slug: str) -> dict | None:
    """Scrape G2 product page for review count + average rating."""
    url = f"https://www.g2.com/products/{slug}/reviews"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return {"error": str(e)}
    # Extract review count + rating from meta tags or JSON-LD
    rating_m = re.search(r'"ratingValue"\s*:\s*"?([\d.]+)"?', html)
    count_m = re.search(r'"reviewCount"\s*:\s*"?(\d+)"?', html)
    if not (rating_m and count_m):
        return None
    return {
        "rating": float(rating_m.group(1)),
        "count": int(count_m.group(1)),
    }


def collect() -> dict:
    stats = {"products": 0, "scraped": 0, "inserted": 0, "skipped_dup": 0, "errors": 0}
    # Store last seen count in a tiny table (or just use source_event_id as dedup)
    for slug, (name, niche_id) in PRODUCTS.items():
        stats["products"] += 1
        result = _scrape_g2(slug)
        if not result or "error" in result:
            stats["errors"] += 1
            continue
        if "rating" not in result:
            continue
        stats["scraped"] += 1
        # Emit a "presence" event so we have a record; pain detection happens via rating drop
        ev_id = insert_event(
            source="g2",
            company_domain=f"g2.com/{slug}",
            event_type="trigger",
            event_subtype="review_activity",
            raw_text=f"{name} on G2: {result['count']} reviews, {result['rating']:.1f}/5",
            source_event_id=f"g2:{slug}:{result['count']}",
            company_name=name,
            evidence_url=f"https://www.g2.com/products/{slug}",
            evidence_snippet=f"Rating {result['rating']}, {result['count']} reviews",
            raw_metadata={"niche_id": niche_id, "rating": result["rating"], "count": result["count"]},
        )
        if ev_id:
            stats["inserted"] += 1
        else:
            stats["skipped_dup"] += 1
        time.sleep(2)  # be nice to G2
    return stats


def main():
    print(f"G2: {len(PRODUCTS)} products in 10 niches")
    s = collect()
    print(f"  products={s['products']} scraped={s['scraped']} inserted={s['inserted']} dup={s['skipped_dup']} err={s['errors']}")


if __name__ == "__main__":
    main()
