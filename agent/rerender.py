"""Applies edits made in editor.html (edits.json) to a finished campaign WITHOUT calling Groq again:
re-renders the changed pins and cards, refreshes boards, the Facebook/Instagram text, the Video Pin,
the summary, the editor and the review draft.

    python -m agent.rerender --campaign output/<slug> --edits edits.json [--drafts drafts] [--no-videos]
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from .boards import assign_boards, load_boards
from .config import ROOT, load_brand
from .drafts import build_facebook_message, build_instagram_caption
from .editor_builder import build_editor
from .facebook_card import render_facebook_card, render_instagram_card
from .image_designer import effective_style, render_pin
from .quality_checker import check_facebook, check_instagram, check_pin
from .report import write_summary
from .video_maker import have_ffmpeg, make_video_pin

PIN_FIELDS = ("headline", "subheadline", "title", "description", "board", "alt_text", "style")
FB_FIELDS = ("headline", "tips", "post", "hashtags", "band")
IG_FIELDS = ("headline", "tips", "caption", "hashtags", "alt_text", "band")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_edits(campaign_dir: Path, edits: dict, brand: dict, boards: list[dict], drafts_dir: Path | None = None,
                rebuild_videos: bool = True) -> dict:
    campaign_dir = Path(campaign_dir)
    camp_path = campaign_dir / "pinterest_campaign.json"
    if not camp_path.exists():
        raise ValueError(f"{campaign_dir} is not a campaign folder (pinterest_campaign.json not found).")
    campaign = _read(camp_path)
    if edits.get("slug") and edits["slug"] != campaign_dir.name:
        raise ValueError(f"These edits are for the campaign '{edits['slug']}', not '{campaign_dir.name}'.")
    assets = campaign_dir / "assets"
    result = {"changed_pins": [], "facebook": False, "instagram": False, "issues": []}

    # ---- pins ----
    by_number = {int(p["number"]): p for p in campaign["pins"]}
    for key, patch in (edits.get("pins") or {}).items():
        pin = by_number.get(int(key))
        if pin is None:
            result["issues"].append(f"Pin {key} does not exist and was skipped.")
            continue
        for field in PIN_FIELDS:
            if field in patch:
                pin[field] = patch[field]
        pin["style"] = effective_style(pin)
        result["changed_pins"].append(int(key))

    board_report = assign_boards(campaign["pins"], boards)
    _write(campaign_dir / "boards_report.json", board_report)

    for number in result["changed_pins"]:
        pin = by_number[number]
        dest = campaign_dir / pin["image_file"]
        meta = render_pin(pin, brand, dest, [], "", "", False, cta_label=campaign.get("cta_label", "READ THE FULL GUIDE"),
                          assets_dir=assets)
        pin["image"], pin["style"] = meta, meta["style"]
        check = check_pin(dest, pin, campaign["article_url"], meta)
        result["issues"] += [f"Pin {number}: {i}" for i in check["issues"]]
    _write(camp_path, campaign)

    # ---- Facebook and Instagram ----
    footers = campaign.get("footers", {})
    draft_updates = {}
    fb_path = campaign_dir / "facebook_post.json"
    if edits.get("facebook") and fb_path.exists():
        fb = _read(fb_path)
        fb["content"].update({k: v for k, v in edits["facebook"].items() if k in FB_FIELDS})
        meta = render_facebook_card(fb["content"], brand, campaign_dir / fb["image_file"],
                                    footers.get("fb", "READ THE FULL GUIDE"))
        fb["message"] = build_facebook_message(fb["content"], fb.get("disclosure", ""), fb["link"],
                                               fb.get("video_url", ""), fb.get("label", "Read the full guide"))
        _write(fb_path, fb)
        check = check_facebook(campaign_dir / fb["image_file"], fb["content"], fb["message"], fb["link"], meta)
        result["issues"] += [f"Facebook: {i}" for i in check["issues"]]
        draft_updates["facebook_message"] = fb["message"]
        result["facebook"] = True
    ig_path = campaign_dir / "instagram_post.json"
    if edits.get("instagram") and ig_path.exists():
        ig = _read(ig_path)
        ig["content"].update({k: v for k, v in edits["instagram"].items() if k in IG_FIELDS})
        meta = render_instagram_card(ig["content"], brand, campaign_dir / ig["image_file"],
                                     footers.get("ig", "FULL GUIDE: LINK IN BIO"))
        ig["caption"] = build_instagram_caption(ig["content"], ig.get("disclosure", ""))
        ig["alt_text"] = ig["content"].get("alt_text", "")
        _write(ig_path, ig)
        check = check_instagram(campaign_dir / ig["image_file"], ig["content"], ig["caption"], meta)
        result["issues"] += [f"Instagram: {i}" for i in check["issues"]]
        result["instagram"] = True

    # ---- the review draft that publishing reads ----
    draft_id = campaign.get("draft_id")
    if drafts_dir and draft_id and (Path(drafts_dir) / draft_id).is_dir() and (result["facebook"] or result["instagram"]):
        folder = Path(drafts_dir) / draft_id
        if draft_updates:
            d = _read(folder / "draft.json")
            d.update(draft_updates)
            _write(folder / "draft.json", d)
        for name in ("facebook_card.png", "instagram_card.png"):
            if (campaign_dir / name).exists():
                shutil.copyfile(campaign_dir / name, folder / name)
        result["draft_updated"] = draft_id

    # ---- video pin, summary, editor ----
    if rebuild_videos and result["changed_pins"] and have_ffmpeg() and (campaign_dir / "video_pin.mp4").exists():
        files = [campaign_dir / p["image_file"] for p in campaign["pins"]]
        vr = _read(campaign_dir / "video_report.json") if (campaign_dir / "video_report.json").exists() else {}
        vr["video_pin.mp4"] = make_video_pin(files, campaign_dir / "video_pin.mp4")
        _write(campaign_dir / "video_report.json", vr)
        result["video_pin_rebuilt"] = True
    write_summary(campaign_dir)
    fb_obj = _read(fb_path) if fb_path.exists() else None
    ig_obj = _read(ig_path) if ig_path.exists() else None
    build_editor(campaign_dir, brand, campaign, boards,
                 facebook={**fb_obj["content"]} if fb_obj else None, instagram={**ig_obj["content"]} if ig_obj else None,
                 cta_label=campaign.get("cta_label", "READ THE FULL GUIDE"),
                 fb_footer=footers.get("fb", "READ THE FULL GUIDE"), ig_footer=footers.get("ig", "FULL GUIDE: LINK IN BIO"))
    _write(campaign_dir / "edits_applied.json", {"edits": edits, "result": result})
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--campaign", required=True, help="campaign folder, e.g. output/my-article")
    ap.add_argument("--edits", required=True, help="edits.json downloaded from editor.html")
    ap.add_argument("--drafts", default=os.getenv("DRAFTS_DIR") or "drafts")
    ap.add_argument("--no-videos", action="store_true")
    args = ap.parse_args(argv)
    try:
        edits = json.loads(Path(args.edits).read_text(encoding="utf-8"))
        brand = load_brand(Path(os.getenv("BRAND_CONFIG") or ROOT / "brand/summer_section.json"))
        boards = load_boards(Path(os.getenv("BOARDS_CONFIG") or ROOT / "brand/boards.json"))
        res = apply_edits(Path(args.campaign), edits, brand, boards, Path(args.drafts), not args.no_videos)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"Re-rendered pins {res['changed_pins'] or 'none'}; Facebook: {res['facebook']}; Instagram: {res['instagram']}")
    for i in res["issues"]:
        print(f"WARNING: {i}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
