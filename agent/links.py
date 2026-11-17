from __future__ import annotations
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def norm_url(url: str) -> str:
    """Comparable form of a URL: lower-case scheme/host, no query, no trailing slash."""
    u = urlparse((url or "").strip())
    return f"{u.scheme.lower()}://{u.netloc.lower()}{u.path.rstrip('/')}"


def add_utm(url: str, source: str, campaign: str, content: str = "") -> str:
    """Add UTM tags so analytics can show which channel (and which pin) sent the visit."""
    u = urlparse(url)
    q = dict(parse_qsl(u.query, keep_blank_values=True))
    q.update({"utm_source": source, "utm_medium": "social", "utm_campaign": campaign})
    if content:
        q["utm_content"] = content
    return urlunparse(u._replace(query=urlencode(q)))
