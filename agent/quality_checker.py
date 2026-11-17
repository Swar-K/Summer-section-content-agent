from __future__ import annotations
from pathlib import Path
from PIL import Image


def check_pin(path: Path, pin: dict, expected_url: str, image_meta: dict | None = None) -> dict:
    issues = []
    try:
        with Image.open(path) as im:
            if im.size != (1000, 1500):
                issues.append(f"Unexpected dimensions: {im.size}")
            if im.mode not in {"RGB", "RGBA"}:
                issues.append(f"Unexpected color mode: {im.mode}")
    except Exception as exc:
        issues.append(f"Image cannot be opened: {exc}")

    for field in ("headline", "title", "description", "board"):
        if not str(pin.get(field, "")).strip():
            issues.append(f"Missing metadata field: {field}")
    if not expected_url.startswith(("https://", "http://")):
        issues.append("Destination URL is not an absolute HTTP(S) URL.")
    headline = str(pin.get("headline", ""))
    if len(headline) > 90:
        issues.append("Headline is too long for the intended mobile-first design.")
    if image_meta and image_meta.get("clipped"):
        issues.append("On-image text did not fit and was cut off. Shorten the headline or subheadline.")
    return {"passed": not issues, "issues": issues, "image": str(path)}



def _check_card(path: Path, block: dict, kind: str, image_meta: dict | None) -> list[str]:
    issues = []
    try:
        with Image.open(path) as im:
            if im.size != (1080, 1350):
                issues.append(f"Unexpected {kind} card dimensions: {im.size}")
    except Exception as exc:
        issues.append(f"{kind} card cannot be opened: {exc}")
    if not str(block.get("headline", "")).strip():
        issues.append(f"Missing {kind} headline.")
    tips = block.get("tips") or []
    if len(tips) != 3 or not all(str(t).strip() for t in tips):
        issues.append(f"{kind} card needs exactly 3 non-empty points.")
    if image_meta and image_meta.get("clipped"):
        issues.append(f"Text on the {kind} card did not fit and was cut off.")
    return issues


def check_facebook(path: Path, fb: dict, message: str, link: str, image_meta: dict | None = None) -> dict:
    issues = _check_card(path, fb, "Facebook", image_meta)
    if not str(fb.get("post", "")).strip():
        issues.append("Missing Facebook post text.")
    if len(message) > 2000:
        issues.append("Facebook message is unusually long.")
    if not link.startswith(("https://", "http://")):
        issues.append("Facebook link is not an absolute HTTP(S) URL.")
    return {"passed": not issues, "issues": issues, "image": str(path)}


def check_instagram(path: Path, ig: dict, caption: str, image_meta: dict | None = None) -> dict:
    issues = _check_card(path, ig, "Instagram", image_meta)
    if not str(ig.get("caption", "")).strip():
        issues.append("Missing Instagram caption.")
    if len(caption) > 2200:
        issues.append("Instagram caption is over the 2,200 character limit.")
    if caption.count("#") > 30:
        issues.append("Instagram caption has more than 30 hashtags.")
    if not str(ig.get("alt_text", "")).strip():
        issues.append("Missing Instagram alt text.")
    return {"passed": not issues, "issues": issues, "image": str(path)}


def check_scripts(scripts: dict) -> dict:
    issues = []
    for kind in ("reel", "short"):
        s = scripts.get(kind) or {}
        if not str(s.get("hook", "")).strip():
            issues.append(f"{kind} script is missing a hook.")
        if len(s.get("scenes") or []) < 3:
            issues.append(f"{kind} script needs at least 3 scenes.")
    if len(str((scripts.get("short") or {}).get("title", ""))) > 100:
        issues.append("YouTube Short title is over 100 characters.")
    r, sh = scripts.get("reel") or {}, scripts.get("short") or {}
    if str(r.get("hook", "")).strip().lower() == str(sh.get("hook", "")).strip().lower() and r.get("hook"):
        issues.append("Reel and Short use the same hook; they should differ.")
    return {"passed": not issues, "issues": issues}
