from __future__ import annotations
import hashlib
import json
import re
import shutil
from datetime import date
from pathlib import Path
from .links import norm_url

DRAFT_ID_RE = re.compile(r"\d{4}-\d{2}-\d{2}-[0-9a-f]{8}")


def new_draft_id(url: str, today: date | None = None) -> str:
    digest = hashlib.sha1(norm_url(url).encode()).hexdigest()[:8]
    return f"{(today or date.today()).isoformat()}-{digest}"


def used_urls(drafts_dir: Path) -> set[str]:
    """URLs that already have a draft, so auto-pick never repeats an article."""
    used: set[str] = set()
    for p in Path(drafts_dir).glob("*/draft.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for key in ("article_url", "submitted_url"):
            if data.get(key):
                used.add(norm_url(data[key]))
    return used


def _tags(items, limit=None) -> str:
    tags = ["#" + h.lstrip("#").replace(" ", "") for h in items if isinstance(h, str) and h.strip()]
    return " ".join(tags[:limit] if limit else tags)


def build_facebook_message(fb: dict, disclosure: str, link: str, video_url: str = "",
                           label: str = "Read the full guide") -> str:
    parts = [fb["post"].strip()]
    if disclosure.strip():
        parts.append(disclosure.strip())
    parts.append(f"{label}: {link}")
    if video_url:
        parts.append(f"Watch the video: {video_url}")
    tags = _tags(fb.get("hashtags", []))
    if tags:
        parts.append(tags)
    return "\n\n".join(parts)


def build_instagram_caption(ig: dict, disclosure: str) -> str:
    parts = [ig["caption"].strip()]
    if disclosure.strip():
        parts.append(disclosure.strip())
    tags = _tags(ig.get("hashtags", []), 8)
    if tags:
        parts.append(tags)
    return "\n\n".join(parts)


def _scenes(scenes) -> list[str]:
    lines = []
    for i, s in enumerate(scenes, 1):
        line = f"{i}. **Visual:** {s['visual']} | **Voiceover:** {s['voiceover']}"
        if s.get("clip"):
            line += f" | **Clip from your video:** {s['clip']}"
        lines.append(line)
    return lines


def build_reel_md(title: str, reel: dict, link: str) -> str:
    lines = [f"# Instagram Reel script: {title}", "", f"**Hook:** {reel['hook']}", "", "**Scenes:**"]
    lines += _scenes(reel["scenes"])
    if reel.get("on_screen_text"):
        lines += ["", "**On-screen text:** " + " / ".join(reel["on_screen_text"])]
    lines += ["", f"**CTA:** {reel['cta']}", "", f"Link for bio: {link}"]
    return "\n".join(lines) + "\n"


def build_short_md(title: str, short: dict, link: str, video_url: str = "") -> str:
    lines = [f"# YouTube Short script: {title}", "", f"**Title:** {short['title']}", "",
             f"**Hook:** {short['hook']}", "", "**Scenes:**"]
    lines += _scenes(short["scenes"])
    if short.get("on_screen_text"):
        lines += ["", "**On-screen text:** " + " / ".join(short["on_screen_text"])]
    lines += ["", f"**CTA:** {short['cta']}", "",
              "**Description:**", f"{short['description']}", f"Full guide: {link}", "",
              f"**Pinned comment:** {short['pinned_comment']}"]
    if video_url:
        lines += ["", f"Source video: {video_url}"]
    return "\n".join(lines) + "\n"


BOARD_LABEL = {"existing": "existing board", "new": "NEW board: create it first", "suggested": "suggested board"}


def build_issue_md(draft_id: str, article: dict, fb_message: str, ig_caption: str, ig_alt: str,
                   reel_md: str, short_md: str, pins: list[dict], quality: dict, run_url: str,
                   repo: str, branch: str, boards_report: dict | None = None, video_files: list[str] | None = None,
                   source_kind: str = "article") -> str:
    raw = f"https://github.com/{repo}/blob/{branch}/drafts/{draft_id}"
    kinds = {"article": "article only", "video": "video only", "both": "article + video"}
    lines = [
        f"<!-- draft-id: {draft_id} -->",
        f"**Source:** [{article.get('title', 'Article')}]({article['url']}) ({kinds.get(source_kind, source_kind)})",
        "",
        f"**Quality checks:** {quality['passed_count']}/{quality['total']} passed",
    ]
    for issue in quality["issues"]:
        lines.append(f"- WARNING: {issue}")
    for note in quality.get("notes", []):
        lines.append(f"- Note: {note}")
    lines += [
        "",
        "## Facebook post (published when you add the `approved` label)",
        "````", fb_message, "````",
        f"![Facebook card]({raw}/facebook_card.png?raw=true)",
        "",
        "## Instagram post (upload manually)",
        "````", ig_caption, "````",
        f"**Alt text:** {ig_alt}",
        "",
        f"![Instagram card]({raw}/instagram_card.png?raw=true)",
        "",
        "## Instagram Reel script",
        "\n".join(reel_md.splitlines()[2:]),
        "",
        "## YouTube Short script",
        "\n".join(short_md.splitlines()[2:]),
        "",
        f"## Pinterest pins ({len(pins)}, review only: upload manually)",
    ]
    if run_url:
        lines.append(f"All pin images, the videos and `editor.html` are in the `summer-section-campaign` artifact of [this run]({run_url}).")
    new = (boards_report or {}).get("new") or []
    if new:
        head = ("Boards to create first" if boards_report.get("mode") == "matched" else "Board suggestions")
        lines += ["", f"**{head}:**"]
        lines += [f"- {b['name']} (pins {', '.join(str(n) for n in b['pins'])})"
                  + (f": {b['description']}" if b.get("description") else "") for b in new]
    for p in pins:
        status = BOARD_LABEL.get(p.get("board_status", ""), "")
        lines += ["", f"### Pin {p['number']}: {p['title']}",
                  f"Board: {p.get('board', '')}" + (f" ({status})" if status else "") + f" | Image: `{p['image_file']}`",
                  f"Link: {p['destination_url']}"]
        if p.get("alt_text"):
            lines.append(f"Alt text: {p['alt_text']}")
        lines += ["", p["description"]]
    if video_files:
        lines += ["", "## Videos and editor (in the artifact)",
                  *[f"- `{f}`" for f in video_files], "- `editor.html`: open it in your browser to edit pins and cards visually"]
    lines += ["", "---",
              f"To change the Facebook text before approving, edit `drafts/{draft_id}/draft.json` "
              "(`facebook_message`), or edit it in `editor.html` and run the Re-render workflow with this run's ID. "
              "To skip this draft, close the issue."]
    return "\n".join(lines) + "\n"


def write_draft(drafts_dir: Path, draft_id: str, draft: dict, images: dict[str, Path], issue_md: str) -> Path:
    folder = Path(drafts_dir) / draft_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "draft.json").write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, src in images.items():
        shutil.copyfile(src, folder / name)
    (folder / "issue.md").write_text(issue_md, encoding="utf-8")
    return folder
