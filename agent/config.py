from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DEFAULT_MODEL = "openai/gpt-oss-120b"


def _env(name: str, default: str = "") -> str:
    """Environment value, treating an empty string (e.g. an unset GitHub variable) as 'not set'."""
    return os.getenv(name, "").strip() or default


@dataclass
class Settings:
    groq_api_key: str
    model: str
    article_url: str
    openai_api_key: str
    image_model: str
    use_ai_backgrounds: bool
    pin_count: int
    article_char_limit: int
    output_dir: Path
    brand_path: Path
    # --- added for the combined Pinterest + Facebook + Reel agent (all optional) ---
    wp_site_url: str = ""          # used only to auto-pick the next article when ARTICLE_URL is blank
    wp_category_id: str = ""
    season: str = ""               # optional seasonal angle for the Facebook/Reel copy, e.g. "summer heat"
    disclosure: str = ""           # affiliate disclosure line added to the Facebook post
    social_outputs: bool = True    # False = Pinterest only (original behaviour)
    run_url: str = ""
    video_url: str = ""            # optional YouTube link (long video or Short)
    video_notes: str = ""          # optional pasted script/transcript/key points (best fallback)
    youtube_api_key: str = ""      # optional; gives reliable title, description, chapters and duration
    include_video_link: bool = True
    video_char_limit: int = 6000   # characters of transcript per Groq request
    video_max_chunks: int = 5      # long videos: how many sections to read (evenly sampled)
    drafts_dir: Path = field(default_factory=lambda: Path("drafts"))
    destination_url: str = ""      # video-only runs: where pins and posts should link (default: the video itself)
    boards_path: Path = field(default_factory=lambda: ROOT / "brand/boards.json")
    make_videos: bool = True       # build the Video Pin, Reel and Short as MP4 files (needs ffmpeg)
    use_tts: bool = True           # spoken voiceover with edge-tts; falls back to silent captions
    tts_voice: str = "en-US-AndrewNeural"
    video_file: str = ""           # optional: source MP4 (repo path or https URL) to cut real clips from


def _read_notes() -> str:
    """VIDEO_NOTES plus the contents of VIDEO_NOTES_FILE (a path inside this repo)."""
    notes = os.getenv("VIDEO_NOTES", "").strip()
    rel = _env("VIDEO_NOTES_FILE")
    if rel:
        path = (ROOT / rel).resolve()
        if ROOT not in path.parents or not path.is_file():
            raise ValueError(f"VIDEO_NOTES_FILE must be a file inside this repository: {rel}")
        notes = (notes + "\n\n" + path.read_text(encoding="utf-8", errors="replace")[:20000]).strip()
    return notes


def load_settings() -> Settings:
    url = _env("ARTICLE_URL")
    wp = _env("WP_SITE_URL")
    has_video = bool(_env("VIDEO_URL") or os.getenv("VIDEO_NOTES", "").strip() or _env("VIDEO_NOTES_FILE"))
    if not url and not wp and not has_video:
        raise ValueError("Provide an article URL and/or a video URL (or video notes). To auto-pick the next "
                         "unused article instead, set WP_SITE_URL.")
    try:
        pins = int(_env("PINS_PER_ARTICLE", "10"))
    except ValueError:
        raise ValueError("PINS_PER_ARTICLE must be a whole number between 1 and 15.")
    if not 1 <= pins <= 15:
        raise ValueError("PINS_PER_ARTICLE must be a whole number between 1 and 15.")
    return Settings(
        groq_api_key=_env("GROQ_API_KEY"),
        model=_env("GROQ_MODEL", DEFAULT_MODEL),
        article_url=url,
        openai_api_key=_env("OPENAI_API_KEY"),
        image_model=_env("OPENAI_IMAGE_MODEL", "gpt-image-1"),
        use_ai_backgrounds=_env("USE_AI_BACKGROUNDS", "true").lower() == "true",
        pin_count=pins,
        article_char_limit=int(_env("ARTICLE_CHAR_LIMIT", "9000")),
        output_dir=Path(_env("OUTPUT_DIR", str(ROOT / "output"))),
        brand_path=Path(_env("BRAND_CONFIG", str(ROOT / "brand/summer_section.json"))),
        wp_site_url=wp,
        wp_category_id=_env("WP_CATEGORY_ID"),
        season=_env("SEASON"),
        disclosure=_env("DISCLOSURE"),
        social_outputs=_env("SOCIAL_OUTPUTS", "true").lower() == "true",
        run_url=_env("RUN_URL"),
        video_url=_env("VIDEO_URL"),
        video_notes=_read_notes(),
        youtube_api_key=_env("YOUTUBE_API_KEY"),
        include_video_link=_env("INCLUDE_VIDEO_LINK", "true").lower() == "true",
        video_char_limit=int(_env("VIDEO_CHAR_LIMIT", "6000")),
        video_max_chunks=int(_env("VIDEO_MAX_CHUNKS", "5")),
        drafts_dir=Path(_env("DRAFTS_DIR", "drafts")),
        destination_url=_env("DESTINATION_URL"),
        boards_path=Path(_env("BOARDS_CONFIG", str(ROOT / "brand/boards.json"))),
        make_videos=_env("MAKE_VIDEOS", "true").lower() == "true",
        use_tts=_env("USE_TTS", "true").lower() == "true",
        tts_voice=_env("TTS_VOICE", "en-US-AndrewNeural"),
        video_file=_env("VIDEO_FILE"),
    )


def load_brand(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
