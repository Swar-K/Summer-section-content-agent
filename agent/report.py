"""Writes CAMPAIGN_SUMMARY.md from the files in a campaign folder (used by the first run and by re-renders)."""
from __future__ import annotations
import json
from pathlib import Path

BOARD_LABEL = {"existing": "existing board", "new": "NEW board: create it first", "suggested": "suggested board"}


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def write_summary(out: Path) -> Path:
    c = _load(out / "pinterest_campaign.json") or {}
    fb, ig = _load(out / "facebook_post.json"), _load(out / "instagram_post.json")
    boards, vids = _load(out / "boards_report.json"), _load(out / "video_report.json") or {}
    q = c.get("quality", {})
    kinds = {"article": "article only", "video": "video only", "both": "article + video"}
    lines = [
        f"# Content campaign: {c.get('article_title', 'Campaign')}",
        "",
        f"- Source: {kinds.get(c.get('source_kind', 'article'), c.get('source_kind', ''))}",
        f"- Destination: {c.get('article_url', '')}",
        (f"- Video: {c['video_url']} (read from: {c.get('video_source', '')})" if c.get("video_url") else "- Video: none"),
        f"- Pins generated: {len(c.get('pins', []))}",
        "- Pinterest publishing: disabled; human review required",
        "- Facebook: " + ("waiting for approval" if fb else "not generated"),
        f"- Quality checks passed: {q.get('passed_count', '?')}/{q.get('total', '?')}",
    ]
    lines += [f"- Note: {n}" for n in c.get("notes", [])]
    lines += ["- Files: `editor.html` (visual editor)" + "".join(f", `{k}`" for k, v in vids.items() if "error" not in v), ""]
    new = (boards or {}).get("new") or []
    if new:
        lines += ["## " + ("Boards to create first" if boards.get("mode") == "matched" else "Board suggestions"), ""]
        lines += [f"- {b['name']} (pins {', '.join(str(n) for n in b['pins'])})"
                  + (f": {b['description']}" if b.get("description") else "") for b in new] + [""]
    if fb:
        lines += ["## Facebook post", "", "````", fb["message"], "````", "", "- Card: `facebook_card.png`", ""]
    if ig:
        lines += ["## Instagram post", "", "````", ig["caption"], "````", "",
                  f"- Alt text: {ig.get('alt_text', '')}", "- Card: `instagram_card.png`", ""]
    for title, name in (("Instagram Reel script", "instagram_reel_script.md"), ("YouTube Short script", "youtube_short_script.md")):
        f = out / name
        if f.exists():
            lines += [f"## {title}", ""] + f.read_text(encoding="utf-8").splitlines()[2:] + [""]
    if vids:
        lines += ["## Videos", ""]
        for name, v in vids.items():
            lines.append(f"- `{name}`: " + (f"failed ({v['error']})" if "error" in v else
                         f"{v.get('seconds')} s, {v.get('aspect')}, voiceover: {'yes' if v.get('voiceover') else 'no'}"
                         + (f", {v['real_clips']} real clip(s)" if v.get("real_clips") else "")))
        lines.append("")
    lines.append("## Pin copy")
    for p in c.get("pins", []):
        status = BOARD_LABEL.get(p.get("board_status", ""), "")
        lines += [f"### Pin {p['number']}: {p['title']}",
                  f"- Image: `{p['image_file']}`",
                  f"- Angle: {p.get('angle', '')}",
                  f"- Description: {p['description']}",
                  f"- Board: {p['board']}" + (f" ({status})" if status else ""),
                  f"- Alt text: {p.get('alt_text', '')}",
                  f"- Link: {p['destination_url']}", ""]
    path = out / "CAMPAIGN_SUMMARY.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
