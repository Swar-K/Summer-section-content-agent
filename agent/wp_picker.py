from __future__ import annotations
import requests
from .links import norm_url

USER_AGENT = "SummerSectionContentAgent/1.0 (+content transformation; contact site owner)"


def pick_unused_article(wp_site_url: str, category_id: str, used: set[str]) -> str:
    """Newest WordPress post whose URL has not been drafted yet. Returns '' when there is none."""
    if not wp_site_url:
        raise ValueError("No article URL was given and WP_SITE_URL is not set, so the next article "
                         "cannot be auto-picked.")
    params = {"per_page": 30, "_fields": "link"}
    if category_id:
        params["categories"] = category_id
    r = requests.get(f"{wp_site_url.rstrip('/')}/wp-json/wp/v2/posts", params=params,
                     headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    for post in r.json():
        link = post.get("link")
        if link and norm_url(link) not in used:
            return link
    return ""
