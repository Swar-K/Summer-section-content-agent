"""Reads a YouTube video (long or short) into text the planner can use.

Fallback ladder, so one blocked request never kills the run:
  1. captions/transcript via youtube-transcript-api (YouTube sometimes blocks cloud IPs such as GitHub's)
  2. title, description, tags and chapters via the YouTube Data API (needs YOUTUBE_API_KEY) or the keyless oEmbed endpoint
  3. notes pasted by the site owner (VIDEO_NOTES / VIDEO_NOTES_FILE), e.g. the script the video was made from
"""
from __future__ import annotations
import html
import re
from urllib.parse import parse_qs, urlparse
import requests

USER_AGENT = "SummerSectionContentAgent/1.0 (+content transformation; contact site owner)"
ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHAPTER_RE = re.compile(r"^\s*\(?((?:\d{1,2}:)?\d{1,2}:\d{2})\)?\s*[-\u2013\u2014:]?\s*(.+?)\s*$")


def parse_video_id(url: str) -> str:
    u = urlparse((url or "").strip())
    host = u.netloc.lower()
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    vid = ""
    if host == "youtu.be":
        vid = u.path.strip("/").split("/")[0]
    elif host in {"youtube.com", "music.youtube.com", "youtube-nocookie.com"}:
        if u.path == "/watch":
            vid = (parse_qs(u.query).get("v") or [""])[0]
        else:
            parts = [p for p in u.path.split("/") if p]
            if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live", "v"}:
                vid = parts[1]
    if not ID_RE.match(vid):
        raise ValueError("Could not find a YouTube video ID in that URL. Use a youtube.com/watch, "
                         "youtu.be or youtube.com/shorts link.")
    return vid


def parse_ts(s: str):
    m = re.fullmatch(r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})", (s or "").strip())
    if not m:
        return None
    return int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))


def fmt_ts(sec) -> str:
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def parse_chapters(description: str) -> list[dict]:
    """Chapters written in the description ('0:00 Intro'). YouTube requires the first one at 0:00."""
    chapters = []
    for line in (description or "").splitlines():
        m = CHAPTER_RE.match(line)
        if m and parse_ts(m.group(1)) is not None:
            chapters.append({"start": parse_ts(m.group(1)), "title": m.group(2)[:100]})
    return chapters if len(chapters) >= 2 and chapters[0]["start"] == 0 else []


def _iso_duration(s: str) -> int:
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return 0
    h, mi, se = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + se


def fetch_metadata(video_id: str, api_key: str = "") -> dict:
    meta = {"title": "", "channel": "", "description": "", "tags": [], "duration_seconds": 0}
    if api_key:
        try:
            r = requests.get("https://www.googleapis.com/youtube/v3/videos",
                             params={"part": "snippet,contentDetails", "id": video_id, "key": api_key}, timeout=20)
            r.raise_for_status()
            items = r.json().get("items") or []
            if items:
                sn = items[0]["snippet"]
                meta.update(title=sn.get("title", ""), channel=sn.get("channelTitle", ""),
                            description=sn.get("description", ""), tags=(sn.get("tags") or [])[:20],
                            duration_seconds=_iso_duration(items[0]["contentDetails"].get("duration", "")))
                return meta
        except Exception as exc:    # never print the exception text: it can contain the API key in the URL
            print(f"  YouTube Data API unavailable ({type(exc).__name__}); trying oEmbed.")
    try:
        r = requests.get("https://www.youtube.com/oembed",
                         params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"},
                         headers={"User-Agent": USER_AGENT}, timeout=20)
        r.raise_for_status()
        d = r.json()
        meta.update(title=d.get("title", ""), channel=d.get("author_name", ""))
    except Exception as exc:
        print(f"  oEmbed unavailable ({type(exc).__name__}).")
    return meta


def fetch_transcript(video_id: str):
    """List of {'start': seconds, 'text': str}, or None. Callers must cope with None."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        print("  youtube-transcript-api is not installed.")
        return None
    langs = ["en", "en-US", "en-GB"]
    try:
        api = YouTubeTranscriptApi()
        if hasattr(api, "list"):
            listing = api.list(video_id)
            try:
                tr = listing.find_transcript(langs)
            except Exception:
                tr = next(iter(listing))
            fetched = tr.fetch()
        else:                                           # older releases
            fetched = YouTubeTranscriptApi.get_transcript(video_id, languages=langs)
        raw = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else list(fetched)
        segs = []
        for s in raw:
            text = s["text"] if isinstance(s, dict) else s.text
            start = s["start"] if isinstance(s, dict) else s.start
            text = re.sub(r"\s+", " ", html.unescape(text or "")).strip()
            if text:
                segs.append({"start": float(start), "text": text})
        return segs or None
    except Exception as exc:
        print(f"  Transcript unavailable ({type(exc).__name__}). YouTube may block GitHub's servers; "
              "paste the script into video_notes as a fallback.")
        return None


def to_blocks(segs: list[dict], span: int = 30) -> list[dict]:
    """Merge caption fragments into ~30-second blocks: far fewer tokens, timestamps kept."""
    blocks, cur, start = [], [], None
    for s in segs:
        if start is None:
            start = s["start"]
        cur.append(s["text"])
        if s["start"] - start >= span:
            blocks.append({"start": int(start), "text": " ".join(cur)})
            cur, start = [], None
    if cur:
        blocks.append({"start": int(start or 0), "text": " ".join(cur)})
    return blocks


def blocks_text(blocks: list[dict]) -> str:
    return "\n".join(f"[{fmt_ts(b['start'])}] {b['text']}" for b in blocks)


def load_video(url: str, api_key: str = "", notes: str = "") -> dict | None:
    """Everything we could learn about the video. 'source' says how good it is:
    transcript > notes > metadata > none."""
    notes = (notes or "").strip()[:20000]
    if not (url or "").strip() and not notes:
        return None
    vid = parse_video_id(url) if (url or "").strip() else ""
    video = {"video_id": vid, "url": f"https://www.youtube.com/watch?v={vid}" if vid else "",
             "title": "", "channel": "", "description": "", "tags": [], "duration_seconds": 0,
             "chapters": [], "blocks": [], "notes": notes, "source": "none", "is_short": False,
             "thumbnail_urls": [f"https://img.youtube.com/vi/{vid}/maxresdefault.jpg"] if vid else [],
             # YouTube's own stills: the cover plus frames taken at roughly 25%, 50% and 75% of the video
             "frame_urls": ([f"https://img.youtube.com/vi/{vid}/maxresdefault.jpg"]
                            + [f"https://img.youtube.com/vi/{vid}/{i}.jpg" for i in (1, 2, 3)]) if vid else []}
    if vid:
        video.update(fetch_metadata(vid, api_key))
        video["chapters"] = parse_chapters(video["description"])
        segs = fetch_transcript(vid)
        if segs:
            video["blocks"] = to_blocks(segs)
            if not video["duration_seconds"]:
                video["duration_seconds"] = int(segs[-1]["start"]) + 5
        video["is_short"] = "/shorts/" in url or 0 < video["duration_seconds"] <= 60
    if video["blocks"]:
        video["source"] = "transcript"
    elif notes:
        video["source"] = "notes"
    elif video["title"] or video["description"]:
        video["source"] = "metadata"
    return video
